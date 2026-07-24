#!/usr/bin/env python3
"""
scraper.py — Cloudflare API docs scraper
Crawls developers.cloudflare.com/api/ and writes public/endpoints.json

Usage:
  python3 scraper.py            incremental — only re-fetch pages that changed
  python3 scraper.py --force    full re-scrape of every page

This is a BUILD-TIME step. The server only *serves* the resulting JSON as a
static file (public/endpoints.json), so the artifact is portable: a Cloudflare
Worker could bundle it directly without ever running this script at runtime.

Incremental scraping
--------------------
A manifest (public/endpoints-manifest.json) records each page's Last-Modified
header. On a normal run we send a cheap HEAD request per URL (~0.3s vs ~0.9s for
a full GET) and only download pages whose Last-Modified changed. This turns a
refresh from ~5-6 min into ~30-60s. `--force` ignores the manifest entirely.

Parsing notes
-------------
Each docs endpoint page renders parameters as a nested property tree using
`stldocs-*` CSS classes. For each parameter group (path / query / body) we:
  * split on `stldocs-property-declaration`
  * dedupe by name (union-of-variants bodies repeat field names per variant)
  * drop PascalCase wrapper names (e.g. `ARecord`, `ZonesNELValue`) and the
    synthetic `body` wrapper — real CF API fields are always lowercase/snake_case
  * detect object / array / enum / scalar types from the type-signature region
"""

import sys
import re
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from html import unescape
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

DOCS_BASE     = "https://developers.cloudflare.com"
API_INDEX     = DOCS_BASE + "/api/"
PUBLIC_DIR    = Path(__file__).parent / "public"
ENDPOINTS_FILE = PUBLIC_DIR / "endpoints.json"
MANIFEST_FILE  = PUBLIC_DIR / "endpoints-manifest.json"
CONCURRENCY   = 8   # parallel fetches — threads handle I/O wait fine
HEADERS       = {"User-Agent": "cf-api-builder/2.0 (educational tool)"}


# ── HTTP ──────────────────────────────────────────────────────────────────────

def fetch(url: str, retries: int = 3) -> tuple[str | None, str | None]:
    """Return (html, last_modified). The Last-Modified comes from the same
    response, so a changed page costs one request, not a GET + a separate HEAD."""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read().decode("utf-8", errors="replace")
                return body, r.headers.get("Last-Modified")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and i < retries - 1:
                time.sleep(1.5 * (i + 1)); continue
            return None, None
        except Exception:
            if i < retries - 1:
                time.sleep(1.0); continue
            return None, None
    return None, None


def head_last_modified(url: str) -> str | None:
    """Cheap HEAD request → Last-Modified header (or None on failure)."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.headers.get("Last-Modified")
    except Exception:
        return None


# ── URL discovery ─────────────────────────────────────────────────────────────

def get_endpoint_urls() -> list[str]:
    print("  Fetching API index…", flush=True)
    html, _ = fetch(API_INDEX)
    if not html:
        raise RuntimeError("Could not fetch API index")

    hrefs = re.findall(r'href="(/api/resources/[^"]+)"', html)
    endpoint_paths = [h for h in hrefs if "/methods/" in h and re.search(r"/methods/[^/]+/?$", h)]

    seen, urls = set(), []
    for p in endpoint_paths:
        url = DOCS_BASE + (p if p.endswith("/") else p + "/")
        if url not in seen:
            seen.add(url); urls.append(url)

    print(f"  Found {len(urls)} endpoint URLs", flush=True)
    return urls


# ── HTML utilities ────────────────────────────────────────────────────────────

def strip_tags(html: str) -> str:
    text = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)  # React splits idents with comments
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(unescape(text).split()).strip()


def to_title(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("_", " ").split())


# ── Page parsing ──────────────────────────────────────────────────────────────

def parse_page(html: str, url: str) -> dict | None:
    m = re.search(r"/api/resources/([^/]+)(.*?)/methods/([^/]+)/?$", url)
    if not m:
        return None
    resource, middle, method_slug = m.group(1), m.group(2), m.group(3)
    sub_parts = re.findall(r"/subresources/([^/]+)", middle)
    tag     = to_title(resource)
    sub_tag = " / ".join(to_title(s) for s in sub_parts)

    method_m = re.search(
        r'class="stldocs-method-route"[^>]*>[\s\S]{0,1200}?'
        r'aria-label="(GET|POST|PUT|PATCH|DELETE|HEAD)"',
        html, re.IGNORECASE,
    ) or re.search(r"curl\s+-X\s+(GET|POST|PUT|PATCH|DELETE)", html, re.IGNORECASE)
    if not method_m:
        return None
    http_method = method_m.group(1).upper()

    path_m = re.search(r'class="stldocs-method-route-endpoint"[^>]*>([^<]+)<', html)
    if not path_m:
        return None
    api_path = path_m.group(1).strip()

    h1_m = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html, re.IGNORECASE)
    summary = strip_tags(h1_m.group(1)) if h1_m else to_title(method_slug) + " " + tag

    desc_m = re.search(
        r'class="stldocs-method-description"[^>]*>[\s\S]*?<p>([\s\S]*?)</p>',
        html, re.IGNORECASE,
    )
    description = strip_tags(desc_m.group(1))[:300] if desc_m else ""

    return {
        "tag": tag, "subTag": sub_tag, "method": http_method, "path": api_path,
        "summary": summary, "description": description, "docsUrl": url,
        "parameters": parse_parameters(html),
    }


def parse_parameters(html: str) -> dict:
    result = {"path": [], "query": [], "body": []}
    ps_m = re.search(
        r'class="stldocs-method-parameters"([\s\S]*?)(?=class="stldocs-method-example|</main>)',
        html,
    )
    if not ps_m:
        return result
    ps = ps_m.group(1)
    groups = re.findall(
        r'data-stldocs-property-group="(\w+)"([\s\S]*?)(?=data-stldocs-property-group="|$)',
        ps,
    )
    for gtype, gcontent in groups:
        target = {"p": "path", "q": "query", "body": "body"}.get(gtype)
        if target:
            result[target] = parse_group(gcontent)
    return result


def parse_group(html: str) -> list[dict]:
    if not BeautifulSoup:
        raise RuntimeError(
            "BeautifulSoup is required for nested schema parsing. "
            "Install with: python3 -m pip install beautifulsoup4"
        )

    soup = BeautifulSoup(f"<root>{html}</root>", "html.parser")
    root = soup.find("root")
    if not root:
        return []

    containers = root.find_all("div", class_="stldocs-properties", recursive=False)
    if not containers:
        return parse_properties_container(root)

    nodes: list[dict] = []
    for container in containers:
        nodes = merge_nodes(nodes, parse_properties_container(container))
    return nodes


def parse_properties_container(container) -> list[dict]:
    props = container.find_all("div", class_="stldocs-property", recursive=False)
    parsed: list[dict] = []

    for prop in props:
        node = parse_property_node(prop)
        if not node:
            continue

        wrapper = node.pop("_wrapper", None)
        if wrapper in {"variant", "entry", "items"}:
            parsed = merge_nodes(parsed, node.get("children", []))
            continue
        if wrapper == "member":
            continue

        # Skip synthetic wrappers that still occasionally appear as plain nodes.
        name = node.get("name", "")
        if name == "body":
            if node.get("properties"):
                parsed = merge_nodes(parsed, node.get("properties", []))
            elif node.get("items", {}).get("properties"):
                parsed = merge_nodes(parsed, node["items"].get("properties", []))
            continue
        if name and name[0].isupper() and node.get("properties"):
            parsed = merge_nodes(parsed, node.get("properties", []))
            continue
        if name and name[0].isupper() and node.get("items", {}).get("properties"):
            parsed = merge_nodes(parsed, node["items"].get("properties", []))
            continue
        if name and name[0].isupper():
            continue

        if looks_like_model_wrapper(node):
            parsed = merge_nodes(parsed, node.get("properties", []))
            continue

        parsed = merge_nodes(parsed, [node])

    return parsed


def parse_property_node(prop) -> dict | None:
    details = prop.find("details", class_="stldocs-expander", recursive=False)

    if details:
        summary = details.find("summary", class_="stldocs-expander-summary")
        info = summary.find("div", class_="stldocs-property-info") if summary else None
        decl = info.find("div", class_="stldocs-property-declaration") if info else None
        desc = info.find("div", class_="stldocs-property-description") if info else None

        children: list[dict] = []
        children_root = details.find("div", class_="stldocs-property-children")
        if children_root:
            nested = children_root.find_all("div", class_="stldocs-properties", recursive=False)
            if nested:
                for container in nested:
                    children = merge_nodes(children, parse_properties_container(container))
            else:
                children = merge_nodes(children, parse_properties_container(children_root))
    else:
        info = prop.find("div", class_="stldocs-property-info", recursive=False)
        decl = info.find("div", class_="stldocs-property-declaration") if info else None
        desc = info.find("div", class_="stldocs-property-description") if info else None
        children = []

    if not decl:
        return None

    info_id = info.get("id", "") if info else ""
    segments = parse_id_segments(info_id)
    wrapper = infer_wrapper_kind(segments)

    node = {
        "name": infer_name(decl, segments),
        "type": infer_type(decl),
        "required": not is_optional(decl),
        "description": normalize_description(desc.get_text(" ", strip=True) if desc else ""),
        "enum": infer_enum(decl),
    }

    # Wrappers (variants/items/allOf entries) are structural, not user fields.
    if wrapper in {"variant", "entry", "items", "member"}:
        return {"_wrapper": wrapper, "children": children}

    if not node["name"]:
        return None

    if node["type"] == "object" and children:
        node["properties"] = children

    if node["type"] == "array":
        item_type = infer_array_item_type(decl)
        if children:
            node["items"] = {"type": "object", "properties": children}
        else:
            node["items"] = {"type": item_type}

    return node


def parse_id_segments(info_id: str) -> list[tuple[str, str]]:
    if not info_id:
        return []
    clean = info_id.replace("&gt;", ">")
    parts = [p.strip() for path in clean.split("+") for p in path.split(">")]
    segments: list[tuple[str, str]] = []
    for part in parts:
        if not part:
            continue
        m = re.match(r"\(([^)]+)\)\s*(.*)$", part)
        if not m:
            continue
        segments.append((m.group(1).strip().lower(), m.group(2).strip()))
    return segments


def infer_wrapper_kind(segments: list[tuple[str, str]]) -> str | None:
    for kind, _ in reversed(segments):
        if kind in {"variant", "entry", "items", "member"}:
            return kind
    return None


def infer_name(decl, segments: list[tuple[str, str]]) -> str | None:
    pn = decl.find("span", class_="stldocs-type-propertyname")
    if pn:
        ident = pn.find("span", class_="stldocs-text-identifier")
        raw = ident.get_text(" ", strip=True) if ident else pn.get_text(" ", strip=True)
        name = strip_tags(raw)
        if name and len(name) <= 120 and "{" not in name:
            return name

    for kind, value in reversed(segments):
        if kind in {"property", "param"} and value:
            return value
    return None


def is_optional(decl) -> bool:
    txt = decl.get_text(" ", strip=True).lower()
    return " optional " in f" {txt} "


def infer_enum(decl) -> list[str] | None:
    literals = []
    for lit in decl.find_all("span", class_="stldocs-literal-string"):
        val = lit.get_text(" ", strip=True).replace('"', "").strip()
        if 0 < len(val) < 120:
            literals.append(val)
    if not literals:
        return None
    seen, out = set(), []
    for val in literals:
        if val not in seen:
            seen.add(val)
            out.append(val)
    return out or None


def infer_type(decl) -> str:
    if decl.find("span", class_="stldocs-type-array"):
        return "array"

    preview_prefix = decl.find("span", class_="stldocs-type-preview-prefix")
    if preview_prefix and preview_prefix.get_text(" ", strip=True).lower() == "object":
        return "object"

    if decl.find("span", class_="stldocs-type-brace"):
        return "object"

    enums = infer_enum(decl)
    if enums:
        return "string"

    plain = decl.find("span", class_="stldocs-type-plain")
    if plain:
        t = plain.get_text(" ", strip=True).lower()
        if t in {"string", "boolean", "number", "integer", "null"}:
            return t
        # Generic fallback for uncommon docs labels.
        if "int" in t:
            return "integer"
        if "bool" in t:
            return "boolean"
        if "num" in t or "float" in t:
            return "number"
        return "string"

    return "string"


def infer_array_item_type(decl) -> str:
    # Most docs render this as "array of <plain>".
    types = [x.get_text(" ", strip=True).lower() for x in decl.find_all("span", class_="stldocs-type-plain")]
    if types:
        t = types[-1]
        if t in {"string", "boolean", "number", "integer", "null"}:
            return t
    if decl.find("span", class_="stldocs-type-preview-prefix"):
        return "object"
    return "string"


def normalize_description(text: str) -> str | None:
    if not text:
        return None
    text = " ".join(text.split()).strip()
    return text[:400] if text else None


def merge_nodes(existing: list[dict], incoming: list[dict]) -> list[dict]:
    out = [dict(x) for x in existing]

    def key(node: dict) -> tuple[str, str]:
        return (node.get("name", ""), node.get("type", "string"))

    index = {key(n): i for i, n in enumerate(out)}

    for node in incoming:
        k = key(node)
        if not k[0]:
            continue
        if k not in index:
            out.append(node)
            index[k] = len(out) - 1
            continue

        cur = out[index[k]]

        # Merge enum values.
        if node.get("enum"):
            merged = list(cur.get("enum") or [])
            for v in node["enum"]:
                if v not in merged:
                    merged.append(v)
            cur["enum"] = merged or None

        # Merge object properties recursively.
        if cur.get("properties") or node.get("properties"):
            cur["properties"] = merge_nodes(cur.get("properties", []), node.get("properties", []))

        # Merge array item object properties recursively.
        cur_items = cur.get("items")
        new_items = node.get("items")
        if cur_items or new_items:
            cur_items = dict(cur_items or {})
            new_items = dict(new_items or {})
            item_type = cur_items.get("type") or new_items.get("type") or "string"
            merged_items = {"type": item_type}
            merged_props = merge_nodes(cur_items.get("properties", []), new_items.get("properties", []))
            if merged_props:
                merged_items["type"] = "object"
                merged_items["properties"] = merged_props
            cur["items"] = merged_items

        # Keep richer description if current is empty.
        if not cur.get("description") and node.get("description"):
            cur["description"] = node["description"]

        # Required if any variant marks it required.
        cur["required"] = bool(cur.get("required") or node.get("required"))

    return out


def looks_like_model_wrapper(node: dict) -> bool:
    if node.get("type") != "object":
        return False
    name = node.get("name")
    props = node.get("properties") or []
    if not name or not props:
        return False
    return any((p.get("name") == name) for p in props)


# ── Persistence ────────────────────────────────────────────────────────────────

def write_outputs(endpoints: list[dict], manifest: dict) -> None:
    order = {"GET": 0, "POST": 1, "PUT": 2, "PATCH": 3, "DELETE": 4}
    endpoints.sort(key=lambda e: (
        e.get("tag", ""), e.get("subTag", ""),
        order.get(e.get("method", ""), 9), e.get("path", ""),
    ))
    ENDPOINTS_FILE.write_text(json.dumps(endpoints, indent=2))
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))


def load_existing() -> tuple[dict, dict]:
    """Return (endpoints_by_url, manifest) from previous run, if present."""
    eps_by_url, manifest = {}, {}
    try:
        manifest = json.loads(MANIFEST_FILE.read_text())
    except Exception:
        manifest = {}
    try:
        for ep in json.loads(ENDPOINTS_FILE.read_text()):
            if ep.get("docsUrl"):
                eps_by_url[ep["docsUrl"]] = ep
    except Exception:
        eps_by_url = {}
    return eps_by_url, manifest


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not BeautifulSoup:
        print(
            "Error: Missing dependency 'beautifulsoup4'. "
            "Install it with: python3 -m pip install beautifulsoup4",
            file=sys.stderr,
        )
        sys.exit(1)

    force = "--force" in sys.argv
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    urls = get_endpoint_urls()
    total = len(urls)

    prev_eps, prev_manifest = ({}, {}) if force else load_existing()
    incremental = bool(prev_eps) and not force
    if incremental:
        print(f"  Incremental mode — {len(prev_eps)} cached endpoints; checking for changes…", flush=True)
    else:
        print("  Full scrape" + (" (forced)" if force else "") + "…", flush=True)

    endpoints_by_url: dict[str, dict] = {}
    new_manifest: dict[str, str] = {}
    done = changed = failed = unchanged = 0
    lock = threading.Lock()

    def process(url):
        nonlocal done, changed, failed, unchanged
        # Incremental: HEAD first, reuse cached parse if Last-Modified unchanged.
        if incremental and url in prev_eps and url in prev_manifest:
            lm = head_last_modified(url)
            if lm and lm == prev_manifest.get(url):
                with lock:
                    done += 1; unchanged += 1
                    endpoints_by_url[url] = prev_eps[url]
                    new_manifest[url] = lm
                    emit_progress(done, total, changed, unchanged, failed)
                return

        html, lm = fetch(url)
        try:
            ep = parse_page(html, url) if html else None
        except Exception:
            ep = None
        with lock:
            done += 1
            if ep:
                changed += 1
                endpoints_by_url[url] = ep
                if lm:
                    new_manifest[url] = lm
            else:
                failed += 1
            emit_progress(done, total, changed, unchanged, failed)

    def emit_progress(done, total, changed, unchanged, failed):
        if done % 25 == 0 or done == total:
            print(json.dumps({"status": "running", "done": done, "total": total,
                              "changed": changed, "unchanged": unchanged, "failed": failed}), flush=True)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        for f in as_completed([ex.submit(process, u) for u in urls]):
            try:
                f.result()
            except Exception:
                pass

    endpoints = list(endpoints_by_url.values())
    write_outputs(endpoints, new_manifest)
    print(json.dumps({"status": "done", "count": len(endpoints),
                      "changed": changed, "unchanged": unchanged, "failed": failed}), flush=True)
    print(f"  Done — {len(endpoints)} endpoints "
          f"({changed} fetched, {unchanged} unchanged, {failed} failed)", flush=True)


if __name__ == "__main__":
    main()

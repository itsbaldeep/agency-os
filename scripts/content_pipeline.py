"""Content pipeline support: render typed content_blocks to HTML and manage
image_slot assets (deterministic SVG generation stored in MinIO)."""
import os, json, io, re, hashlib, html as _html

# ── MinIO (hearth-storage) ──────────────────────────────────────────────
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "100.64.0.1:9002")
S3_ACCESS = os.environ.get("S3_ACCESS", "hearth")
S3_SECRET = os.environ.get("S3_SECRET", "hearth_storage")
S3_BUCKET = os.environ.get("S3_BUCKET", "agency-content")
S3_PUBLIC = os.environ.get("S3_PUBLIC_BASE", "http://100.64.0.1:9002")


def storage_client():
    try:
        from minio import Minio
        from urllib.parse import urlparse
        ep = S3_ENDPOINT
        secure = False
        if ep.startswith("http://"):
            ep = ep[len("http://"):]
            secure = False
        elif ep.startswith("https://"):
            ep = ep[len("https://"):]
            secure = True
        return Minio(ep, access_key=S3_ACCESS, secret_key=S3_SECRET, secure=secure)
    except Exception:
        return None


def ensure_bucket():
    c = storage_client()
    if not c:
        return False
    try:
        if not c.bucket_exists(S3_BUCKET):
            c.make_bucket(S3_BUCKET)
        return True
    except Exception:
        return False


def store_bytes(key, data, content_type="image/svg+xml"):
    c = storage_client()
    if not c or not ensure_bucket():
        return None
    try:
        c.put_object(S3_BUCKET, key, io.BytesIO(data), len(data), content_type=content_type)
        return f"{S3_PUBLIC}/{S3_BUCKET}/{key}"
    except Exception as e:
        return None


def slot_key(ci_id, idx):
    return f"content/{ci_id}/image-{idx}.svg"


# ── Deterministic SVG generation from an image_slot ─────────────────────
# No image model is available on Zen, so we render a styled, information-rich
# placeholder SVG derived from the slot's alt+prompt. This keeps the asset
# pipeline real (stored + served via MinIO) without a fake image.
def svg_from_slot(alt, prompt, idx):
    seed = hashlib.md5(f"{alt}|{prompt}|{idx}".encode()).hexdigest()
    palettes = [
        ("#1f2937", "#3b82f6", "#60a5fa"),
        ("#111827", "#10b981", "#34d399"),
        ("#1e1b4b", "#8b5cf6", "#a78bfa"),
        ("#1c1917", "#f59e0b", "#fbbf24"),
    ]
    bg, accent, soft = palettes[int(seed, 16) % len(palettes)]
    title = (alt or "Visual").strip()
    sub = (prompt or "")[:120].strip() or "Concept placeholder"
    w, h = 800, 450
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="{bg}"/><stop offset="1" stop-color="{accent}"/></linearGradient></defs>
<rect width="{w}" height="{h}" fill="url(#g)"/>
<circle cx="{w*0.18}" cy="{h*0.2}" r="{h*0.35}" fill="{soft}" opacity="0.25"/>
<circle cx="{w*0.85}" cy="{h*0.8}" r="{h*0.4}" fill="{soft}" opacity="0.2"/>
<rect x="0" y="{h-8}" width="{w}" height="8" fill="{accent}"/>
<text x="{w*0.06}" y="{h*0.42}" font-family="Segoe UI,Arial,sans-serif" font-size="38" font-weight="700" fill="#fff">{_html.escape(title[:46])}</text>
<text x="{w*0.06}" y="{h*0.56}" font-family="Segoe UI,Arial,sans-serif" font-size="20" fill="#e5e7eb">{_html.escape(sub[:120])}</text>
<text x="{w*0.06}" y="{h*0.9}" font-family="Segoe UI,Arial,sans-serif" font-size="15" fill="{soft}" opacity="0.9">Generated visual placeholder · asset-id {idx}</text>
</svg>'''
    return svg.encode()


def ensure_slot_images(ci_id, blocks):
    """For each image_slot without a stored image URL, generate an SVG, upload
    to MinIO, and write the URL back onto the block. Returns updated blocks."""
    if not ensure_bucket():
        return blocks
    changed = False
    for idx, b in enumerate(blocks):
        if not isinstance(b, dict) or b.get("type") != "image_slot":
            continue
        if b.get("url"):
            continue
        url = store_bytes(slot_key(ci_id, idx), svg_from_slot(b.get("alt", ""), b.get("prompt", ""), idx))
        if url:
            b["url"] = url
            changed = True
    return blocks


# ── Pexels stock image sourcing for image_slot blocks ───────────────────
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


def _pexels_search(query, per_page=5):
    """Query Pexels for landscape photos. Returns list of {id, url, alt} or []."""
    if not PEXELS_API_KEY:
        return []
    try:
        import urllib.request, urllib.parse
        params = urllib.parse.urlencode({"query": query, "per_page": per_page,
                                         "orientation": "landscape"})
        req = urllib.request.Request(
            f"{PEXELS_SEARCH_URL}?{params}",
            headers={"Authorization": PEXELS_API_KEY, "User-Agent": "AgencyOS/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        results = []
        for photo in (data.get("photos") or []):
            results.append({
                "id": photo.get("id"),
                "url": photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large"),
                "alt": photo.get("alt") or query,
            })
        return results
    except Exception:
        return []


def _pexels_download(url):
    """Download image bytes from a URL. Returns (data, content_type) or (None, None)."""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "AgencyOS/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            ct = resp.headers.get("Content-Type", "image/jpeg")
            return data, ct
    except Exception:
        return None, None


def source_slot_images(ci_id, blocks):
    """For each image_slot without an image_url, query Pexels using the block's
    prompt text, download the top landscape result, upload to MinIO, and store
    the resulting public URL on the block as image_url. Falls back to SVG
    placeholder if Pexels fails. Returns updated blocks."""
    if not ensure_bucket():
        return blocks
    changed = False
    for idx, b in enumerate(blocks):
        if not isinstance(b, dict) or b.get("type") != "image_slot":
            continue
        if b.get("image_url"):
            continue
        query = (b.get("prompt") or b.get("alt") or "").strip()
        if not query:
            continue
        results = _pexels_search(query)
        if not results:
            continue
        img_data, ct = _pexels_download(results[0]["url"])
        if not img_data:
            continue
        ext = "jpg"
        if "png" in (ct or ""):
            ext = "png"
        key = f"content/{ci_id}/image-{idx}.{ext}"
        url = store_bytes(key, img_data, ct or "image/jpeg")
        if url:
            b["image_url"] = url
            b["url"] = url
            b["photo_alt"] = results[0].get("alt", "")
            changed = True
    return blocks


# ── Render typed content_blocks to HTML ─────────────────────────────────
def esc(x):
    return _html.escape(str(x or ""))


def render_content_blocks(blocks, title="Untitled"):
    parts = [f"<article><h1>{esc(title)}</h1>"]
    for i, b in enumerate(blocks):
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t in ("intro", "heading"):
            text = b.get("markdown") or b.get("heading") or ""
            if t == "heading":
                parts.append(f"<h2>{esc(text)}</h2>")
            elif text:
                parts.append(f"<p class='lead'>{_md(text)}</p>")
        elif t == "prose":
            if b.get("markdown"):
                parts.append(f"<div class='prose'>{_md(b['markdown'])}</div>")
        elif t == "key_takeaways":
            pts = b.get("points") or []
            if pts:
                lis = "".join(f"<li>{_md(p)}</li>" for p in pts)
                parts.append(f"<div class='takeaways'><h3>Key takeaways</h3><ul>{lis}</ul></div>")
        elif t == "steps":
            st = b.get("steps") or []
            if st:
                lis = "".join(f"<li>{_md(s)}</li>" for s in st)
                parts.append(f"<ol class='steps'>{lis}</ol>")
        elif t == "table":
            cols = b.get("columns") or []
            rows = b.get("rows") or []
            if rows:
                hdr = "".join(f"<th>{esc(c)}</th>" for c in (cols or rows[0]))
                body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
                parts.append(f"<table><thead><tr>{hdr}</tr></thead><tbody>{body}</tbody></table>")
        elif t == "chart":
            parts.append(_render_chart(b))
        elif t == "callout":
            if b.get("stat"):
                parts.append(f"<div class='callout'><div class='stat'>{esc(b.get('stat'))}</div><div class='label'>{esc(b.get('label',''))}</div></div>")
        elif t == "image_slot":
            alt = b.get("alt", "")
            img_src = b.get("image_url") or b.get("url")
            if img_src:
                parts.append(f"<figure><img src='{esc(img_src)}' alt='{esc(alt)}' loading='lazy'/><figcaption>{esc(alt)}</figcaption></figure>")
            else:
                parts.append(f"<figure><div class='imgph'>{esc(alt)}</div><figcaption>{esc(alt)}</figcaption></figure>")
        elif t == "faq":
            q = b.get("brief", "")
            a = b.get("answer", "")
            if q and a:
                parts.append(f"<details class='faq'><summary>{esc(q)}</summary><div>{_md(a)}</div></details>")
    parts.append("</article>")
    return "".join(parts)


def _md(s):
    try:
        import markdown
        return markdown.markdown(s or "")
    except Exception:
        return f"<p>{esc(s)}</p>"


def _render_chart(b):
    ct = b.get("chart_type") or "bar"
    ds = b.get("data_series") or {}
    labels = ds.get("labels") or []
    values = [float(v) for v in (ds.get("values") or []) if isinstance(v, (int, float))]
    title = b.get("title") or "Chart"
    if not values:
        return f"<div class='chart'><h4>{esc(title)}</h4><p class='empty'>No data</p></div>"
    vmax = max(values) or 1
    bars = "".join(
        f"<div class='barwrap'><span class='bar' style='height:{int(v/vmax*100)}%' title='{esc(labels[i] if i<len(labels) else '')}: {v}'></span><span class='bar-label'>{esc(str(labels[i])[:12] if i<len(labels) else str(v))}</span></div>"
        for i, v in enumerate(values)
    )
    return f"<div class='chart'><h4>{esc(title)}</h4><div class='barchart'>{bars}</div></div>"


def render_pipeline_css():
    return """<style>
.pipeline-article{font-family:Segoe UI,Arial,sans-serif;line-height:1.7;color:#111827;max-width:720px;margin:0 auto}
.pipeline-article h1{font-size:2.2em;line-height:1.15;margin-bottom:8px}
.pipeline-article .lead{font-size:1.15em;color:#374151;border-left:4px solid #3b82f6;padding-left:12px}
.pipeline-article .prose p{margin:12px 0}
.pipeline-article h2{margin-top:28px;font-size:1.4em;border-bottom:2px solid #e5e7eb;padding-bottom:6px}
.pipeline-article .takeaways{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:14px 18px;margin:16px 0}
.pipeline-article .takeaways h3{margin:0 0 8px;color:#1d4ed8}
.pipeline-article ol.steps{counter-reset:s;list-style:none;padding:0}
.pipeline-article ol.steps li{counter-increment:s;padding:6px 0 6px 36px;position:relative}
.pipeline-article ol.steps li:before{content:counter(s);position:absolute;left:0;top:8px;width:24px;height:24px;background:#3b82f6;color:#fff;border-radius:50%;text-align:center;font-size:13px;line-height:24px}
.pipeline-article table{width:100%;border-collapse:collapse;margin:16px 0;font-size:.95em}
.pipeline-article th,.pipeline-article td{border:1px solid #e5e7eb;padding:8px 10px;text-align:left}
.pipeline-article th{background:#f9fafb}
.pipeline-article .callout{background:#111827;color:#fff;border-radius:10px;padding:18px 22px;margin:18px 0;text-align:center}
.pipeline-article .callout .stat{font-size:2.6em;font-weight:800;color:#60a5fa}
.pipeline-article .callout .label{font-size:1em;color:#e5e7eb;margin-top:4px}
.pipeline-article .chart{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px;margin:16px 0}
.pipeline-article .barchart{display:flex;align-items:flex-end;gap:6px;height:200px;padding-top:8px}
.pipeline-article .barwrap{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}
.pipeline-article .bar{width:100%;max-width:46px;background:linear-gradient(#3b82f6,#2563eb);border-radius:4px 4px 0 0}
.pipeline-article .bar-label{font-size:11px;color:#6b7280;margin-top:4px}
.pipeline-article figure{margin:16px 0}
.pipeline-article figure img{max-width:100%;border-radius:8px}
.pipeline-article figcaption{font-size:.85em;color:#6b7280;margin-top:6px}
.pipeline-article .imgph{aspect-ratio:16/9;background:linear-gradient(135deg,#1f2937,#3b82f6);border-radius:8px;display:flex;align-items:center;justify-content:center;color:#e5e7eb;padding:20px;text-align:center}
.pipeline-article details.faq{border:1px solid #e5e7eb;border-radius:6px;margin:8px 0;padding:8px 12px}
.pipeline-article details.faq summary{cursor:pointer;font-weight:600}
</style>"""

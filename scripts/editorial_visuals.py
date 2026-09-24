"""Bounded, reviewed editorial visual blocks.

This module deliberately has no network, storage, or image-generation
dependency.  It is separate from evidence-backed article blocks: only chart
numbers use verified facts, while the other kinds are clearly editorial.
"""
from __future__ import annotations

import html
import hashlib
import math
import re
from urllib.parse import urlparse


MAX_TEXT = 350
KINDS = {"comparison", "annotated_example", "checklist", "flow", "image", "bar_chart", "line_chart"}
_NUMBER = re.compile(r"(?<![\w.])-?(?:\d+(?:\.\d+)?|\.\d+)(?![\w.])")
_PRIVATE_HOSTS = {"localhost", "localhost.localdomain", "local", "example", "example.com", "example.org", "example.net"}


def _text(value, name, limit=MAX_TEXT):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be a non-empty string of at most {limit} characters")
    return value.strip()


def _list(value, name, minimum, maximum):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{name} must contain {minimum}-{maximum} items")
    return value


def _safe_url(value, name):
    value = _text(value, name, 2048)
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.port:
        raise ValueError(f"{name} must be an HTTPS public URL")
    if any(ch.isspace() or ord(ch) < 32 for ch in value) or "\\" in value:
        raise ValueError(f"{name} contains invalid URL characters")
    if host in _PRIVATE_HOSTS or host.endswith((".local", ".localhost", ".internal", ".lan")):
        raise ValueError(f"{name} must use a public hostname")
    if ":" in host or not "." in host or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
        raise ValueError(f"{name} must not use an IP address")
    labels = host.split(".")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
        raise ValueError(f"{name} must use a valid public hostname")
    return value


def _facts_map(facts):
    if isinstance(facts, dict):
        values = facts.values()
    elif isinstance(facts, list):
        values = facts
    else:
        values = []
    return {str(f.get("id")): f for f in values if isinstance(f, dict) and f.get("id")}


def _grounded_point(point, index, fact_map):
    if not isinstance(point, dict):
        raise ValueError(f"points[{index}] must be an object")
    label = _text(point.get("label"), f"points[{index}].label", MAX_TEXT)
    value = point.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 1e15 or not math.isfinite(value):
        raise ValueError(f"points[{index}].value must be finite numeric")
    fact_id = str(point.get("fact_id", ""))
    fact = fact_map.get(fact_id)
    if not fact:
        raise ValueError(f"points[{index}] requires an existing verified fact_id")
    evidence = str(fact.get("evidence_snippet", ""))
    token = str(value)
    if isinstance(value, float) and value.is_integer():
        token = str(int(value))
    if token not in _NUMBER.findall(evidence):
        raise ValueError(f"points[{index}].value is not literally grounded in its fact")
    source = fact.get("source_url") or fact.get("url")
    if not isinstance(source, str) or not source:
        raise ValueError(f"fact {fact_id} has no source URL")
    return {"label": label, "value": value, "fact_id": fact_id, "source_url": _safe_url(source, "source_url")}


def validate_visual(payload, facts):
    """Validate and normalize a reviewed visual payload, or raise ValueError."""
    if not isinstance(payload, dict):
        raise ValueError("visual payload must be an object")
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("unsupported visual kind")
    out = {"type": "editorial_visual", "kind": kind,
           "title": _text(payload.get("title"), "title"),
           "caption": _text(payload.get("caption"), "caption")}
    if kind == "comparison":
        cols = _list(payload.get("columns"), "columns", 2, 4)
        rows = _list(payload.get("rows"), "rows", 1, 8)
        out["columns"] = [_text(v, "column") for v in cols]
        out["rows"] = [[_text(v, "cell") for v in _list(row, "row", 2, 4)] for row in rows]
        if any(len(row) != len(out["columns"]) for row in out["rows"]):
            raise ValueError("comparison rows must match columns")
        if any(_NUMBER.search(text) for text in [out["title"], out["caption"], *out["columns"], *(cell for row in out["rows"] for cell in row)]):
            raise ValueError("comparison editorial guidance cannot contain numeric/statistical claims")
        out["editorial_label"] = "Editorial guidance, not statistical evidence"
    elif kind == "annotated_example":
        out["before"] = _text(payload.get("before"), "before")
        out["after"] = _text(payload.get("after"), "after")
        out["notes"] = [_text(v, "note") for v in _list(payload.get("notes"), "notes", 1, 6)]
        out["label"] = "Hypothetical example"
    elif kind == "checklist":
        out["items"] = [_text(v, "item") for v in _list(payload.get("items"), "items", 1, 10)]
    elif kind == "flow":
        out["items"] = [_text(v, "item") for v in _list(payload.get("items"), "items", 2, 8)]
    elif kind == "image":
        out["url"] = _safe_url(payload.get("url"), "url")
        out["alt"] = _text(payload.get("alt"), "alt")
        out["credit"] = _text(payload.get("credit"), "credit")
        if payload.get("credit_url") is not None:
            out["credit_url"] = _safe_url(payload["credit_url"], "credit_url")
    else:
        out["units"] = _text(payload.get("units"), "units", 80)
        points = _list(payload.get("points"), "points", 2, 12)
        fmap = _facts_map(facts)
        out["points"] = [_grounded_point(p, i, fmap) for i, p in enumerate(points)]
        out["sources"] = list(dict.fromkeys(p["source_url"] for p in out["points"]))
        out['evidence'] = [{key: fmap[point['fact_id']].get(key) for key in ('id', 'claim', 'evidence_snippet', 'source_url')}
                           for point in out['points']]
        if "width" in payload or "height" in payload:
            width, height = payload.get("width", 720), payload.get("height", 360)
            if not isinstance(width, int) or not isinstance(height, int) or not 240 <= width <= 1600 or not 160 <= height <= 1000:
                raise ValueError("chart dimensions are malformed")
            out.update(width=width, height=height)
    return out


def _e(value):
    return html.escape(str(value), quote=True)


def render_visual(visual):
    """Render a validated visual as responsive, escaped, self-contained HTML."""
    if not isinstance(visual, dict):
        raise ValueError('Visual must be an object')
    v = validate_visual(visual, visual.get('evidence') or [])
    if v.get("kind") == "image":
        _safe_url(v.get("url"), "url")
        if v.get("credit_url") is not None:
            _safe_url(v.get("credit_url"), "credit_url")
    kind, title, caption = v["kind"], _e(v["title"]), _e(v["caption"])
    if kind == "image":
        credit = f' <a href="{_e(v["credit_url"])}">{_e(v["credit"])} </a>' if v.get("credit_url") else f" {_e(v['credit'])}"
        body = f'<img style="max-width:100%;height:auto" src="{_e(v["url"])}" alt="{_e(v["alt"])}" loading="lazy" decoding="async" referrerpolicy="no-referrer"><small>Credit:{credit}</small>'
    elif kind == "comparison":
        head = "".join(f"<th>{_e(x)}</th>" for x in v["columns"])
        body = f'<p class="label">{_e(v["editorial_label"])}</p><div style="max-width:100%;overflow-x:auto"><table><thead><tr>{head}</tr></thead><tbody>' + "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>" for row in v["rows"]) + "</tbody></table></div>"
    elif kind == "annotated_example":
        body = f'<p class="label">{_e(v["label"])}</p><div class="cards"><div class="card"><b>Before</b><p>{_e(v["before"])}</p></div><div class="card"><b>After</b><p>{_e(v["after"])}</p></div></div><ul>' + "".join(f"<li>{_e(x)}</li>" for x in v["notes"]) + "</ul>"
    elif kind in ("checklist", "flow"):
        tag = "ol" if kind == "flow" else "ul"
        body = f'<{tag} class="cards">' + "".join(f'<li class="card">{_e(x)}</li>' for x in v["items"]) + f"</{tag}>"
    else:
        width, height = v.get("width", 720), v.get("height", 360)
        vals = [p["value"] for p in v["points"]]
        lo, hi = min(0, min(vals)), max(0, max(vals))
        span = hi - lo or 1
        if not math.isfinite(span):
            raise ValueError('Chart range is too large to render safely')
        bars = []
        line_points = []
        for i, p in enumerate(v["points"]):
            x = 20 + i * (680 / len(vals)); y0 = 300 - ((0 - lo) / span) * 240
            y = 300 - ((p["value"] - lo) / span) * 240
            line_points.append(f"{x + max(12, 560/len(vals))/2:.1f},{y:.1f}")
            bars.append(f'<rect x="{x:.1f}" y="{min(y,y0):.1f}" width="{max(12, 560/len(vals)):.1f}" height="{abs(y-y0):.1f}"/>')
        rows = "".join(f'<tr><th scope="row">{_e(p["label"])}</th><td>{_e(p["value"])}</td><td>{_e(p["fact_id"])}</td><td>{_e(p["source_url"])}</td></tr>' for p in v["points"])
        series = (f'<polyline points="{" ".join(line_points)}" fill="none" stroke="currentColor"/>' if kind == "line_chart" else "".join(bars))
        ident = "v-" + hashlib.sha256((v["title"] + v["caption"] + kind + repr(v['points']) + str(visual.get('visual_id', ''))).encode()).hexdigest()[:12]
        body = f'<div style="max-width:100%;overflow-x:auto"><svg style="width:100%;height:auto;min-width:420px" viewBox="0 0 720 360" role="img" aria-labelledby="{ident}-title {ident}-desc"><title id="{ident}-title">{title}</title><desc id="{ident}-desc">{_e(v["caption"])}, range {_e(lo)} to {_e(hi)} {_e(v["units"])}</desc><text x="22" y="18">{_e(hi)} {_e(v["units"])}</text><text x="22" y="355">{_e(lo)} {_e(v["units"])}</text><line x1="20" y1="{y0:.1f}" x2="700" y2="{y0:.1f}" stroke="currentColor"/><g class="series">{series}</g></svg></div><div style="max-width:100%;overflow-x:auto"><table class="data"><caption>{_e(v["units"])}; sources and verified fact IDs retained in the data rows</caption><thead><tr><th>Label</th><th>Value</th><th>Fact ID</th><th>Source</th></tr></thead><tbody>{rows}</tbody></table></div>'
    body = body.replace('class="cards"', 'class="cards" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr));gap:14px;padding:0;list-style-position:inside"')
    body = body.replace('class="card"', 'class="card" style="padding:18px;border:1px solid #b9cdbf;background:#f7fbf6;border-radius:8px;min-width:0;color:#17332b"')
    body = body.replace('<th>', '<th scope="col" style="padding:12px;border:1px solid #b9cdbf;text-align:left;color:#17332b;background:#dcebdd;font-size:14px;font-weight:700;text-transform:none;letter-spacing:normal;min-width:120px">').replace('<td>', '<td style="padding:12px;border:1px solid #b9cdbf;min-width:120px;word-break:normal">')
    body = body.replace('<table', '<table style="width:100%;border-collapse:collapse;font-size:16px"')
    body = body.replace('class="series"', 'class="series" style="fill:#087f68;color:#087f68;stroke-width:3"')
    return f'<figure class="editorial-visual {kind}" style="max-width:100%;box-sizing:border-box;margin:28px 0;padding:22px;background:#edf4ed;color:#17332b;border:1px solid #b9cdbf;border-radius:10px"><h3 style="margin:0 0 14px;font-size:23px;line-height:1.3">{title}</h3><div class="visual-body" style="max-width:100%;overflow-wrap:anywhere">{body}</div><figcaption style="margin-top:16px;font-size:14px;color:#385b4d">{caption}</figcaption></figure>'


def visual_markdown(visual):
    """Return a portable plain Markdown representation of a validated visual."""
    v = validate_visual(visual, visual.get('evidence') or [])
    safe = lambda value: str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = [f"### {safe(v['title'])}", safe(v["caption"])]
    k = v["kind"]
    if k == "comparison":
        lines += ["", f"*{safe(v['editorial_label'])}*"]
        lines.append("| " + " | ".join(safe(x) for x in v["columns"]) + " |")
        lines.append("| " + " | ".join("---" for _ in v["columns"]) + " |")
        lines += ["| " + " | ".join(safe(x) for x in row) + " |" for row in v["rows"]]
    elif k == "image":
        lines += ["", f"![{safe(v['alt'])}]({v['url']})", f"Credit: {safe(v['credit'])}"]
    elif k == "annotated_example":
        lines += ["", "*Hypothetical example*", f"**Before:** {safe(v['before'])}", f"**After:** {safe(v['after'])}"] + [f"- {safe(n)}" for n in v["notes"]]
    elif k in ("bar_chart", "line_chart"):
        lines += ["", f"*Units: {safe(v['units'])}*"]
        lines += [f"- {safe(p['label'])}: {safe(p['value'])} ({p['source_url']}, fact {safe(p['fact_id'])})" for p in v["points"]]
    else:
        lines += [""] + [f"{i}. {safe(x)}" for i, x in enumerate(v.get("items", []), 1)]
    return "\n".join(lines)

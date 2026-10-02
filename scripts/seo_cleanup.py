"""Deterministic SEO repair planning and receipt verification.

This module only creates reviewable plans.  It deliberately has no HTTP, Ghost,
filesystem, git, or Discord side effects.  A dashboard or an explicitly
approved executor can consume the plan after checking its preconditions.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit


SCHEMA_VERSION = 1
GHOST_RULES = frozenset({
    "missing_title", "missing_description", "duplicate_title",
    "duplicate_description", "missing_jsonld", "invalid_jsonld",
})
REDIRECT_RULES = frozenset({"canonical_mismatch", "sitemap_redirect"})


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value):
    """Return a stable hash suitable for an optimistic concurrency precondition."""
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def normalize_url(url):
    p = urlsplit(str(url or "").strip())
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    host = p.hostname.lower()
    port = p.port
    default = 443 if p.scheme == "https" else 80
    netloc = host if port in (None, default) else "%s:%s" % (host, port)
    path = p.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return urlunsplit((p.scheme, netloc, path, p.query, ""))


def _source_kind(finding):
    rule = finding.get("rule")
    if rule in GHOST_RULES and finding.get("ghost_post_id"):
        return "ghost_metadata"
    if rule in REDIRECT_RULES:
        return "repo_redirect"
    return "review"


def _destination(finding):
    expected = finding.get("expected")
    observed = finding.get("observed")
    if finding.get("rule") == "canonical_mismatch":
        return normalize_url(expected) or normalize_url(finding.get("url"))
    if finding.get("rule") == "sitemap_redirect":
        return normalize_url(observed)
    return None


def build_cleanup_plan(findings, *, audit_id=None, revision=None, owned_origin=None):
    """Group findings into bounded proposals with hashes and destinations.

    ``revision`` is an opaque source revision supplied by the caller, usually
    an audit run id or repository commit.  No topic or repair text is inferred
    from an unrecognised finding.
    """
    grouped = defaultdict(list)
    for raw in findings or []:
        if not isinstance(raw, dict):
            continue
        rule = str(raw.get("rule") or "")
        url = normalize_url(raw.get("url"))
        if not rule or not url:
            continue
        if owned_origin and normalize_url(owned_origin):
            origin = normalize_url(owned_origin)
            if urlsplit(url).netloc != urlsplit(origin).netloc:
                continue
        kind = _source_kind(raw)
        observed = raw.get("observed")
        expected = raw.get("expected")
        precondition = {
            "audit_id": audit_id,
            "revision": revision,
            "source_hash": digest({"url": url, "rule": rule, "observed": observed}),
            "observed": observed,
        }
        if raw.get("content_revision") is not None:
            precondition["content_revision"] = raw.get("content_revision")
        if raw.get("content_hash"):
            precondition["content_hash"] = raw.get("content_hash")
        item = {
            "evidence_id": raw.get("evidence_id") or digest([rule, url])[:24],
            "rule": rule,
            "url": url,
            "source_kind": kind,
            "action": "review" if kind == "review" else "update_metadata" if kind == "ghost_metadata" else "propose_redirect",
            "destination": _destination(raw),
            "expected": expected,
            "precondition": precondition,
            "precondition_hash": digest(precondition),
            "status": "proposed",
        }
        proposal = description_proposal(raw)
        if proposal is not None and rule == "missing_description":
            item["proposal"] = {"meta_description": proposal}
        if raw.get("ghost_post_id"):
            item["ghost_post_id"] = str(raw["ghost_post_id"])
        grouped[(kind, rule)].append(item)
    groups = []
    for (kind, rule), items in sorted(grouped.items()):
        groups.append({
            "group_key": "%s:%s" % (kind, rule),
            "source_kind": kind,
            "rule": rule,
            "count": len(items),
            "items": items,
        })
    plan = {
        "schema_version": SCHEMA_VERSION,
        "audit_id": audit_id,
        "revision": revision,
        "groups": groups,
    }
    plan["plan_hash"] = digest(plan)
    return plan


def verify_receipt(item, receipt, *, revision=None):
    """Verify an executor receipt without trusting executor supplied status."""
    if not isinstance(item, dict) or not isinstance(receipt, dict):
        return {"ok": False, "reason": "malformed_receipt"}
    if receipt.get("precondition_hash") != item.get("precondition_hash"):
        return {"ok": False, "reason": "precondition_hash_mismatch"}
    if revision is not None and item.get("precondition", {}).get("revision") != revision:
        return {"ok": False, "reason": "revision_mismatch"}
    if receipt.get("destination") != item.get("destination"):
        return {"ok": False, "reason": "destination_mismatch"}
    if receipt.get("status") not in ("applied", "verified"):
        return {"ok": False, "reason": "receipt_not_verified"}
    return {"ok": True, "status": "verified", "evidence_id": item.get("evidence_id")}


def notification_key(plan_hash):
    return "seo-cleanup:%s" % str(plan_hash or "")


def discord_summary(batch_id, status, results, dashboard_url=""):
    """Build one short secret-free executive notification for a batch."""
    rows = results if isinstance(results, list) else []
    counts = {}
    for row in rows:
        key = str((row or {}).get("status") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    detail = ", ".join("%s %s" % (n, key) for key, n in sorted(counts.items())) or "no receipts"
    link = ("\n" + dashboard_url[:500]) if dashboard_url else ""
    labels = {"missing_description": "meta descriptions", "canonical_mismatch": "canonical routes", "sitemap_redirect": "sitemap redirects", "missing_title": "page titles", "missing_jsonld": "structured data"}
    changes = sorted({labels[row.get("rule")] for row in rows if row.get("rule") in labels})
    scope = (" Checked: " + ", ".join(changes) + ".") if changes else ""
    return "SEO cleanup batch #%s: %s (%s).%s Review verified changes and remaining work in the dashboard.%s" % (batch_id, status, detail, scope, link)


def description_proposal(finding):
    """Use only supplied editorial text, never invent a page description."""
    if not isinstance(finding, dict):
        return None
    value = str(finding.get("excerpt") or "").strip()
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:157] + "..." if len(value) > 160 else value


def read_named_credential(path, name):
    """Read one named engagement credential without exposing its value."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name or "")):
        raise ValueError("credential name is invalid")
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(str(name) + "="):
                value = line.split("=", 1)[1].strip().strip("\"").strip("'")
                if value:
                    return value
    raise ValueError("named credential was not found")


def apply_ghost_metadata(item, destination, *, client=None, allow_empty=False):
    """Apply one approved description and verify exact readback.

    The caller must provide an approved plan item and an explicit Ghost
    destination. Only ``meta_description`` is sent in the PUT payload.
    """
    if not isinstance(item, dict) or item.get("source_kind") != "ghost_metadata":
        raise ValueError("item is not a Ghost metadata proposal")
    proposed = item.get("proposal") or {}
    description = proposed.get("meta_description")
    if not isinstance(description, str) or not ((allow_empty and len(description) == 0) or (1 <= len(description) <= 160)):
        raise ValueError("reviewed meta description is required")
    post_id = item.get("ghost_post_id") or item.get("post_id")
    if not post_id:
        raise ValueError("Ghost post id is required")
    if client is None:
        from ghost_publisher import GhostAdminClient, _endpoint
        credential_path = destination.get("credential_path")
        if not credential_path and destination.get("project_path") and destination.get("env_file"):
            credential_path = str((Path(destination["project_path"]).resolve() / str(destination["env_file"])).resolve())
        credential_name = destination.get("credential_ref")
        if not credential_name:
            raise ValueError("Ghost credential_ref is required")
        if not credential_path:
            raise ValueError("engagement credential path is required")
        root = destination.get("credential_root") or "/home/agency/engagements/trueapply"
        try:
            Path(str(credential_path)).resolve().relative_to(Path(str(root)).resolve())
        except ValueError as exc:
            raise ValueError("credential path is outside the engagement scope") from exc
        key = read_named_credential(credential_path, credential_name)
        client = GhostAdminClient(_endpoint(destination), key, admin_host=destination.get("admin_host"))
    import urllib.parse
    path = "/ghost/api/admin/posts/%s/?formats=html" % urllib.parse.quote(str(post_id), safe="")
    before = (client.request("GET", path).get("posts") or [None])[0]
    if not isinstance(before, dict):
        raise ValueError("Ghost post readback was empty")
    expected = item.get("precondition") or {}
    expected_revision = expected.get("content_revision")
    if expected_revision is not None and before.get("updated_at") != expected_revision:
        raise ValueError("Ghost content revision changed")
    current_hash = digest({"meta_description": before.get("meta_description") or "", "updated_at": before.get("updated_at")})
    if expected.get("content_hash") and expected["content_hash"] != current_hash:
        raise ValueError("Ghost content precondition changed")
    client.request("PUT", "/ghost/api/admin/posts/%s/" % urllib.parse.quote(str(post_id), safe=""),
                   {"posts": [{"meta_description": description, "updated_at": before.get("updated_at")}]})
    after = (client.request("GET", path).get("posts") or [None])[0]
    if not isinstance(after, dict) or after.get("meta_description") != description:
        raise ValueError("Ghost metadata readback did not match")
    return {"status": "verified", "post_id": str(post_id), "destination": item.get("destination"),
            "precondition_hash": item.get("precondition_hash"),
            "before": {"meta_description": before.get("meta_description") or "", "updated_at": before.get("updated_at")},
            "after": {"meta_description": after.get("meta_description") or "", "updated_at": after.get("updated_at")}}


def rollback_ghost_metadata(item, receipt, destination, *, client=None):
    """Restore the exact prior description after an approved rollback task."""
    before = (receipt or {}).get("before") or {}
    if not isinstance(before.get("meta_description"), str):
        raise ValueError("receipt does not contain a prior description")
    rollback = dict(item, proposal={"meta_description": before["meta_description"]})
    return apply_ghost_metadata(rollback, destination, client=client, allow_empty=True)


def enrich_ghost_findings(findings, destination, *, client=None):
    """Attach owned Ghost post state to findings using a read-only list call."""
    if not isinstance(destination, dict) or not (destination.get("credential_path") or (destination.get("project_path") and destination.get("env_file"))):
        return list(findings or [])
    if client is None:
        from ghost_publisher import GhostAdminClient, _endpoint
        credential_ref = destination.get("credential_ref")
        if not credential_ref:
            raise ValueError("Ghost credential_ref is required")
        credential_path = destination.get("credential_path") or str((Path(destination["project_path"]).resolve() / str(destination["env_file"])).resolve())
        try:
            Path(credential_path).resolve().relative_to(Path("/home/agency/engagements/trueapply").resolve())
        except ValueError as exc:
            raise ValueError("credential path is outside the engagement scope") from exc
        key = read_named_credential(credential_path, credential_ref)
        client = GhostAdminClient(_endpoint(destination), key, admin_host=destination.get("admin_host"))
    response = client.request("GET", "/ghost/api/admin/posts/?limit=100&fields=id,url,canonical_url,updated_at,meta_description,custom_excerpt,excerpt")
    posts = response.get("posts") if isinstance(response, dict) else []
    by_url = {}
    for post in posts or []:
        if not isinstance(post, dict):
            continue
        for key in ("url", "canonical_url"):
            if post.get(key): by_url[str(post[key]).rstrip("/")] = post
    enriched = []
    for raw in findings or []:
        finding = dict(raw) if isinstance(raw, dict) else raw
        post = by_url.get(str(finding.get("url") or "").rstrip("/")) if isinstance(finding, dict) else None
        if post and isinstance(finding, dict):
            finding["ghost_post_id"] = post.get("id")
            finding["content_revision"] = post.get("updated_at")
            finding["excerpt"] = post.get("custom_excerpt") or post.get("excerpt") or ""
            finding["content_hash"] = digest({"meta_description": post.get("meta_description") or "", "updated_at": post.get("updated_at")})
        enriched.append(finding)
    return enriched


def verify_public_metadata(url, expected, *, fetcher=None):
    """Verify the published page exposes the exact metadata value."""
    if fetcher:
        result = fetcher(url)
    else:
        import public_fetch
        result = public_fetch.fetch(url, max_bytes=1_000_000, timeout=15)
    if not isinstance(result, dict) or not result.get("ok"):
        return {"status": "unavailable"}
    from seo_measurement import extract_html
    fields = extract_html(result.get("body", b""), url)
    return {"status": "verified" if fields.get("meta_description") == expected else "mismatch",
            "meta_description": fields.get("meta_description") or ""}

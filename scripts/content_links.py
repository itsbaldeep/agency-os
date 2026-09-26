"""Bounded internal and external link auditing for owned content surfaces.

This module is deliberately independent of the stored SEO crawl schema.  It
provides a page inventory that content workflows can consume while keeping
the existing ``seo_measurement.crawl`` contract unchanged.  Network access
uses ``public_fetch`` by default, including its DNS, redirect, byte, and
timeout safeguards.  Tests and callers may inject deterministic fetchers.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from collections import deque
from typing import Any, Callable

import public_fetch
import seo_measurement as seo


MAX_PAGES = 50
MAX_SITEMAPS = 5
MAX_SITEMAP_MEMBERS = 200
MAX_QUEUE = 200
MAX_EXTERNAL_CANDIDATES = 500
MAX_DOCUMENT_LINKS = 50
MAX_EXTERNAL_CHECKS = 25
TIMEOUT = 15
MIN_DELAY = 0.2
USER_AGENT = seo.USER_AGENT


def _origin(value: str) -> str | None:
    return seo.normalize_url(value)


def _category(url: str) -> str:
    path = urllib.parse.urlsplit(url).path.lower().strip("/")
    if not path:
        return "landing"
    first = path.split("/", 1)[0]
    if first in {"blog", "blogs", "articles", "news", "insights"}:
        return "blog"
    if first in {"help", "support", "docs", "documentation", "guides", "faq"}:
        return "help"
    return "other"


def _tuple_response(value: Any, requested: str) -> dict[str, Any]:
    """Normalize the existing test/crawler tuple shape without exposing errors."""
    if isinstance(value, dict):
        if not value.get("ok"):
            return {"ok": False, "status": value.get("status"), "error": str(value.get("error") or "fetch_failed")}
        return {
            "ok": True,
            "status": int(value.get("status", 200)),
            "body": value.get("body", b""),
            "content_type": value.get("content_type", ""),
            "final_url": seo.normalize_url(value.get("final_url"), requested) or requested,
        }
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return {"ok": False, "error": "malformed_fetch_result"}
    try:
        status = int(value[0])
    except (TypeError, ValueError):
        return {"ok": False, "error": "malformed_status"}
    final = requested
    if len(value) > 2 and value[2]:
        final = seo.normalize_url(value[2], requested) or requested
    return {
        "ok": True,
        "status": status,
        "body": value[1],
        "content_type": value[3] if len(value) > 3 else "",
        "final_url": final,
    }


def _fetch(url: str, fetcher: Callable[[str], Any] | None) -> dict[str, Any]:
    if fetcher is not None:
        try:
            return _tuple_response(fetcher(url), url)
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}
    try:
        return _tuple_response(public_fetch.fetch(url, timeout=TIMEOUT, return_final_url=True), url)
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def _external_state(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        error = str(result.get("error") or "").lower()
        if re.search(r"(?:http_status_)?(?:404|410)(?:$|[^0-9])", error):
            return "broken"
        if re.search(r"(?:http_status_)?(?:403|429)(?:$|[^0-9])", error):
            return "blocked"
        return "unknown"
    status = int(result.get("status", 0))
    if status in (404, 410):
        return "broken"
    if status in (403, 429):
        return "blocked"
    if 200 <= status < 400:
        return "ok"
    return "unknown"


def _http_error_status(result: dict[str, Any]) -> int | None:
    status = result.get("status")
    if isinstance(status, int):
        return status
    match = re.search(r"(?:http_status_)?(\d{3})(?:$|[^0-9])", str(result.get("error") or ""))
    return int(match.group(1)) if match else None


def _link_record(url: str, source_url: str, state: str, result: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    record = {
        "url": url,
        "source_url": source_url,
        "state": state,
        "status": result.get("status"),
    }
    if reason:
        record["reason"] = reason
    elif not result.get("ok"):
        record["error"] = result.get("error", "unknown")
    return record


_MARKDOWN_HREF = re.compile(r"\[[^\]]*\]\(\s*(<[^>]+>|[^\s)]+)", re.I)


def _document_links(blocks: Any, base_url: str) -> list[dict[str, str]]:
    """Extract checkable document links while excluding image asset URLs."""
    found: list[dict[str, str]] = []

    def add(value: Any, kind: str, source: str) -> None:
        if not isinstance(value, str):
            return
        value = value.strip().strip("<>")
        url = seo.normalize_url(value, base_url)
        if url and url not in {item["url"] for item in found} and len(found) < MAX_DOCUMENT_LINKS:
            found.append({"url": url, "kind": kind, "source": source})

    def walk(value: Any, path: str = "", parent_kind: str = "") -> None:
        if isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]", parent_kind)
            return
        if not isinstance(value, dict):
            return
        block_type = value.get("type") or parent_kind
        # Image availability and licensing are handled by the asset workflow.
        if block_type == "image_slot":
            for key in ("alt", "caption"):
                for match in _MARKDOWN_HREF.findall(str(value.get(key) or "")):
                    add(match, "markdown", f"{path}.{key}")
            return
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key in {"image_url", "image", "asset", "url"} and block_type == "image_slot":
                continue
            if key in {"source_url", "credit_url"}:
                add(child, "editorial_source", child_path)
            elif key == "sources" and isinstance(child, list):
                for index, source in enumerate(child):
                    add(source, "source", f"{child_path}[{index}]")
            elif isinstance(child, str) and key in {"markdown", "body", "answer", "brief", "text", "heading"}:
                for match in _MARKDOWN_HREF.findall(child):
                    add(match, "markdown", child_path)
            elif isinstance(child, (dict, list)):
                walk(child, child_path, block_type)

    walk(blocks)
    return found


def check_document_links(blocks: Any, base_url: str, fetcher: Callable[[str], Any] | None = None) -> dict[str, Any]:
    """Check links embedded in content blocks before publication.

    Returns source metadata, per-link states, explicit broken-link blockers,
    and a separate unverified list for blocked or failed checks. Image asset
    URLs are intentionally excluded because the asset workflow owns those
    checks. At most ``MAX_DOCUMENT_LINKS`` unique links are checked.
    """
    base = _origin(base_url)
    if not base:
        raise ValueError("base_url must be an absolute http or https URL")
    candidates = _document_links(blocks, base)
    checked: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    captured = seo.now()
    for candidate in candidates:
        result = _fetch(candidate["url"], fetcher)
        state = _external_state(result)
        record = {**candidate, "state": state, "status": result.get("status"), "checked_at": captured}
        if not result.get("ok") and result.get("error"):
            record["error"] = result["error"]
        checked.append(record)
        if state == "broken":
            blockers.append(record)
        elif state != "ok":
            unverified.append(record)
    findings = [
        {"rule": "content_link_broken" if item["state"] == "broken" else "content_link_unverified",
         "url": item["url"], "source": item["source"], "source_kind": item["kind"],
         "status": item.get("status"), "state": item["state"], "checked_at": captured}
        for item in checked if item["state"] != "ok"
    ]
    return {
        "status": "available",
        "links": checked,
        "findings": findings,
        "blocking": blockers,
        "unverified": unverified,
        "coverage": {"discovered": len(candidates), "checked": len(checked),
                      "cap": MAX_DOCUMENT_LINKS, "truncated": len(candidates) >= MAX_DOCUMENT_LINKS},
    }


def audit_links(
    start: str,
    *,
    max_pages: int = MAX_PAGES,
    external_budget: int = MAX_EXTERNAL_CHECKS,
    fetcher: Callable[[str], Any] | None = None,
    external_fetcher: Callable[[str], Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Audit owned pages and bounded external links.

    ``fetcher`` is used for owned pages and sitemap documents.  By default it
    is the SSRF-safe ``public_fetch`` implementation.  ``external_fetcher``
    is separate so a caller can use a cache or a test double without changing
    the internal inventory.  External checks are deduplicated by URL and are
    capped before any request is made.
    """
    origin = _origin(start)
    if not origin:
        raise ValueError("start must be an absolute http or https URL")
    page_cap = max(1, min(int(max_pages or MAX_PAGES), MAX_PAGES))
    external_cap = max(0, min(int(external_budget if external_budget is not None else MAX_EXTERNAL_CHECKS), MAX_EXTERNAL_CHECKS))
    root = urllib.parse.urlsplit(origin)
    robots_url = urllib.parse.urlunsplit(root._replace(path="/robots.txt", query=""))
    sitemap_urls: list[str] = []
    unavailable: list[str] = []
    robots_result = _fetch(robots_url, fetcher)
    robots_parser = None
    if robots_result.get("ok") and int(robots_result.get("status", 0)) < 400:
        try:
            robots_parser, declared = seo.parse_robots(robots_result.get("body", b"").decode("utf-8", "replace"), origin)
            sitemap_urls.extend(declared)
        except (AttributeError, UnicodeError):
            pass
    else:
        unavailable.append(robots_url)
    if not sitemap_urls:
        sitemap_urls.append(urllib.parse.urlunsplit(root._replace(path="/sitemap.xml", query="")))

    sitemap_members: list[str] = []
    sitemap_truncated = False
    sitemap_seen: set[str] = set()
    sitemap_queue = deque(sitemap_urls[:MAX_SITEMAPS])
    while sitemap_queue and len(sitemap_seen) < MAX_SITEMAPS:
        sitemap_url = sitemap_queue.popleft()
        if sitemap_url in sitemap_seen:
            continue
        sitemap_seen.add(sitemap_url)
        result = _fetch(sitemap_url, fetcher)
        if not result.get("ok") or int(result.get("status", 0)) >= 400:
            unavailable.append(sitemap_url)
            continue
        document = seo.parse_sitemap_document(result.get("body", b""), origin)
        if document.get("kind") == "index":
            for child in document.get("children", []):
                if child not in sitemap_seen and len(sitemap_queue) + len(sitemap_seen) < MAX_SITEMAPS:
                    sitemap_queue.append(child)
                elif child not in sitemap_seen:
                    sitemap_truncated = True
        elif document.get("kind") == "urlset":
            for member in document.get("urls", []):
                if member not in sitemap_members and len(sitemap_members) < MAX_SITEMAP_MEMBERS:
                    sitemap_members.append(member)
                elif member not in sitemap_members:
                    sitemap_truncated = True

    queue: deque[tuple[str, str, str]] = deque([(origin, origin, "seed")])
    queue_truncated = False
    for member in sorted(sitemap_members):
        if seo.same_origin(member, origin):
            if len(queue) < MAX_QUEUE:
                queue.append((member, "sitemap", "sitemap"))
            else:
                queue_truncated = True
    queued: set[str] = set()
    inventory: list[dict[str, Any]] = []
    internal_links: list[dict[str, Any]] = []
    external_candidates: dict[str, list[str]] = {}
    last_fetch = 0.0
    while queue and len(inventory) < page_cap:
        url, source_url, source_kind = queue.popleft()
        if url in queued:
            continue
        queued.add(url)
        if not seo.same_origin(url, origin):
            continue
        if robots_parser is not None and not robots_parser.can_fetch(USER_AGENT, url):
            inventory.append({"url": url, "category": _category(url), "source": source_kind, "state": "excluded", "status": None, "reason": "robots_disallow"})
            continue
        wait = MIN_DELAY - (time.monotonic() - last_fetch)
        if wait > 0:
            sleep(wait)
        result = _fetch(url, fetcher)
        last_fetch = time.monotonic()
        status = result.get("status")
        if not result.get("ok"):
            error_status = _http_error_status(result)
            state = "broken" if error_status in (404, 410) else "unknown"
            inventory.append({"url": url, "category": _category(url), "source": source_kind, "state": state, "status": error_status, "error": result.get("error", "unknown")})
            if state == "broken":
                internal_links.append(_link_record(url, source_url, state, result))
            continue
        if isinstance(status, int) and status >= 400:
            state = "broken" if status in (404, 410) else "unknown"
            inventory.append({"url": url, "category": _category(url), "source": source_kind, "state": state, "status": status})
            if state == "broken":
                internal_links.append(_link_record(url, source_url, state, result))
            continue
        body = result.get("body", b"")
        content_type = str(result.get("content_type") or "")
        if content_type and "html" not in content_type.lower():
            inventory.append({"url": url, "category": _category(url), "source": source_kind, "state": "non_html", "status": status, "content_type": content_type})
            continue
        try:
            fields = seo.extract_html(body, result.get("final_url") or url)
        except Exception:
            inventory.append({"url": url, "category": _category(url), "source": source_kind, "state": "unknown", "status": status, "error": "parse_failed"})
            continue
        inventory.append({"url": url, "final_url": result.get("final_url") or url, "category": _category(url), "source": source_kind, "state": "ok", "status": status, "title": fields.get("title", ""), "link_count": len(fields.get("links", []))})
        for link in fields.get("links", []):
            if seo.same_origin(link, origin):
                if link not in queued and len(queue) < MAX_QUEUE:
                    queue.append((link, url, "internal_link"))
                elif link not in queued:
                    queue_truncated = True
            else:
                if link in external_candidates or len(external_candidates) < MAX_EXTERNAL_CANDIDATES:
                    external_candidates.setdefault(link, []).append(url)
                else:
                    queue_truncated = True

    # The queue is intentionally not silently discarded.  This makes the
    # inventory coverage honest when sitemap or internal-link discovery exceeds
    # the cap.
    for url, source_url, source_kind in list(queue):
        if url not in queued and seo.same_origin(url, origin):
            inventory.append({"url": url, "category": _category(url), "source": source_kind, "state": "unfetched", "status": None, "reason": "page_budget_exhausted"})
            queued.add(url)

    external_cache: dict[str, dict[str, Any]] = {}
    external_links: list[dict[str, Any]] = []
    external_checked = 0
    for link in sorted(external_candidates):
        sources = external_candidates[link]
        if link in external_cache:
            result = external_cache[link]
            reason = "cache"
        elif external_checked >= external_cap:
            result = {"ok": False, "error": "external_budget_exhausted"}
            reason = "external_budget_exhausted"
        else:
            result = _fetch(link, external_fetcher or fetcher)
            external_cache[link] = result
            external_checked += 1
            reason = None
        state = _external_state(result)
        external_links.append(_link_record(link, sources[0], state, result, reason))
        for extra_source in sources[1:]:
            external_links.append(_link_record(link, extra_source, state, result, "cache"))

    return {
        "status": "available" if inventory else "unavailable",
        "page_inventory": inventory,
        "internal_links": internal_links,
        "external_links": external_links,
        "sitemap": {"members": sorted(sitemap_members), "unavailable": sorted(set(unavailable))},
        "coverage": {
            "page_cap": page_cap,
            "pages_fetched": sum(1 for page in inventory if page.get("state") != "unfetched"),
            "pages_unfetched": sum(1 for page in inventory if page.get("state") == "unfetched"),
            "external_budget": external_cap,
            "external_unique_discovered": len(external_candidates),
            "external_checked": external_checked,
            "external_unchecked": max(0, len(external_candidates) - external_checked),
            "external_budget_exhausted": len(external_candidates) > external_checked,
            "sitemap_member_cap": MAX_SITEMAP_MEMBERS,
            "sitemap_truncated": sitemap_truncated,
            "queue_cap": MAX_QUEUE,
            "queue_truncated": queue_truncated,
            "external_candidate_cap": MAX_EXTERNAL_CANDIDATES,
        },
    }

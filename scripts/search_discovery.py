#!/usr/bin/env python3
"""Bounded, explicit Google Search Console discovery operations.

Inspection is read-only. Sitemap submission requires ``--submit`` and uses the
write Search Console scope only in that mode. Results intentionally contain
receipts and stable statuses, never Google response bodies or credentials.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from seo_measurement import SERVICE_ACCOUNT_FILE, sign_jwt
import public_fetch

API = "https://searchconsole.googleapis.com"
TOKEN_URL = "https://oauth2.googleapis.com/token"
MAX_SITEMAPS = 10
MAX_URLS = 50
TIMEOUT = 15
MAX_BYTES = 300_000
READ_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/webmasters"


def _property(value: object) -> str:
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError("invalid property")
    if value.startswith("sc-domain:"):
        host = value[10:].strip().lower().rstrip(".")
        if not host or "/" in host or ":" in host or "?" in host or "#" in host:
            raise ValueError("invalid domain property")
        return "sc-domain:" + host
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("property must be an HTTPS URL-prefix property")
    if parsed.query or parsed.fragment or parsed.port not in (None, 443):
        raise ValueError("property contains unsupported URL parts")
    path = parsed.path or "/"
    if path != "/":
        raise ValueError("property must be an origin URL")
    return "https://" + parsed.hostname.lower() + "/"


def _public_url(value: object, property_url: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("invalid target URL")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("target must be an HTTPS URL without credentials or query")
    if parsed.hostname is None or parsed.port not in (None, 443):
        raise ValueError("target URL is invalid")
    normalized = urllib.parse.urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", "", ""))
    try:
        public_fetch._validate_target(normalized)  # same public-DNS/SSRF policy as owned fetches
    except Exception as exc:
        raise ValueError("target URL is not public") from exc
    expected_host = property_url[10:] if property_url.startswith("sc-domain:") else urllib.parse.urlsplit(property_url).hostname
    if parsed.hostname.lower().rstrip(".") != expected_host.lower().rstrip("."):
        raise ValueError("target origin does not match property")
    return normalized


def _account(path: object) -> dict:
    if not isinstance(path, str) or not path or len(path) > 1024:
        raise ValueError("service account file is unavailable")
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_file() or candidate.is_symlink():
        raise ValueError("service account file is unavailable")
    with candidate.open(encoding="utf-8") as handle:
        account = json.load(handle)
    if not isinstance(account, dict) or not isinstance(account.get("client_email"), str) or not isinstance(account.get("private_key"), str):
        raise ValueError("invalid service account")
    return account


def access_token(service_account_file: str, *, submit: bool, token_request=None) -> str:
    account = _account(service_account_file)
    issued = int(time.time())
    scope = WRITE_SCOPE if submit else READ_SCOPE
    assertion = sign_jwt({"alg": "RS256", "typ": "JWT"}, {
        "iss": account["client_email"], "scope": scope, "aud": TOKEN_URL,
        "iat": issued, "exp": issued + 3600,
    }, account["private_key"])
    request = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode())
    response = token_request(request) if token_request else urllib.request.urlopen(request, timeout=TIMEOUT)
    payload = json.load(response) if hasattr(response, "read") else response
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("access token unavailable")
    return token


def _request(token: str, method: str, path: str, payload=None, request=None) -> dict:
    if not path.startswith("/webmasters/v3/sites/") and not path.startswith("/v1/urlInspection/"):
        raise ValueError("untrusted API path")
    req = urllib.request.Request(API + path, method=method,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    opener = request or urllib.request.urlopen
    response = opener(req, timeout=TIMEOUT)
    if isinstance(response, dict):
        result = response
    else:
        raw = response.read(MAX_BYTES)
        result = json.loads(raw) if raw.strip() else {}
        close = getattr(response, "close", None)
        if close:
            close()
    if not isinstance(result, dict):
        raise ValueError("malformed API response")
    return result


def _site_path(property_url: str) -> str:
    return "/webmasters/v3/sites/" + urllib.parse.quote(property_url, safe="")


def _safe_inspection_link(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "search.google.com" or parsed.username or parsed.password:
        return None
    if parsed.fragment:
        return None
    return value


def _safe_sitemap_entry(entry: object) -> dict | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or len(entry["path"]) > 2048:
        return None
    result = {"path": entry["path"]}
    for key in ("isPending", "lastSubmitted", "lastDownloaded"):
        value = entry.get(key)
        if isinstance(value, (bool, str)) and (not isinstance(value, str) or len(value) <= 128):
            result[key] = value
    for key in ("warnings", "errors", "contents"):
        value = entry.get(key)
        if isinstance(value, list):
            result[key] = [str(item)[:256] for item in value[:50]]
    return result


def discover(config: dict, *, submit=False, token=None, token_request=None, request=None) -> dict:
    if not isinstance(config, dict):
        return {"status": "invalid", "error": "configuration must be an object"}
    submitted = []
    skipped = []
    inspections = []
    checked_at = datetime.now(timezone.utc).isoformat()
    property_url = None
    try:
        property_url = _property(config.get("property"))
        sitemap_values = config.get("sitemaps", [])
        url_values = config.get("urls", [])
        if not isinstance(sitemap_values, list) or not isinstance(url_values, list):
            raise ValueError("sitemaps and urls must be arrays")
        if len(sitemap_values) > MAX_SITEMAPS or len(url_values) > MAX_URLS:
            raise ValueError("discovery target cap exceeded")
        sitemaps = list(dict.fromkeys(_public_url(item, property_url) for item in sitemap_values))
        urls = list(dict.fromkeys(_public_url(item, property_url) for item in url_values))
        account_file = config.get("service_account_file", SERVICE_ACCOUNT_FILE)
        token = token or access_token(account_file, submit=submit, token_request=token_request)
        site = _site_path(property_url)
        inventory = _request(token, "GET", site + "/sitemaps", request=request)
        entries = inventory.get("sitemap", [])
        if not isinstance(entries, list) or len(entries) > 100:
            raise ValueError("sitemap inventory exceeds bounded coverage")
        existing = {item.get("path") for item in entries if isinstance(item, dict) and isinstance(item.get("path"), str)}
        inventory_entries = [_safe_sitemap_entry(item) for item in entries]
        inventory_entries = [item for item in inventory_entries if item is not None]
        if submit:
            for sitemap in sitemaps:
                if sitemap in existing:
                    skipped.append({"sitemap": sitemap, "reason": "already_submitted"})
                    continue
                _request(token, "PUT", site + "/sitemaps/" + urllib.parse.quote(sitemap, safe=""), request=request)
                submitted.append(sitemap)
            try:
                inventory = _request(token, "GET", site + "/sitemaps", request=request)
                entries = inventory.get("sitemap", [])
                if not isinstance(entries, list) or len(entries) > 100:
                    raise ValueError("sitemap inventory exceeds bounded coverage")
                inventory_entries = [_safe_sitemap_entry(item) for item in entries]
                inventory_entries = [item for item in inventory_entries if item is not None]
                present = {item["path"] for item in inventory_entries}
                missing = [item for item in sitemaps if item not in present]
                inventory_status = "partial" if missing else "verified"
                inventory_count = len(entries)
            except Exception as exc:
                return {"status": "source_unavailable", "mode": "submit", "property": property_url,
                        "checked_at": checked_at, "sitemaps": {"requested": len(sitemaps),
                        "submitted": submitted, "skipped": skipped, "inventory_status": "unavailable",
                        "submission_checked_at": checked_at}, "inventory": {"status": "unavailable",
                        "entries": inventory_entries},
                        "inspections": inspections, "warnings": [type(exc).__name__], "errors": []}
        else:
            inventory_status = "available"
            inventory_count = len(entries)
        for url in urls:
            response = _request(token, "POST", "/v1/urlInspection/index:inspect",
                                {"inspectionUrl": url, "siteUrl": property_url}, request=request)
            result = response.get("inspectionResult") if isinstance(response.get("inspectionResult"), dict) else {}
            index = result.get("indexStatusResult") if isinstance(result.get("indexStatusResult"), dict) else {}
            verdict = index.get("verdict")
            item = {"url": url, "verdict": verdict,
                                "coverage_state": index.get("coverageState"),
                                "robots_txt_state": index.get("robotsTxtState"),
                                "indexing_state": index.get("indexingState")}
            link = _safe_inspection_link(result.get("inspectionResultLink"))
            if link:
                item["inspection_result_link"] = link
            inspections.append(item)
        status = "available" if all(item.get("verdict") for item in inspections) else "source_unavailable"
        warnings = []
        if submit and inventory_status == "partial":
            status = "partial"
            warnings.append("submitted_sitemap_missing_from_inventory")
        return {"status": status, "mode": "submit" if submit else "inspect",
                "checked_at": checked_at,
                "property": property_url, "sitemaps": {"requested": len(sitemaps),
                "submitted": submitted, "skipped": skipped, "inventory_status": inventory_status,
                "submission_checked_at": checked_at if submit else None},
                "inventory": {"status": inventory_status, "count": inventory_count,
                              "checked_at": checked_at, "entries": inventory_entries},
                "inspections": inspections, "warnings": warnings, "errors": []}
    except Exception as exc:
        status = "blocked" if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403) else "source_unavailable"
        return {"status": status, "error": type(exc).__name__, "checked_at": checked_at,
                "property": property_url,
                "sitemaps": {"submitted": submitted, "skipped": skipped},
                "inspections": inspections, "warnings": [], "errors": [type(exc).__name__]}


def load_config(path: str) -> dict:
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_file() or candidate.is_symlink():
        raise ValueError("configuration file is unavailable")
    with candidate.open(encoding="utf-8") as handle:
        return json.load(handle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("--submit", action="store_true", help="explicitly submit new sitemaps")
    parser.add_argument("--json", action="store_true", help="emit JSON receipt")
    args = parser.parse_args(argv)
    try:
        result = discover(load_config(args.config), submit=args.submit)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        result = {"status": "invalid", "error": type(exc).__name__}
    print(json.dumps(result, sort_keys=True) if args.json else result["status"])
    return 0 if result.get("status") == "available" else 1


if __name__ == "__main__":
    raise SystemExit(main())

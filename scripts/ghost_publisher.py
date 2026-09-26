"""Small, deterministic Ghost Admin API publication adapter.

The adapter deliberately has no database or model dependency.  The caller must
provide the approved content digest and an explicit destination configuration.
It creates a Ghost draft, reads that draft back, and only then publishes it.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from html.parser import HTMLParser


class GhostPublishError(ValueError):
    """A safe, user-facing publication error with no credential material."""


def content_digest(item: dict) -> str:
    """Return the approval digest for exactly the fields sent to Ghost."""
    if not isinstance(item, dict):
        raise GhostPublishError("content item must be an object")
    selected = {
        "title": item.get("title") or "",
        "body": item.get("body") or "",
        "content_blocks": item.get("content_blocks") or [],
        "structured": item.get("structured") or {},
    }
    raw = json.dumps(selected, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value[:70].strip("-")


def _endpoint(destination: dict) -> str:
    value = (destination.get("endpoint") or destination.get("api_url") or destination.get("base_url") or "").strip()
    if not value:
        raise GhostPublishError("Ghost endpoint is required")
    parsed = urllib.parse.urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GhostPublishError("Ghost endpoint must not contain credentials or query data")
    host = (parsed.hostname or "").lower().rstrip(".")
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "http" and not loopback:
        raise GhostPublishError("Ghost endpoint must use HTTPS unless it is localhost")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise GhostPublishError("Ghost endpoint must use HTTPS")
    if not host:
        raise GhostPublishError("Ghost endpoint hostname is required")
    value = value.rstrip("/")
    # Accept either a Ghost site root or its explicit Admin API root.  Keeping
    # one canonical form prevents accidental /ghost/api/admin duplication.
    suffix = "/ghost/api/admin"
    if value.lower().endswith(suffix):
        value = value[:-len(suffix)].rstrip("/")
    return value


def _read_credential(item: dict, destination: dict) -> str:
    ref = destination.get("credential_ref") or "GHOST_ADMIN_API_KEY"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(ref)):
        raise GhostPublishError("Ghost credential_ref is invalid")
    env_file = destination.get("env_file") or destination.get("project_env_file")
    project = Path(str(item.get("local_path") or destination.get("project_path") or ".")).resolve()
    if not env_file:
        raise GhostPublishError("Ghost project-relative env_file is required")
    env_path = (project / str(env_file)).resolve()
    try:
        env_path.relative_to(project)
    except ValueError as exc:
        raise GhostPublishError("Ghost env_file must remain inside the project") from exc
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(ref + "="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    except OSError as exc:
        raise GhostPublishError("Ghost project env file could not be read") from exc
    raise GhostPublishError("Named Ghost credential was not found in the project env file")


def _jwt(key: str) -> str:
    try:
        key_id, secret = key.split(":", 1)
        secret_bytes = bytes.fromhex(secret)
    except (ValueError, TypeError):
        raise GhostPublishError("Ghost Admin API key must be id:hex-secret")
    header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
    payload = {"iat": __import__("time").time_ns() // 1_000_000_000,
               "exp": __import__("time").time_ns() // 1_000_000_000 + 300,
               "aud": "/admin/"}
    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).rstrip(b"=")
    unsigned = enc(header) + b"." + enc(payload)
    sig = hmac.new(secret_bytes, unsigned, hashlib.sha256).digest()
    return (unsigned + b"." + base64.urlsafe_b64encode(sig).rstrip(b"=")).decode()


def render_pipeline_html(item: dict) -> str:
    from content_pipeline import render_content_blocks, render_pipeline_css
    blocks = item.get("content_blocks") or []
    rendered = render_content_blocks(blocks, item.get("title") or "Untitled")
    rendered = rendered.replace("<article>", '<article class="pipeline-article">', 1)
    # Ghost treats this as one lossless HTML card.  The pipeline renderer adds
    # an article h1 for dashboard previews, but Ghost themes render the post
    # title themselves, so remove only that duplicate heading here.
    rendered = re.sub(r"<h1>.*?</h1>", "", rendered, count=1, flags=re.S)
    return ("<!--kg-card-begin: html-->\n"
            '<div class="agency-content-card">' + render_pipeline_css() +
            rendered + "</div>\n<!--kg-card-end: html-->")


class GhostAdminClient:
    def __init__(self, endpoint: str, api_key: str, opener=None, admin_host=None):
        self.endpoint = endpoint.rstrip("/")
        self.token = _jwt(api_key)
        self.opener = opener or urllib.request.build_opener(_NoRedirect())
        self.admin_host = admin_host

    def request(self, method: str, path: str, payload=None):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        req = urllib.request.Request(self.endpoint + path, data=data, method=method,
        headers={"Authorization": "Ghost " + self.token,
                                              "Accept-Version": "v5.0",
                                              "Content-Type": "application/json"})
        if urllib.parse.urlsplit(self.endpoint).hostname in {"localhost", "127.0.0.1", "::1"}:
            req.add_header("X-Forwarded-Proto", "https")
            if self.admin_host:
                if not re.fullmatch(r'[A-Za-z0-9.:-]+', self.admin_host):
                    raise GhostPublishError('Invalid Ghost admin host')
                req.add_header('Host', self.admin_host)
        try:
            with self.opener.open(req, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except GhostPublishError:
            raise
        except urllib.error.HTTPError as exc:
            raise GhostPublishError(f"Ghost API returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise GhostPublishError("Ghost API request failed") from exc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GhostPublishError("Ghost API redirects are not allowed")


def _post(response):
    posts = response.get("posts") if isinstance(response, dict) else None
    return (posts or [None])[0]


def _required_fragments(item: dict) -> list[str]:
    fragments = ["<!--kg-card-begin: html-->", "<!--kg-card-end: html-->",
                 "pipeline-article"]
    for block in item.get("content_blocks") or []:
        if not isinstance(block, dict) or block.get("type") != "editorial_visual":
            continue
        for key in ("title", "caption", "before", "after"):
            value = block.get(key)
            if value:
                fragments.append(html.escape(str(value)))
        for key in ("notes", "items"):
            values = block.get(key) or []
            if isinstance(values, list):
                fragments.extend(html.escape(str(value)) for value in values if value)
    return fragments


def _normal_html(value: str) -> str:
    class CanonicalHTML(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []
        def handle_starttag(self, tag, attrs):
            self.parts.append(('start', tag, sorted(attrs)))
        def handle_endtag(self, tag):
            self.parts.append(('end', tag))
        def handle_data(self, data):
            text = re.sub(r'\s+', ' ', data).strip()
            if text:
                self.parts.append(('text', text))
        def handle_comment(self, data):
            self.parts.append(('comment', data.strip()))
    parser = CanonicalHTML()
    parser.feed(value or '')
    parser.close()
    return repr(parser.parts)


def _validate_item(item: dict) -> None:
    structured = item.get("structured") or {}
    facts = structured.get("facts", []) if isinstance(structured, dict) else []
    from editorial_visuals import validate_visual
    for block in item.get("content_blocks") or []:
        if not isinstance(block, dict) or block.get("type") != "editorial_visual":
            continue
        if block.get("reviewed") is not True:
            raise GhostPublishError("every visual must be reviewed before Ghost publication")
        try:
            validate_visual(block, facts)
        except (ValueError, TypeError, KeyError) as exc:
            raise GhostPublishError("a visual failed its publication validation") from exc


def _prepare_managed_assets(item: dict, destination: dict) -> dict:
    """Copy reviewed managed visuals to the engagement public-media store.

    The approved source item is never mutated.  Ghost receives a deep copy with
    immutable engagement URLs, and every copied object is read back by hash.
    """
    blocks = item.get("content_blocks") or []
    managed = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        is_image = kind == "image_slot" or (kind == "editorial_visual" and block.get("kind") in {"image", "photo"})
        if not is_image:
            continue
        if block.get("reviewed") is not True:
            raise GhostPublishError(f"image block {index} must be reviewed before publication")
        metadata = block.get("asset") or block.get("asset_metadata")
        if not isinstance(metadata, dict) or not metadata.get("sha256") or not metadata.get("object_key"):
            raise GhostPublishError(f"image block {index} is not a managed editorial asset")
        managed.append((index, block, metadata))
    if not managed:
        return item
    storage = destination.get("asset_storage")
    if not isinstance(storage, (dict, str)):
        raise GhostPublishError("managed images require an explicit asset_storage destination")
    from content_assets import copy_to_engagement, read_core_asset
    out = copy.deepcopy(item)
    for index, original, metadata in managed:
        try:
            copied = copy_to_engagement(metadata, read_core_asset(metadata), storage)
        except Exception as exc:
            raise GhostPublishError(f"managed image {index} could not be copied and verified") from exc
        block = out["content_blocks"][index]
        block["url"] = copied["url"]
        if block.get("type") == "image_slot":
            block["image_url"] = copied["url"]
        block["asset"] = {**metadata, "url": copied["url"], "object_key": copied["object_key"]}
    return out


class _SafeMarkup(HTMLParser):
    blocked = {"script", "iframe", "object", "embed", "form", "input", "button",
               "meta", "link", "base"}
    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.blocked:
            raise GhostPublishError("rendered content contains a blocked HTML element")
        for name, value in attrs:
            if name.lower().startswith("on"):
                raise GhostPublishError("rendered content contains an event handler")
            if name.lower() in {"href", "src", "action", "xlink:href", "srcset"} and value:
                if value.startswith("#") or value.startswith("mailto:"):
                    continue
                if not value.startswith("https://"):
                    raise GhostPublishError("rendered content contains a non-HTTPS URL")
            if name.lower() == "style" and re.search(r"@import|url\s*\(|expression\s*\(", value, re.I):
                raise GhostPublishError("rendered content contains unsafe CSS")
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def _validate_markup(markup: str) -> None:
    if re.search(r'@import|url\s*\(|expression\s*\(', markup, re.I):
        raise GhostPublishError('Rendered content contains unsupported CSS loading')
    parser = _SafeMarkup(convert_charrefs=True)
    try:
        parser.feed(markup)
        parser.close()
    except GhostPublishError:
        raise
    except Exception as exc:
        raise GhostPublishError("rendered content is not valid HTML") from exc


def publish(item: dict, destination: dict, approved_digest: str, publish: bool = True,
            client: GhostAdminClient | None = None) -> dict:
    """Create, verify, and optionally publish one Ghost post.

    ``publish=False`` stops after the verified private draft, which is the safe
    mode for previews and all automated tests.
    """
    digest = content_digest(item)
    if not isinstance(approved_digest, str) or not hmac.compare_digest(digest, approved_digest):
        raise GhostPublishError("approved content digest does not match the current item")
    destination = destination if isinstance(destination, dict) else {}
    endpoint = _endpoint(destination)
    if client is None:
        key = destination.get("api_key") or _read_credential(item, destination)
        client = GhostAdminClient(endpoint, key, admin_host=destination.get('admin_host'))
    content_id = item.get("id")
    if content_id is None:
        raise GhostPublishError("content item id is required")
    item_for_publish = _prepare_managed_assets(item, destination)
    _validate_item(item_for_publish)
    from content_quality import publication_blockers
    blockers = publication_blockers(item_for_publish.get("content_blocks") or [])
    if blockers:
        raise GhostPublishError("content quality blockers remain before publication")
    slug = "content-" + str(content_id)
    title = item_for_publish.get("title") or "Untitled"
    marker = "#agency-content-%s-%s" % (content_id, digest[:16])
    html_body = render_pipeline_html(item_for_publish)
    if "visual unavailable" in html_body.lower():
        raise GhostPublishError("rendered visual content is unavailable")
    _validate_markup(html_body)
    existing = None
    try:
        existing = _post(client.request("GET", "/ghost/api/admin/posts/slug/" + urllib.parse.quote(slug, safe="") + "/?formats=html"))
    except GhostPublishError as exc:
        if "HTTP 404" not in str(exc):
            raise
    if existing:
        tags = existing.get("tags") or []
        names = {t.get("name") for t in tags if isinstance(t, dict)}
        if marker not in names:
            raise GhostPublishError("Ghost slug already exists and is not owned by this content item")
        post_id = existing.get("id")
    else:
        draft = _post(client.request("POST", "/ghost/api/admin/posts/?source=html", {
            "posts": [{"title": title, "slug": slug, "html": html_body, "status": "draft",
                       "tags": [{"name": marker, "visibility": "internal"}]}]}))
        if not draft:
            raise GhostPublishError("Ghost draft did not preserve the rendered HTML")
        post_id = draft.get("id")
        if not post_id:
            raise GhostPublishError("Ghost draft response did not include an id")
    checked = _post(client.request("GET", "/ghost/api/admin/posts/" + urllib.parse.quote(str(post_id), safe="") + "/?formats=html"))
    checked_html = (checked or {}).get("html") or ""
    if any(fragment not in checked_html for fragment in _required_fragments(item_for_publish)) or _normal_html(checked_html) != _normal_html(html_body):
        raise GhostPublishError("Ghost read-back did not preserve the rendered HTML")
    if not publish:
        status = (checked or {}).get("status")
        if status not in {"draft", "internal"}:
            raise GhostPublishError("Ghost prepare mode expected a private draft")
        return {"ok": True, "post_id": post_id, "slug": slug, "digest": digest, "status": status}
    if (checked or {}).get("status") == "published":
        public = destination.get("public_url") or destination.get("base_url") or ""
        if not str(public).startswith("https://"):
            raise GhostPublishError("published Ghost result requires an HTTPS base_url")
        return {"ok": True, "post_id": post_id, "slug": slug, "digest": digest,
                "status": "published", "url": str(public).rstrip("/") + "/" + slug + "/"}
    updated_at = checked.get("updated_at") if checked else None
    payload = {"posts": [{"updated_at": updated_at, "status": "published"}]}
    client.request("PUT", "/ghost/api/admin/posts/" + urllib.parse.quote(str(post_id), safe="") + "/", payload)
    final = _post(client.request("GET", "/ghost/api/admin/posts/" + urllib.parse.quote(str(post_id), safe="") + "/?formats=html"))
    if (final or {}).get("status") != "published":
        raise GhostPublishError("Ghost did not confirm publication")
    if _normal_html(final.get('html')) != _normal_html(html_body):
        raise GhostPublishError('Published HTML differs from the approved content; inspect the article before retrying')
    public = destination.get("public_url") or destination.get("base_url") or ""
    if not str(public).startswith("https://"):
        raise GhostPublishError("published Ghost result requires an HTTPS base_url")
    return {"ok": True, "post_id": post_id, "slug": slug, "digest": digest,
            "status": "published", "url": str(public).rstrip("/") + "/" + slug + "/"}

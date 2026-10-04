"""Deterministic publication of approved editorial items to a static blog.

The adapter has no database, project, credential, or network dependency.  The
caller supplies an already-authorized item and destination.  Private ownership
receipts live beside the public root, while public files contain only the
rendered article and bounded index metadata. Individual public files are atomic;
whole-generation recovery is eventual and an exact retry repairs staged work.
"""
from __future__ import annotations

import hashlib
import html
import hmac
import json
import os
import re
import tempfile
from contextlib import contextmanager
import fcntl
from pathlib import Path
from urllib.parse import urlsplit

from ghost_publisher import GhostPublishError, _validate_item, _validate_markup, content_digest, render_pipeline_html


class StaticPublishError(ValueError):
    """Safe publication failure without filesystem or credential details."""


PUBLICATION_ROOT = Path("/home/agency/.local/share/agency-marketing/publications")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


def _fail(message: str):
    raise StaticPublishError(message)


def _destination(destination: dict, brand_id: str | None = None) -> tuple[Path, str]:
    if not isinstance(destination, dict):
        _fail("static destination must be an object")
    if destination.get("type") != "static":
        _fail("static destination type is required")
    if destination.get("enabled") is not True:
        _fail("static destination is disabled")
    base_url = str(destination.get("base_url") or "").strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        _fail("static base_url must be an HTTPS origin or path without credentials")
    output_value = destination.get("output_root")
    if not output_value:
        _fail("static output_root is required")
    root = Path(str(output_value)).expanduser()
    try:
        root = root.resolve(strict=False)
        allowed = PUBLICATION_ROOT.resolve(strict=False)
        root.relative_to(allowed)
    except (OSError, ValueError) as exc:
        raise StaticPublishError("static output_root is outside the Agency publication root") from exc
    if root == allowed:
        _fail("static output_root must be brand-scoped")
    if brand_id is not None and root != allowed / str(brand_id):
        _fail("static output_root must match the content brand")
    return root, base_url


def _assert_no_symlink(path: Path, stop: Path) -> None:
    current = path
    while True:
        if current.exists() and current.is_symlink():
            _fail("static publication path cannot contain symlinks")
        if current == stop or current.parent == current:
            break
        current = current.parent


def _brand_item(item: dict) -> tuple[str, str]:
    if not isinstance(item, dict):
        _fail("content item must be an object")
    brand_id = item.get("brand_id")
    content_id = item.get("id")
    if isinstance(brand_id, bool) or not isinstance(brand_id, int) or brand_id < 1:
        _fail("brand_id is required")
    if isinstance(content_id, bool) or not isinstance(content_id, (int, str)) or not _ID.fullmatch(str(content_id)):
        _fail("content item id is invalid")
    return str(brand_id), str(content_id)


def _status_gate(item: dict, destination: dict) -> None:
    project_status = item.get("project_status", destination.get("project_status"))
    publication_status = item.get("publication_status", destination.get("publication_status"))
    if project_status != "active":
        _fail("static publication requires an active project")
    if publication_status not in {"publishing", "publish_failed"}:
        _fail("static publication is not in an approved publishing state")


@contextmanager
def _brand_lock(brand_id: str):
    lock_path = _receipt_root() / "locks" / f"{brand_id}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_symlink(lock_path.parent, PUBLICATION_ROOT.resolve(strict=False))
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _receipt_root() -> Path:
    return PUBLICATION_ROOT.parent / "receipts"


def _receipt_path(brand_id: str, content_id: str) -> Path:
    return _receipt_root() / brand_id / f"{content_id}.json"


def _pending_path(brand_id: str, content_id: str) -> Path:
    return _receipt_root() / brand_id / f"{content_id}.pending.json"


def _manifest_path(root: Path) -> Path:
    return root / ".agency-static-manifest.json"


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_symlink(path.parent, PUBLICATION_ROOT.resolve(strict=False))
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _article_html(item: dict, canonical: str, digest: str, brand_name: str) -> str:
    _validate_item(item)
    rendered = render_pipeline_html(item)
    _validate_markup(rendered)
    title = html.escape(str(item.get("title") or "Untitled"), quote=True)
    description_value = (item.get("structured") or {}).get("meta_description") if isinstance(item.get("structured"), dict) else ""
    description = html.escape(str(description_value or item.get("title") or ""), quote=True)[:320]
    canonical_escaped = html.escape(canonical, quote=True)
    name = html.escape(str(brand_name or "Brand"), quote=True)
    home = html.escape(canonical.split("/article/", 1)[0] + "/", quote=True)
    contact = html.escape(home.rstrip("/") + "/#contact", quote=True)
    style = "body{margin:0;background:#f4f6f8;color:#405167;font:16px/1.7 system-ui,-apple-system,Segoe UI,sans-serif}header,main,footer{width:min(760px,calc(100% - 32px));margin:auto}header{padding:24px 0 12px;border-bottom:1px solid #d5dee7}header a,footer a{color:#173f6d;text-decoration:none;font-weight:700}main{padding:42px 0}main h1{color:#17283d;line-height:1.15}main p,main li{font-size:16px}footer{padding:22px 0 40px;border-top:1px solid #d5dee7;color:#68788a;font-size:13px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.agency-content-card{overflow-wrap:anywhere}"
    document = f"<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{title} | {name}</title><meta name=\"description\" content=\"{description}\"><link rel=\"canonical\" href=\"{canonical_escaped}\"><style>{style}</style></head><body><header><a href=\"{home}\">{name}</a></header><main data-agency-content-digest=\"{digest}\">{rendered}</main><footer><a href=\"{home}\">{name}</a><a href=\"{contact}\">Contact</a></footer></body></html>"
    return document


def _owned_receipts(root: Path, brand_id: str) -> list[dict]:
    folder = _receipt_root() / brand_id
    if not folder.exists() or folder.is_symlink():
        return []
    rows = []
    for path in sorted(folder.glob("*.json")):
        row = _read_json(path)
        if row and row.get("output_root") == str(root) and row.get("brand_id") == brand_id:
            rows.append(row)
    return rows


def _refresh_indexes(root: Path, base_url: str, brand_id: str) -> None:
    rows = sorted(_owned_receipts(root, brand_id), key=lambda row: (row.get("content_id", ""), row.get("canonical", "")))
    links = []
    urls = []
    for row in rows:
        canonical = str(row.get("canonical") or "")
        title = html.escape(str(row.get("title") or "Untitled"), quote=True)
        links.append(f'<li><a href="{html.escape(canonical, quote=True)}">{title}</a></li>')
        urls.append(f'<url><loc>{html.escape(canonical, quote=True)}</loc></url>')
    brand_name = html.escape(str((rows[0].get("brand_name") if rows else "Brand") or "Brand"), quote=True)
    home = html.escape(base_url + "/", quote=True)
    contact = html.escape(base_url + "/#contact", quote=True)
    style = "body{margin:0;background:#f4f6f8;color:#405167;font:16px/1.7 system-ui,-apple-system,Segoe UI,sans-serif}header,main,footer{width:min(760px,calc(100% - 32px));margin:auto}header{padding:24px 0 12px;border-bottom:1px solid #d5dee7}header a,footer a{color:#173f6d;text-decoration:none;font-weight:700}main{padding:42px 0}h1{color:#17283d}li{margin:8px 0}footer{padding:22px 0 40px;border-top:1px solid #d5dee7;color:#68788a;font-size:13px}"
    index = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Articles | " + brand_name + "</title><meta name=\"description\" content=\"Published articles from " + brand_name + "\"><link rel=\"canonical\" href=\"" + home + "\"><style>" + style + "</style></head><body><header><a href=\"" + home + "\">" + brand_name + "</a></header><main><h1>Articles</h1><ul>" + "".join(links) + "</ul></main><footer><a href=\"" + home + "\">" + brand_name + "</a><a href=\"" + contact + "\">Contact</a></footer></body></html>")
    sitemap = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + "</urlset>"
    _write_atomic(root / "index.html", index)
    _write_atomic(root / "sitemap.xml", sitemap)


def _publish_unlocked(item: dict, destination: dict, approved_digest: str) -> dict:
    """Atomically publish one approved article and rebuild owned indexes."""
    brand_id, content_id = _brand_item(item)
    root, base_url = _destination(destination, brand_id)
    _status_gate(item, destination)
    digest = content_digest(item)
    if not isinstance(approved_digest, str) or not hmac.compare_digest(digest, approved_digest):
        _fail("approved content digest does not match the current item")
    article_root = root / "article" / content_id
    article_path = article_root / "index.html"
    receipt_path = _receipt_path(brand_id, content_id)
    pending_path = _pending_path(brand_id, content_id)
    _assert_no_symlink(root, PUBLICATION_ROOT.resolve(strict=False))
    _assert_no_symlink(article_root, PUBLICATION_ROOT.resolve(strict=False))
    _assert_no_symlink(article_path, PUBLICATION_ROOT.resolve(strict=False))
    _assert_no_symlink(receipt_path, PUBLICATION_ROOT.resolve(strict=False))
    _assert_no_symlink(pending_path, PUBLICATION_ROOT.resolve(strict=False))
    canonical = f"{base_url}/article/{content_id}/"
    document = _article_html(item, canonical, digest, str(destination.get("brand_name") or "Brand"))
    checksum = hashlib.sha256(document.encode("utf-8")).hexdigest()
    existing_receipt = _read_json(receipt_path)
    pending = _read_json(pending_path)
    if article_path.exists() or existing_receipt:
        if article_path.exists() and not article_path.is_file():
            _fail("existing static publication ownership is unproven")
        if not existing_receipt and not pending:
            _fail("existing static publication ownership is unproven")
        owner = existing_receipt or pending
        if (
            owner.get("manifest_hash") != checksum
            or owner.get("digest") != digest
            or str(owner.get("output_root")) != str(root)
            or str(owner.get("canonical")) != canonical
            or str(owner.get("brand_id")) != brand_id
            or str(owner.get("content_id")) != content_id
            or str(owner.get("article_path")) != str(article_path)
        ):
            _fail("existing static publication conflicts with this content")
        if not article_path.exists():
            _write_atomic(article_path, document)
        if hashlib.sha256(article_path.read_bytes()).hexdigest() != checksum:
            _fail("existing static publication checksum differs")
        if not existing_receipt:
            receipt = dict(pending)
            receipt.pop("staged_at", None)
            _write_atomic(receipt_path, json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
            try:
                pending_path.unlink()
            except FileNotFoundError:
                pass
        _refresh_indexes(root, base_url, brand_id)
        return {"ok": True, "idempotent": True, "brand_id": brand_id, "content_id": content_id, "digest": digest, "manifest_hash": checksum, "url": canonical}
    receipt = {"version": 1, "brand_id": brand_id, "content_id": content_id, "brand_name": str(destination.get("brand_name") or "Brand"), "title": str(item.get("title") or "Untitled"), "digest": digest, "manifest_hash": checksum, "output_root": str(root), "canonical": canonical, "article_path": str(article_path), "published_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
    _write_atomic(pending_path, json.dumps({**receipt, "staged_at": receipt["published_at"]}, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    _write_atomic(article_path, document)
    _write_atomic(receipt_path, json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    try:
        pending_path.unlink()
    except FileNotFoundError:
        pass
    _refresh_indexes(root, base_url, brand_id)
    return {"ok": True, "idempotent": False, "brand_id": brand_id, "content_id": content_id, "digest": digest, "manifest_hash": checksum, "url": canonical}


def publish(item: dict, destination: dict, approved_digest: str) -> dict:
    brand_id, _ = _brand_item(item)
    with _brand_lock(brand_id):
        return _publish_unlocked(item, destination, approved_digest)


def _rollback_unlocked(destination: dict, manifest_hash: str) -> dict:
    """Archive and unpublish an exact owned article, preserving its bytes."""
    root_value = destination.get("output_root") if isinstance(destination, dict) else None
    root_hint = Path(str(root_value)).expanduser().resolve(strict=False) if root_value else None
    brand_hint = None
    if root_hint is not None:
        try:
            brand_hint = root_hint.name
        except (AttributeError, OSError):
            brand_hint = None
    root, base_url = _destination(destination, brand_hint)
    if not isinstance(manifest_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_hash):
        _fail("manifest hash is invalid")
    manifest = None
    manifest_path = None
    for candidate in _receipt_root().glob("*/*.json"):
        row = _read_json(candidate)
        if row and row.get("output_root") == str(root) and row.get("manifest_hash") == manifest_hash:
            manifest, manifest_path = row, candidate
            break
    if not manifest:
        _fail("static publication manifest is not owned or has changed")
    article_path = Path(str(manifest.get("article_path") or ""))
    try:
        article_path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise StaticPublishError("static publication manifest path is invalid") from exc
    _assert_no_symlink(article_path, PUBLICATION_ROOT.resolve(strict=False))
    if not article_path.is_file() or hashlib.sha256(article_path.read_bytes()).hexdigest() != manifest_hash:
        _fail("static publication bytes no longer match the manifest")
    archive = _receipt_root() / "archive" / str(manifest.get("brand_id")) / f"{manifest.get('content_id')}-{manifest_hash}.html"
    _write_atomic(archive, article_path.read_text(encoding="utf-8"))
    article_path.unlink()
    if manifest_path and manifest_path.exists():
        manifest_path.unlink()
    _refresh_indexes(root, base_url, str(manifest.get("brand_id")))
    return {"ok": True, "manifest_hash": manifest_hash, "archived_path": str(archive)}


def rollback(destination: dict, manifest_hash: str) -> dict:
    root_value = destination.get("output_root") if isinstance(destination, dict) else None
    brand_id = Path(str(root_value)).name if root_value else ""
    if not _ID.fullmatch(str(brand_id)):
        _fail("static output_root must be brand-scoped")
    with _brand_lock(str(brand_id)):
        return _rollback_unlocked(destination, manifest_hash)

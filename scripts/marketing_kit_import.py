"""Import a supplied historical marketing kit into reviewable brand drafts.

The importer is deliberately local and draft only. It reads a bounded operator
manifest under the linked project root, copies allowlisted files into owned
brand artifacts, and never publishes, sends, or treats historical claims as
approved current facts.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable

import psycopg2.extras
import marketing_studio


ARTIFACT_ROOT = Path("/home/agency/.local/share/agency-marketing/brands")
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".mp4", ".zip", ".pdf", ".txt", ".json"}
MAX_FILE_BYTES = 150 * 1024 * 1024
MAX_TOTAL_BYTES = 300 * 1024 * 1024
MAX_ITEMS = 200
MAX_FILES_PER_ITEM = 50
_SECRET_NAME = re.compile(r"(?:secret|token|password|credential|private[_-]?key|\.env)", re.I)
_HTML_JS = re.compile(r"<\s*/?\s*(?:html|script|iframe|object|embed)|javascript\s*:", re.I)
_SECRET_CONTENT = re.compile(r"(?:BEGIN\s+(?:RSA|EC|OPENSSH)?\s*PRIVATE\s+KEY|(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=])", re.I)


class MarketingKitImportError(ValueError):
    pass


def _reject_symlink_ancestors(path: Path, stop: Path) -> None:
    current = path
    stop = stop.absolute()
    while True:
        if current.exists() and current.is_symlink():
            raise MarketingKitImportError("symlink paths are not allowed")
        if current == stop or current.parent == current:
            return
        current = current.parent


def _under(root: Path, candidate: Path, *, must_exist=False) -> Path:
    root = root.absolute()
    candidate = candidate if candidate.is_absolute() else root / candidate
    _reject_symlink_ancestors(candidate, root)
    normalized = candidate.resolve(strict=must_exist)
    try:
        normalized.relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise MarketingKitImportError("path escaped the linked project root") from exc
    if must_exist and not normalized.exists():
        raise MarketingKitImportError("source path is unavailable")
    return normalized


def _safe_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise MarketingKitImportError(f"{field} is invalid")
    if any(ord(char) < 32 and char not in "\n\t" for char in value) or _HTML_JS.search(value):
        raise MarketingKitImportError(f"{field} contains unsafe markup")
    return value.strip()


def _clean_brief(value: Any, depth=0) -> Any:
    if depth > 4:
        raise MarketingKitImportError("brief is too deeply nested")
    if isinstance(value, dict):
        if len(value) > 40:
            raise MarketingKitImportError("brief has too many fields")
        clean = {}
        for key, item in value.items():
            key = _safe_text(key, "brief key", 80)
            if _SECRET_NAME.search(key):
                raise MarketingKitImportError("brief contains a credential-like field")
            if key.lower() in {"approved", "publish", "send", "recipients"}:
                continue
            clean[key] = _clean_brief(item, depth + 1)
        return clean
    if isinstance(value, list):
        if len(value) > 100:
            raise MarketingKitImportError("brief list is too large")
        return [_clean_brief(item, depth + 1) for item in value]
    if isinstance(value, str):
        if len(value) > 10000 or _HTML_JS.search(value):
            raise MarketingKitImportError("brief contains unsafe or oversized text")
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    raise MarketingKitImportError("brief contains unsupported data")


def _load_manifest(source_dir: Path, manifest_path: str) -> tuple[dict, str, Path]:
    manifest = Path(manifest_path)
    if not manifest.is_absolute():
        manifest = source_dir / manifest
    manifest = _under(source_dir, manifest, must_exist=True)
    if not manifest.is_file():
        raise MarketingKitImportError("manifest file is unavailable")
    if manifest.name.startswith(".") or _SECRET_NAME.search(manifest.name):
        raise MarketingKitImportError("manifest filename is not allowed")
    if manifest.stat().st_size > 5 * 1024 * 1024:
        raise MarketingKitImportError("manifest is too large")
    raw = manifest.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketingKitImportError("manifest must be UTF-8 JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise MarketingKitImportError("manifest items are required")
    return payload, digest, manifest


def _validate_item(raw: Any, index: int, brand_id: int) -> dict:
    if not isinstance(raw, dict):
        raise MarketingKitImportError(f"item {index} is invalid")
    kind = _safe_text(raw.get("kind"), f"item {index} kind", 40)
    channel = _safe_text(raw.get("channel"), f"item {index} channel", 40)
    allowed = {"strategy", "social_post", "email_campaign", "video_brief", "channel_setup"}
    channels = {"website", "blog", "help", "instagram", "youtube", "linkedin", "facebook", "x", "email"}
    if kind not in allowed or channel not in channels:
        raise MarketingKitImportError(f"item {index} type is unsupported")
    title = _safe_text(raw.get("title"), f"item {index} title", 240)
    body = raw.get("body", "")
    if not isinstance(body, str) or len(body) > 50000 or _HTML_JS.search(body):
        raise MarketingKitImportError(f"item {index} body is invalid")
    files = raw.get("files", [])
    if not isinstance(files, list) or len(files) > MAX_FILES_PER_ITEM:
        raise MarketingKitImportError(f"item {index} files are invalid")
    clean_files = []
    for value in files:
        if not isinstance(value, str) or not value or len(value) > 500:
            raise MarketingKitImportError(f"item {index} file path is invalid")
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or any(part.startswith(".") for part in path.parts):
            raise MarketingKitImportError(f"item {index} file path escaped the source package")
        if _SECRET_NAME.search(path.name) or path.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise MarketingKitImportError(f"item {index} file type is not allowed")
        clean_files.append(value)
    brief = _clean_brief(raw.get("brief", {}))
    if not isinstance(brief, dict):
        raise MarketingKitImportError(f"item {index} brief must be an object")
    item = {"brand_id": brand_id, "kind": kind, "channel": channel, "title": title,
            "body": body, "brief": brief, "files": clean_files, "state": "draft", "revision": 1}
    try:
        marketing_studio.validate_work_item(item)
    except (TypeError, ValueError) as exc:
        raise MarketingKitImportError(f"item {index} failed marketing validation") from exc
    return {key: item[key] for key in ("kind", "channel", "title", "body", "brief", "files")}


def _mime(path: Path) -> str:
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".mp4": "video/mp4", ".zip": "application/zip", ".pdf": "application/pdf",
            ".txt": "text/plain", ".json": "application/json"}.get(path.suffix.lower(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")


def _validate_text_attachment(path: Path) -> None:
    if path.suffix.lower() not in {".txt", ".json"}:
        return
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(65536):
                text = chunk.decode("utf-8", errors="ignore")
                if _HTML_JS.search(text) or _SECRET_CONTENT.search(text):
                    raise MarketingKitImportError("text attachment contains unsafe markup or secret material")
    except OSError as exc:
            raise MarketingKitImportError("source attachment is unreadable") from exc


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _result(*, digest: str, item_ids: list[int], idempotent: bool) -> dict:
    content = {"item_ids": item_ids, "manifest_sha256": digest, "idempotent": idempotent,
               "published": False, "sent": False}
    return {"ok": True, **content, "content": json.dumps(content, separators=(",", ":"))}


def handle(task: dict, get_conn: Callable = None) -> dict:
    """Import one operator package, returning draft ids and no publication action."""
    params = task.get("params") or {}
    try:
        brand_id = int(params["brand_id"])
        source_dir_input = params["source_dir"]
        manifest_input = params["manifest_path"]
        if brand_id < 1 or not isinstance(source_dir_input, str) or not isinstance(manifest_input, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "brand_id, source_dir and manifest_path are required"}
    get_conn = get_conn or _default_get_conn
    conn = get_conn()
    created_roots: list[Path] = []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT b.id,b.project_id,p.local_path,p.lifecycle FROM brands b JOIN projects p ON p.id=b.project_id WHERE b.id=%s FOR UPDATE OF b", (brand_id,))
        brand = cur.fetchone()
        if not brand or brand.get("lifecycle") != "active" or not brand.get("local_path"):
            return {"ok": False, "error": "brand ledger is missing or not active"}
        root = Path(str(brand["local_path"]))
        if not root.is_absolute():
            return {"ok": False, "error": "linked project root is invalid"}
        source_dir = _under(root, Path(source_dir_input), must_exist=True)
        if not source_dir.is_dir():
            return {"ok": False, "error": "source directory is unavailable"}
        manifest, digest, manifest_path = _load_manifest(source_dir, manifest_input)
        items = manifest["items"]
        if len(items) > MAX_ITEMS:
            raise MarketingKitImportError("manifest has too many items")
        clean_items = [_validate_item(item, index, brand_id) for index, item in enumerate(items)]
        total_bytes = 0
        for item in clean_items:
            for relative in item["files"]:
                source = _under(source_dir, Path(relative), must_exist=True)
                if source.is_symlink() or not source.is_file():
                    raise MarketingKitImportError("source files must be regular non-symlink files")
                _validate_text_attachment(source)
                size = source.stat().st_size
                if size > MAX_FILE_BYTES:
                    raise MarketingKitImportError("source file exceeds 150MB")
                total_bytes += size
                if total_bytes > MAX_TOTAL_BYTES:
                    raise MarketingKitImportError("source package exceeds 300MB")
        cur.execute("SELECT id FROM marketing_work_items WHERE brand_id=%s AND brief->>'source_manifest_sha256'=%s ORDER BY id", (brand_id, digest))
        existing = cur.fetchall()
        if existing:
            return _result(digest=digest, item_ids=[int(row["id"]) for row in existing], idempotent=True)
        item_ids = []
        task_id = task.get("id")
        if isinstance(task_id, str) and task_id.isdigit():
            task_id = int(task_id)
        if not isinstance(task_id, int) or task_id <= 0:
            task_id = None
        for index, item in enumerate(clean_items):
            brief = dict(item["brief"])
            brief.update({"source_manifest_sha256": digest, "source_manifest_path": str(manifest_path),
                          "source_session_id": str(manifest.get("session_id") or "")[:200],
                          "source_item_index": index, "source_provenance": "operator supplied historical marketing kit",
                          "needs_review": True, "current_offer": False, "approved": False})
            cur.execute("INSERT INTO marketing_work_items (brand_id,kind,channel,title,brief,body,state,revision,task_id) VALUES (%s,%s,%s,%s,%s,%s,'draft',1,%s) RETURNING id",
                        (brand_id, item["kind"], item["channel"], item["title"], json.dumps(brief), item["body"], task_id))
            row = cur.fetchone()
            if not row or not row.get("id"):
                raise MarketingKitImportError("draft row was not created")
            item_id = int(row["id"])
            item_ids.append(item_id)
            target = ARTIFACT_ROOT / str(brand_id) / "work" / str(item_id) / "imported"
            _reject_symlink_ancestors(target, ARTIFACT_ROOT)
            if target.exists():
                raise MarketingKitImportError("artifact destination already exists")
            target.mkdir(parents=True, exist_ok=False)
            created_roots.append(target)
            outputs = []
            for relative in item["files"]:
                source = _under(source_dir, Path(relative), must_exist=True)
                destination = target / Path(relative).name
                if destination.exists() or destination.is_symlink():
                    raise MarketingKitImportError("artifact destination conflict")
                shutil.copyfile(source, destination)
                outputs.append({"path": str(destination), "mime": _mime(destination), "sha256": _file_sha256(destination), "provenance": "historical kit import"})
            brief["media"] = {"outputs": outputs, "published": False, "sent": False}
            cur.execute("UPDATE marketing_work_items SET brief=%s,updated_at=now() WHERE id=%s AND brand_id=%s", (json.dumps(brief), item_id, brand_id))
        conn.commit()
        return _result(digest=digest, item_ids=item_ids, idempotent=False)
    except (MarketingKitImportError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        conn.rollback()
        for path in reversed(created_roots):
            shutil.rmtree(path, ignore_errors=True)
        return {"ok": False, "error": str(exc)[:240]}
    finally:
        conn.close()


def _default_get_conn():
    import worker
    return worker.get_conn()


__all__ = ["handle", "MarketingKitImportError"]

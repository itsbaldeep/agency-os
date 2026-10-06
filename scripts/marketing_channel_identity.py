"""Bounded local identity bridge for generated marketing media.

This module reads only brand-owned local manifests and image files.  It never
contacts a provider or exposes filesystem paths in returned metadata/errors.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


DEFAULT_ROOT = Path("/home/agency/.local/share/agency-marketing/brands")
MAX_WORK_ITEMS = 30
MAX_CANDIDATES = 24
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_FILENAME = 200
SAFE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MIMES = {"image/png": "PNG", "image/jpeg": "JPEG"}


def _fail() -> None:
    raise ValueError("media reference unavailable")


def _metadata_text(value: Any, default: str, limit: int) -> str:
    text = value if isinstance(value, str) else default
    if any(ord(char) < 32 or ord(char) == 127 for char in text) or "/" in text or "\\" in text:
        return default
    return text[:limit]


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _brand_root(root: Path, brand_id: int) -> Path:
    if not _positive_int(brand_id):
        _fail()
    base = Path(root)
    brand = base / str(brand_id)
    current = brand
    while True:
        if current.exists() and current.is_symlink():
            _fail()
        if current.parent == current:
            break
        current = current.parent
    try:
        brand.resolve(strict=False).relative_to(base.resolve(strict=False))
    except ValueError:
        _fail()
    return brand


def _safe_relative(path: Path, brand_root: Path) -> Path:
    if not path.is_absolute():
        _fail()
    try:
        relative = path.absolute().relative_to(brand_root.absolute())
    except ValueError:
        _fail()
    if not relative.parts or any(not SAFE_FILENAME.fullmatch(part) for part in relative.parts):
        _fail()
    return relative


def _read_owned(path: Path, brand_root: Path) -> bytes:
    relative = _safe_relative(path, brand_root)
    root_fd = file_fd = None
    directory_fds = []
    try:
        root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in brand_root.absolute().parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            os.close(root_fd)
            root_fd = next_fd
        directory_fd = root_fd
        for part in relative.parts[:-1]:
            directory_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            directory_fds.append(directory_fd)
        file_fd = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        stat = os.fstat(file_fd)
        if not (stat.st_mode & 0o170000) == 0o100000 or stat.st_size > MAX_FILE_BYTES:
            _fail()
        chunks = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(1024 * 1024, MAX_FILE_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                _fail()
        return b"".join(chunks)
    except (OSError, ValueError):
        _fail()
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if root_fd is not None:
            os.close(root_fd)
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


def _manifest(item: dict[str, Any]) -> list[dict[str, Any]]:
    brief = item.get("brief")
    media = item.get("media")
    if not isinstance(media, dict) and isinstance(brief, dict):
        media = brief.get("media")
    outputs = media.get("outputs") if isinstance(media, dict) else None
    return outputs if isinstance(outputs, list) and len(outputs) <= 100 else []


def _identity(item: Any, brand_id: int) -> tuple[int, int]:
    if not isinstance(item, dict) or not _positive_int(item.get("brand_id")) or item.get("brand_id") != brand_id:
        _fail()
    work_id = item.get("id")
    revision = item.get("revision")
    if not _positive_int(work_id) or not _positive_int(revision):
        _fail()
    return work_id, revision


def _output(item: dict[str, Any], brand_id: int, filename: str, root: Path) -> dict[str, Any]:
    brand_root = _brand_root(root, brand_id)
    matches = []
    for output in _manifest(item):
        if not isinstance(output, dict) or not isinstance(output.get("path"), str):
            continue
        path = Path(output["path"])
        if path.name == filename:
            matches.append((output, path))
    if len(matches) != 1:
        _fail()
    output, path = matches[0]
    _safe_relative(path, brand_root)
    return output


def _validate_image(output: dict[str, Any], path: Path, brand_root: Path) -> tuple[bytes, str, int, int]:
    mime = output.get("mime")
    if not isinstance(mime, str) or mime not in MIMES:
        _fail()
    data = _read_owned(path, brand_root)
    try:
        with Image.open(__import__("io").BytesIO(data)) as image:
            width, height, actual_format = image.width, image.height, image.format
            if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                _fail()
            image.verify()
        with Image.open(__import__("io").BytesIO(data)) as image:
            if image.width * image.height > MAX_PIXELS:
                _fail()
            image.load()
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError):
        _fail()
    if actual_format != MIMES[mime]:
        _fail()
    declared_sha = output.get("sha256")
    if declared_sha is not None and (not isinstance(declared_sha, str) or not SHA256.fullmatch(declared_sha)):
        _fail()
    actual_sha = hashlib.sha256(data).hexdigest()
    if declared_sha is not None and declared_sha != actual_sha:
        _fail()
    return data, mime, width, height


def candidates(items: Any, brand_id: int, root: Path | None = None) -> list[dict[str, Any]]:
    """Return at most 24 validated image identities from at most 30 work items."""
    if not isinstance(items, list) or not _positive_int(brand_id):
        return []
    try:
        brand_root = _brand_root(DEFAULT_ROOT if root is None else root, brand_id)
    except (OSError, ValueError, TypeError):
        return []
    result = []
    for item in items[:MAX_WORK_ITEMS]:
        try:
            work_id, revision = _identity(item, brand_id)
            outputs = _manifest(item)
            names = [Path(o["path"]).name for o in outputs if isinstance(o, dict) and isinstance(o.get("path"), str)]
            for output in outputs:
                try:
                    if len(result) >= MAX_CANDIDATES:
                        return result
                    if not isinstance(output, dict) or not isinstance(output.get("path"), str):
                        continue
                    filename = Path(output["path"]).name
                    if names.count(filename) != 1 or not SAFE_FILENAME.fullmatch(filename):
                        continue
                    path = Path(output["path"])
                    _safe_relative(path, brand_root)
                    data, mime, width, height = _validate_image(output, path, brand_root)
                    result.append({
                        "work_id": work_id,
                        "source_revision": revision,
                        "filename": filename,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "mime": mime,
                        "width": width,
                        "height": height,
                        "provenance": _metadata_text(output.get("provenance"), "generated media", 200),
                        "title": _metadata_text(item.get("title"), "Generated media", 240),
                    })
                except (OSError, ValueError, TypeError):
                    continue
        except (OSError, ValueError, TypeError):
            continue
    return result


def resolve_reference(item: Any, brand_id: int, ref: Any, root: Path | None = None) -> dict[str, Any]:
    """Resolve a saved ref, allowing newer item revisions only when the hash is unchanged."""
    if not isinstance(ref, dict) or set(ref) != {"work_id", "source_revision", "filename", "sha256"}:
        _fail()
    work_id, current_revision = _identity(item, brand_id)
    if not _positive_int(ref["work_id"]) or ref["work_id"] != work_id or not _positive_int(ref["source_revision"]):
        _fail()
    filename = ref["filename"]
    if not isinstance(filename, str) or not SAFE_FILENAME.fullmatch(filename) or not isinstance(ref["sha256"], str) or not SHA256.fullmatch(ref["sha256"]):
        _fail()
    if current_revision < ref["source_revision"]:
        _fail()
    effective_root = DEFAULT_ROOT if root is None else root
    output = _output(item, brand_id, filename, effective_root)
    brand_root = _brand_root(effective_root, brand_id)
    path = Path(output["path"])
    data, mime, width, height = _validate_image(output, path, brand_root)
    actual_sha = hashlib.sha256(data).hexdigest()
    if actual_sha != ref["sha256"]:
        _fail()
    return {
        "metadata": {
            "work_id": work_id,
            "source_revision": ref["source_revision"],
            "filename": filename,
            "sha256": actual_sha,
            "mime": mime,
            "width": width,
            "height": height,
            "provenance": _metadata_text(output.get("provenance"), "generated media", 200),
            "title": _metadata_text(item.get("title"), "Generated media", 240),
        },
        "image_bytes": data,
    }

"""Bounded, immutable editorial asset primitives.

This module intentionally has no database dependency.  The dashboard owns the
asset registry and review workflow; this module owns safe bytes-in/object-bytes-
out operations and provider import metadata.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import urllib.parse
import urllib.error
import urllib.request
from typing import Any
import public_fetch

MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 20_000_000
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}
PEXELS_API = "https://api.pexels.com/v1"
_PEXELS_HOSTS = {"api.pexels.com", "www.pexels.com", "pexels.com"}
_PEXELS_IMAGE_HOSTS = {"images.pexels.com"}


def _asset_config() -> tuple[str, str, str, str, str]:
    endpoint = os.environ.get("AGENCY_S3_ENDPOINT", "100.64.0.1:9010")
    access = os.environ.get("AGENCY_S3_ACCESS_KEY") or os.environ.get("MINIO_ROOT_USER", "")
    secret = os.environ.get("AGENCY_S3_SECRET_KEY") or os.environ.get("MINIO_ROOT_PASSWORD", "")
    bucket = os.environ.get("AGENCY_S3_BUCKET", "agency-editorial")
    public = os.environ.get("AGENCY_S3_PUBLIC_BASE", "https://assets.apps.deployden.tech")
    return endpoint, access, secret, bucket, public.rstrip("/")


def _client(endpoint: str, access: str, secret: str):
    from minio import Minio
    secure = endpoint.startswith("https://")
    endpoint = endpoint.removeprefix("https://").removeprefix("http://")
    return Minio(endpoint, access_key=access, secret_key=secret, secure=secure)


def _mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    # WebP is RIFF + WEBP.  Do not accept arbitrary RIFF containers.
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("asset must be a PNG, JPEG, or WebP image")


def _dimensions(data: bytes) -> tuple[int | None, int | None]:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            if int(image.width) * int(image.height) > MAX_PIXELS:
                raise ValueError("asset exceeds the pixel limit")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except ImportError:
        raise ValueError("Pillow is required for safe image validation")
    except Exception as exc:
        raise ValueError("asset is not a valid decodable image") from exc


def _sanitize(data: bytes) -> bytes:
    """Decode and re-encode to strip EXIF/metadata and bound decompression."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("Pillow is required for safe image validation") from exc
    mime = _mime(data)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if int(image.width) * int(image.height) > MAX_PIXELS:
                raise ValueError("asset exceeds the pixel limit")
            image.load()
            if mime == "image/jpeg":
                image = image.convert("RGB")
                fmt, options = "JPEG", {"quality": 90, "optimize": True}
            elif mime == "image/png":
                if image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                    image = image.convert("RGBA")
                fmt, options = "PNG", {"optimize": True}
            else:
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA")
                fmt, options = "WEBP", {"quality": 90, "method": 4}
            out = io.BytesIO()
            image.save(out, format=fmt, **options)
            clean = out.getvalue()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("asset is not a valid decodable image") from exc
    if len(clean) > MAX_BYTES:
        raise ValueError("sanitized asset exceeds the 12 MB limit")
    return clean


def suggest_alt(description: str, source_alt: str = "") -> str:
    """Create a conservative, editable alt suggestion without an LLM."""
    value = (description or source_alt or "Editorial illustration").strip()
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:180] or "Editorial illustration"


def _metadata(data: bytes, description: str, provenance: dict[str, Any], *, source_alt: str = "") -> dict[str, Any]:
    if not isinstance(provenance, dict) or not provenance:
        raise ValueError("provenance is required")
    if len(data) > MAX_BYTES:
        raise ValueError("asset exceeds the 12 MB limit")
    mime = _mime(data)
    width, height = _dimensions(data)
    digest = hashlib.sha256(data).hexdigest()
    return {
        "id": digest,
        "sha256": digest,
        "object_key": f"editorial/{digest[:2]}/{digest}.{mime.split('/')[-1].replace('jpeg', 'jpg')}",
        "mime": mime,
        "size": len(data),
        "width": width,
        "height": height,
        "alt": suggest_alt(description, source_alt),
        "alt_suggestion": suggest_alt(description, source_alt),
        "provenance": provenance,
    }


def store_asset(data: bytes, description: str, provenance: dict[str, Any]) -> dict[str, Any]:
    """Validate and immutably store an owned editorial image in core MinIO."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("asset bytes are required")
    data = _sanitize(bytes(data))
    metadata = _metadata(data, description, provenance)
    endpoint, access, secret, bucket, public = _asset_config()
    client = _client(endpoint, access, secret)
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    client.put_object(bucket, metadata["object_key"], io.BytesIO(data), len(data), content_type=metadata["mime"], metadata={"sha256": metadata["sha256"]})
    metadata["url"] = f"{public}/{bucket}/{metadata['object_key']}"
    read_core_asset(metadata)
    verify_public_asset(metadata['url'], metadata['sha256'])
    return metadata


def _safe_url(value: str, hosts: set[str]) -> str:
    parsed = urllib.parse.urlsplit(str(value or ""))
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port or parsed.hostname not in hosts:
        raise ValueError("provider returned an unsafe asset URL")
    return value


def _request(url: str, *, headers: dict[str, str] | None = None, max_bytes: int = 2_000_000, allowed_hosts: set[str] | None = None) -> tuple[int, bytes, str, str]:
    """Fetch with redirects disabled by policy and host checked every hop."""
    current = url
    for _ in range(4):
        if allowed_hosts is not None:
            _safe_url(current, allowed_hosts)
        target = public_fetch._validate_target(current)
        if allowed_hosts is not None and target.host not in allowed_hosts:
            raise ValueError("provider redirect host is not allowed")
        connection_type = (public_fetch._PinnedHTTPSConnection
                           if target.parsed.scheme == "https" else public_fetch._PinnedHTTPConnection)
        connection = connection_type(target.host, target.port, 20, target.family, target.address)
        try:
            connection.request("GET", target.request_target, headers={"User-Agent": "AgencyOS asset importer/1.0", "Accept": "image/*,application/json", **(headers or {})})
            response = connection.getresponse()
            body = response.read(max_bytes + 1)
            status = int(response.status)
            content_type = response.getheader("Content-Type", "")
            connection.close()
            if len(body) > max_bytes:
                raise ValueError("provider response exceeds limit")
            if status not in (301, 302, 303, 307, 308):
                return status, body, current, content_type
            location = response.getheader("Location")
            if not location:
                raise ValueError("provider redirect has no location")
            current = urllib.parse.urljoin(current, location)
        except (OSError, public_fetch.PublicFetchError) as exc:
            connection.close()
            raise ValueError("provider request failed") from exc
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise
            location = exc.headers.get("Location")
            if not location:
                raise ValueError("provider redirect has no location")
            current = urllib.parse.urljoin(current, location)
    raise ValueError("provider redirect limit exceeded")


def search_assets(query: str) -> list[dict[str, Any]]:
    key = os.environ.get("PEXELS_API_KEY", "")
    query = str(query or "").strip()
    if not key or not query:
        return []
    url = f"{PEXELS_API}/search?{urllib.parse.urlencode({'query': query, 'per_page': 12, 'orientation': 'landscape'})}"
    _safe_url(url, _PEXELS_HOSTS)
    status, body, _, _ = _request(url, headers={"Authorization": key, "User-Agent": "AgencyOS asset importer/1.0"}, max_bytes=1_000_000, allowed_hosts=_PEXELS_HOSTS)
    if status >= 400:
        return []
    result = json.loads(body)
    records = []
    for photo in result.get("photos", []):
        src = photo.get("src") or {}
        thumb = src.get("medium") or src.get("small")
        if not thumb:
            continue
        records.append({"provider": "pexels", "provider_id": str(photo.get("id")), "thumbnail_url": _safe_url(thumb, _PEXELS_IMAGE_HOSTS), "photographer": photo.get("photographer") or "", "source_url": _safe_url(photo.get("url"), _PEXELS_HOSTS), "license_url": "https://www.pexels.com/license/", "alt": photo.get("alt") or query})
    return records


def import_stock(provider_id: str, description: str = "") -> dict[str, Any]:
    """Resolve a Pexels ID server-side, then import its provider-selected image."""
    key = os.environ.get("PEXELS_API_KEY", "")
    if not key or not str(provider_id).isdigit():
        raise ValueError("a valid Pexels provider ID and configured provider are required")
    api_url = f"{PEXELS_API}/photos/{int(provider_id)}"
    status, body, _, _ = _request(_safe_url(api_url, _PEXELS_HOSTS), headers={"Authorization": key, "User-Agent": "AgencyOS asset importer/1.0"}, max_bytes=1_000_000, allowed_hosts=_PEXELS_HOSTS)
    if status >= 400:
        raise ValueError("provider asset was not found")
    photo = json.loads(body)
    src = photo.get("src") or {}
    original = _safe_url(src.get("original") or src.get("large2x") or "", _PEXELS_IMAGE_HOSTS)
    status, data, final_url, content_type = _request(original, max_bytes=MAX_BYTES, allowed_hosts=_PEXELS_IMAGE_HOSTS)
    if status >= 400 or not data:
        raise ValueError("provider asset download failed")
    provenance = {"provider": "pexels", "provider_id": str(photo.get("id")), "source_url": _safe_url(photo.get("url"), _PEXELS_HOSTS), "license_url": "https://www.pexels.com/license/", "photographer": photo.get("photographer") or "", "download_url": final_url}
    return store_asset(data, description or photo.get("alt") or "Editorial illustration", provenance)


def public_readback(data: bytes, expected_sha256: str) -> bool:
    """Pure hash check for callers after public/object-storage readback."""
    return hashlib.sha256(data).hexdigest() == str(expected_sha256 or "").lower()


def read_core_asset(metadata: dict[str, Any]) -> bytes:
    """Read a managed core object and verify its immutable key/hash."""
    digest = str(metadata.get("sha256") or "")
    key = str(metadata.get("object_key") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or not re.fullmatch(r"editorial/[0-9a-f]{2}/[0-9a-f]{64}\.(?:png|jpg|webp)", key):
        raise ValueError("managed asset metadata is invalid")
    endpoint, access, secret, bucket, _ = _asset_config()
    client = _client(endpoint, access, secret)
    response = client.get_object(bucket, key)
    try:
        data = response.read(MAX_BYTES + 1)
    finally:
        response.close()
        response.release_conn()
    if len(data) > MAX_BYTES or not public_readback(data, digest):
        raise ValueError("core asset readback hash mismatch")
    return data


def _storage_from_project(project_root: str, env_name: str) -> dict[str, str]:
    root = os.path.realpath(project_root)
    env_path = os.path.realpath(os.path.join(root, env_name))
    if not env_path.startswith(root + os.sep) or not os.path.isfile(env_path):
        raise ValueError("engagement environment must be a project-relative file")
    values: dict[str, str] = {}
    for line in open(env_path, encoding="utf-8"):
        match = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return {"endpoint": values.get("PUBLIC_MEDIA_ENDPOINT", ""), "access_key": values.get("PUBLIC_MEDIA_ACCESS_KEY", ""), "secret_key": values.get("PUBLIC_MEDIA_SECRET_KEY", ""), "bucket": values.get("PUBLIC_MEDIA_BUCKET", ""), "public_base": values.get("PUBLIC_MEDIA_BASE", "")}


def copy_to_engagement(metadata: dict[str, Any], data: bytes, storage: dict[str, Any] | str, env_name: str = ".env") -> dict[str, Any]:
    """Copy an approved asset to a separately configured public-media bucket.

    ``storage`` is either an explicit destination mapping or a project root.
    The latter reads only generic PUBLIC_MEDIA_* names from a project-relative
    env file, keeping this primitive project-agnostic.
    """
    if isinstance(storage, str):
        values = _storage_from_project(storage, env_name)
    elif isinstance(storage, dict):
        root = storage.get("project_root")
        env_file = str(storage.get("env_file") or ".env")
        if not isinstance(root, str):
            raise ValueError("asset_storage.project_root is required")
        env_values = _storage_from_project(root, env_file)
        access_ref = str(storage.get("access_key_ref") or "")
        secret_ref = str(storage.get("secret_key_ref") or "")
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", access_ref) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", secret_ref):
            raise ValueError("asset storage credential references are required")
        # Read refs from the same project-relative environment, never from the
        # dashboard payload.
        raw: dict[str, str] = {}
        path = os.path.realpath(os.path.join(os.path.realpath(root), env_file))
        for line in open(path, encoding="utf-8"):
            match = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
            if match: raw[match.group(1)] = match.group(2).strip().strip('"').strip("'")
        values = {"endpoint": storage.get("endpoint"), "bucket": storage.get("bucket"), "public_base": storage.get("public_base"), "access_key": raw.get(access_ref), "secret_key": raw.get(secret_ref)}
    else:
        values = {}
    endpoint = str(values.get("endpoint") or "")
    access = str(values.get("access_key") or "")
    secret = str(values.get("secret_key") or "")
    bucket = str(values.get("bucket") or "")
    public = str(values.get("public_base") or "").rstrip("/")
    if not all((endpoint, access, secret, bucket, public)):
        raise ValueError("dedicated public-media storage configuration is incomplete")
    digest = str(metadata.get("sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or not public.startswith("https://"):
        raise ValueError("asset metadata is invalid")
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("asset bytes do not match immutable metadata hash")
    client = _client(endpoint, access, secret)
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    key = f"editorial/{digest[:2]}/{digest}.{str(metadata.get('mime', '')).split('/')[-1].replace('jpeg', 'jpg')}"
    client.put_object(bucket, key, io.BytesIO(data), len(data), content_type=metadata["mime"], metadata={"sha256": digest, "classification": "public-editorial"})
    response = client.get_object(bucket, key)
    try:
        readback = response.read()
    finally:
        response.close()
        response.release_conn()
    if not public_readback(readback, digest):
        raise ValueError("engagement asset readback hash mismatch")
    url = f"{public}/{bucket}/{key}"
    verify_public_asset(url, digest)
    return {**metadata, "object_key": key, "url": url}


def verify_public_asset(url, digest):
    """Read an asset over public HTTPS without the research fetcher's 300 KB cap."""
    host = urllib.parse.urlsplit(url).hostname
    try:
        status, data, _, _ = _request(url, max_bytes=MAX_BYTES, allowed_hosts={host})
    except Exception as exc:
        raise ValueError('Public asset URL could not be verified') from exc
    if status != 200 or not public_readback(data, digest):
        raise ValueError('Public asset URL readback hash mismatch')

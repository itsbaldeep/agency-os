"""Read-only, brand-scoped Brevo account verification."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import urllib.error
import urllib.request
from datetime import UTC, datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Callable

import psycopg2.extras

CORE_CREDENTIAL_ROOT = Path("/home/agency/.config/agency")
ENGAGEMENT_ROOT = Path("/home/agency/engagements")
BREVO_ACCOUNT_URL = "https://api.brevo.com/v3/account"
BREVO_SENDERS_URL = "https://api.brevo.com/v3/senders"
MAX_CONFIG_PATH = 500
MAX_CREDENTIAL_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 128 * 1024


def _email(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 254 or "\n" in value or "\r" in value:
        raise ValueError("sender_email must be a bounded email address")
    name, address = parseaddr(value)
    if name or address != value or "@" not in address or address.startswith("@") or address.endswith("@"):
        raise ValueError("sender_email must be a public sender email")
    local, domain = address.rsplit("@", 1)
    if not local or not domain or ":" in address or "/" in address or "\\" in address:
        raise ValueError("sender_email must be a public sender email")
    if len(local) > 64 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", address):
        raise ValueError('sender_email must be a public sender email')
    return address


def _validate_reference(ref, name):
    """Validate a named file reference without reading any credential."""
    if not isinstance(ref, str) or not ref or len(ref) > MAX_CONFIG_PATH or not os.path.isabs(ref) or any(c in ref for c in ('\x00', '\r', '\n')) or '..' in Path(ref).parts:
        raise ValueError("credential_ref must be an absolute bounded path")
    if not isinstance(name, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', name):
        raise ValueError("credential_name must be an uppercase environment name")
    return ref, name


def validate_config(payload: dict[str, Any]) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) != {"provider", "credential_ref", "credential_name", "sender_email"}:
        raise ValueError("Brevo configuration fields are incomplete or unsupported")
    if payload.get("provider") != "brevo":
        raise ValueError("provider must be brevo")
    ref, name = _validate_reference(payload.get('credential_ref'), payload.get('credential_name'))
    return {"provider": "brevo", "credential_ref": ref, "credential_name": name,
            "sender_email": _email(payload.get("sender_email"))}


def config_digest(config: dict[str, Any]) -> str:
    if config == {}:
        return hashlib.sha256(b"{}").hexdigest()
    normalized = validate_config(config)
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _safe_root(project: dict[str, Any]) -> Path:
    classification = project.get("classification")
    if classification == "core":
        return CORE_CREDENTIAL_ROOT
    if classification == "engagement":
        local = project.get("local_path")
        if not isinstance(local, str) or not os.path.isabs(local) or '..' in Path(local).parts:
            raise ValueError("engagement credential root unavailable")
        root = Path(local)
        try:
            root.relative_to(ENGAGEMENT_ROOT)
        except ValueError as exc:
            raise ValueError("engagement credential root is outside Agency storage") from exc
        return root
    raise ValueError("credential classification is unsupported")


def read_credential(config: dict[str, Any], project: dict[str, Any]) -> str:
    config = validate_config(config)
    return read_owned_reference(config['credential_ref'], config['credential_name'], project)


def read_owned_reference(credential_ref: str, credential_name: str, project: dict[str, Any]) -> str:
    """Read one named credential from its authoritative owning ledger root."""
    credential_ref, credential_name = _validate_reference(credential_ref, credential_name)
    root = _safe_root(project)
    try:
        if root.is_symlink() or not root.is_dir():
            raise ValueError("credential root unavailable")
        path = Path(credential_ref)
        path.relative_to(root)
        relative = path.relative_to(root)
        if not relative.parts:
            raise ValueError('credential reference must name a file')
    except (OSError, ValueError) as exc:
        raise ValueError("credential reference is outside the owned root") from exc
    flags_dir = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    flags_file = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK
    fds: list[int] = []
    try:
        current = os.open('/', flags_dir)
        fds.append(current)
        for part in root.parts[1:]:
            current = os.open(part, flags_dir, dir_fd=current)
            fds.append(current)
        for part in relative.parts[:-1]:
            current = os.open(part, flags_dir, dir_fd=current)
            fds.append(current)
        fd = os.open(relative.parts[-1], flags_file, dir_fd=current)
        fds.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("credential file permissions are unsafe")
        if info.st_size > MAX_CREDENTIAL_BYTES:
            raise ValueError("credential file is too large")
        with os.fdopen(fd, "rb") as handle:
            fds.pop()
            raw = handle.read(MAX_CREDENTIAL_BYTES + 1)
        if len(raw) > MAX_CREDENTIAL_BYTES:
            raise ValueError("credential file is too large")
        text = raw.decode("utf-8")
        for line in text.splitlines():
            if line.startswith(credential_name + "="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value and len(value) <= 4096 and all(32 < ord(char) < 127 for char in value):
                    return value
        raise ValueError("named credential is unavailable")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("credential file is unavailable") from exc
    finally:
        for fd in reversed(fds):
            try:
                os.close(fd)
            except OSError:
                pass


def _read_json(response: Any) -> dict[str, Any]:
    status = int(getattr(response, "status", 200))
    if status < 200 or status >= 300:
        raise ValueError(f"http_{status}")
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("response_too_large")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid_json")
    return value


def verify(config: dict[str, Any], project: dict[str, Any], opener: Callable[..., Any] | None = None) -> dict[str, Any]:
    checked_at = datetime.now(UTC).isoformat()
    try:
        config = validate_config(config)
        api_key = read_credential(config, project)
        if opener is None:
            class _NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, request, fp, code, msg, headers, newurl):
                    raise ValueError("redirect_rejected")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open
        headers = {"accept": "application/json", "api-key": api_key}
        account_request = urllib.request.Request(BREVO_ACCOUNT_URL, headers=headers, method="GET")
        with opener(account_request, timeout=15) as response:
            account = _read_json(response)
        if not ((type(account.get("user_id")) is int and account["user_id"] > 0)
                or (isinstance(account.get("organization_id"), str) and account["organization_id"].strip())):
            raise ValueError("invalid_account")
        if not isinstance(account.get("plan"), list):
            raise ValueError("invalid_account")
        senders_request = urllib.request.Request(BREVO_SENDERS_URL, headers=headers, method="GET")
        with opener(senders_request, timeout=15) as response:
            senders = _read_json(response)
        rows = senders.get("senders")
        if not isinstance(rows, list):
            raise ValueError("invalid_senders")
        sender_verified = any(isinstance(row, dict) and row.get("email") == config["sender_email"] and row.get("active") is True for row in rows)
        return {"authenticated": True, "sender_verified": sender_verified, "checked_at": checked_at,
                "status": "verified" if sender_verified else "sender_unverified",
                "error": None if sender_verified else "sender_not_active"}
    except urllib.error.HTTPError as exc:
        return {"authenticated": False, "sender_verified": False, "checked_at": checked_at, "status": "source_unavailable", "error": f"http_{exc.code}"}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"authenticated": False, "sender_verified": False, "checked_at": checked_at, "status": "source_unavailable", "error": "network_error"}
    except (ValueError, UnicodeDecodeError, KeyError, TypeError):
        return {"authenticated": False, "sender_verified": False, "checked_at": checked_at, "status": "source_unavailable", "error": "verification_failed"}


def handle(task: dict[str, Any], get_conn: Callable[[], Any]) -> dict[str, Any]:
    params = task.get("params") if isinstance(task, dict) else {}
    params = params if isinstance(params, dict) else {}
    brand_id = params.get("brand_id")
    expected = params.get("config_digest")
    if isinstance(brand_id, bool) or not isinstance(brand_id, int) or brand_id <= 0 or not isinstance(expected, str):
        return {"ok": False, "error": "provider verification parameters are invalid"}
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT b.id,b.project_id,p.local_path,p.classification,p.lifecycle,bp.value FROM brands b LEFT JOIN projects p ON p.id=b.project_id LEFT JOIN brand_properties bp ON bp.brand_id=b.id AND bp.property_type='email_provider_config' WHERE b.id=%s FOR UPDATE OF b", (brand_id,))
        row = cur.fetchone()
        if not row or row.get("lifecycle") != 'active' or row.get('classification') not in ('core', 'engagement'):
            return {"ok": False, "error": "brand is unavailable"}
        config = row.get("value")
        if isinstance(config, str):
            config = json.loads(config)
        if config_digest(config) != expected:
            return {"ok": False, "error": "provider configuration changed; review it again"}
        result = verify(config, row)
        stored = {**result, "config_digest": expected}
        cur.execute("INSERT INTO brand_properties (brand_id,property_type,value,accessible) VALUES (%s,'email_provider_verification',%s,%s) ON CONFLICT (brand_id,property_type) DO UPDATE SET value=EXCLUDED.value,accessible=EXCLUDED.accessible,created_at=now()", (brand_id, json.dumps(stored, sort_keys=True), bool(result["authenticated"] and result["sender_verified"])))
        conn.commit()
        return {"ok": True, "content": json.dumps(stored, sort_keys=True), "verification": stored, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0}
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return {"ok": False, "error": "provider verification could not be completed"}
    finally:
        conn.close()

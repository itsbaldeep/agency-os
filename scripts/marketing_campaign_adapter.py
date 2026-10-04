"""Pure contract and localhost transport for brand-owned campaign adapters.

The source system remains responsible for recipients, consent, suppression, and
provider delivery.  This module carries only frozen, digest-bound campaign
metadata across the core/source boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlsplit

import marketing_campaigns
import marketing_studio

MAX_RESPONSE_BYTES = 128 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
_IDEMPOTENCY = re.compile(r"^[0-9a-f]{64}$")
_PATHS = {"preview": "/marketing/campaigns/preview", "dispatch": "/marketing/campaigns/dispatch", "receipt": "/marketing/campaigns/receipt"}


def _fail(code: str) -> None:
    raise ValueError(code)


def _aware(value: Any, name: str, *, now: datetime | None = None) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            value = None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _fail(f"invalid_{name}")
    value = value.astimezone(UTC)
    if now is not None and value > now:
        _fail(f"invalid_{name}")
    return value


def _id(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(f"invalid_{name}")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        _fail(f"invalid_{name}")
    return value


def _message_fields(item: dict[str, Any]) -> dict[str, str]:
    item = marketing_studio.validate_work_item(item)
    brief = item["brief"]
    subject = brief.get("subject", "") if isinstance(brief, dict) else ""
    if not subject and item["kind"] == "email_campaign":
        first = item["body"].splitlines()[0] if item["body"] else ""
        subject = first[8:].strip() if first.lower().startswith("subject:") else ""
    if not subject:
        _fail('campaign_subject_required')
    subject = marketing_campaigns.validate_subject(subject)
    body = marketing_campaigns.validate_copy(item["body"])
    if not body.strip():
        _fail('campaign_copy_required')
    return {"title": item["title"], "subject": subject, "body": body}


def _message_digest(item: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(_message_fields(item), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _policy(item: dict[str, Any]) -> dict[str, Any]:
    brief = item.get("brief")
    policy = brief.get("campaign_policy") if isinstance(brief, dict) else None
    if not isinstance(policy, dict):
        _fail("campaign_policy_required")
    return marketing_campaigns.validate_policy(policy)


def _policy_digest(policy: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(marketing_campaigns.validate_policy(policy), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_config(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "base_url", "credential_ref", "credential_name"}:
        _fail("invalid_adapter_config")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        _fail("invalid_schema_version")
    base = payload["base_url"]
    if not isinstance(base, str) or len(base) > 200 or "\n" in base or "\r" in base:
        _fail("invalid_base_url")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or not parsed.port:
        _fail("invalid_base_url")
    ref = payload["credential_ref"]
    if not isinstance(ref, str) or not ref.startswith("/") or len(ref) > 500 or "\x00" in ref or "\n" in ref or "\r" in ref or ".." in ref.split("/"):
        _fail("invalid_credential_ref")
    name = payload["credential_name"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", name):
        _fail("invalid_credential_name")
    return {"schema_version": 1, "base_url": base.rstrip("/"), "credential_ref": ref, "credential_name": name}


def _validate_preview(value: Any, now: datetime) -> dict[str, Any]:
    allowed = {"schema_version", "brand_id", "item_id", "revision", "message_digest", "policy_digest", "audience_digest", "source_revision", "eligible_count", "suppressed_count", "generated_at", "expires_at", "provider_ready"}
    if not isinstance(value, dict) or set(value) != allowed or type(value.get("schema_version")) is not int or value.get("schema_version") != 1:
        _fail("invalid_preview")
    result = dict(value)
    _id(result["brand_id"], "brand_id"); _id(result["item_id"], "item_id")
    if isinstance(result["revision"], bool) or not isinstance(result["revision"], int) or result["revision"] < 1: _fail("invalid_revision")
    _digest(result["message_digest"], "message_digest"); _digest(result["policy_digest"], "policy_digest"); _digest(result["audience_digest"], "audience_digest")
    if not isinstance(result["source_revision"], str) or not _OPAQUE.fullmatch(result["source_revision"]): _fail("invalid_source_revision")
    for key in ("eligible_count", "suppressed_count"):
        if isinstance(result[key], bool) or not isinstance(result[key], int) or result[key] < 0 or result[key] > 100000: _fail("invalid_preview_count")
    generated = _aware(result["generated_at"], "generated_at")
    expires = _aware(result["expires_at"], "expires_at")
    if generated > now or now - generated > timedelta(minutes=5) or expires <= now or expires > generated + timedelta(days=7): _fail("invalid_preview_window")
    if result["provider_ready"] is not True: _fail("source_not_ready")
    result["generated_at"] = generated.isoformat(); result["expires_at"] = expires.isoformat()
    return result


def preview_request(item: dict[str, Any], now: datetime) -> dict[str, Any]:
    item = marketing_studio.validate_work_item(item)
    if item["kind"] != "email_campaign" or item["channel"] != "email" or item["state"] not in {"ready", "draft"}:
        _fail("email_draft_required")
    policy = _policy(item)
    return {"schema_version": 1, "brand_id": _id(item["brand_id"], "brand_id"), "item_id": _id(item.get("id"), "item_id"), "revision": item["revision"], "message": _message_fields(item), "policy": policy, "message_digest": _message_digest(item), "policy_digest": _policy_digest(policy)}


def approval_contract(item: dict[str, Any], config: dict[str, Any], preview: dict[str, Any], send_at: datetime, now: datetime) -> dict[str, Any]:
    config = validate_config(config)
    item = marketing_studio.validate_work_item(item)
    if item["kind"] != "email_campaign" or item["channel"] != "email" or item["state"] != "ready": _fail("email_draft_not_ready")
    now = _aware(now, "now"); send_at = _aware(send_at, "send_at")
    if send_at < now: _fail("send_at_in_past")
    checked = _validate_preview(preview, now)
    expected = preview_request(item, now)
    for key in ("schema_version", "brand_id", "item_id", "revision", "message_digest", "policy_digest"):
        if checked.get(key) != expected[key]: _fail("preview_mismatch")
    if send_at >= datetime.fromisoformat(checked["expires_at"]): _fail("preview_expired")
    policy = _policy(item)
    contract = {"schema_version": 1, "brand_id": item["brand_id"], "item_id": item["id"], "revision": item["revision"], "message": _message_fields(item), "message_digest": expected["message_digest"], "policy_digest": expected["policy_digest"], "audience_digest": checked["audience_digest"], "preview_generated_at": checked["generated_at"], "preview_expires_at": checked["expires_at"], "source_revision": checked["source_revision"], "eligible_count": checked["eligible_count"], "suppressed_count": checked["suppressed_count"], "send_at": send_at.isoformat(), "config_digest": hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "policy": policy}
    digest_input = {key: value for key, value in contract.items() if key != "policy"}
    contract["approval_digest"] = hashlib.sha256(json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    contract["idempotency_key"] = hashlib.sha256(("campaign:" + contract["approval_digest"]).encode()).hexdigest()
    return contract


def _contract_digest(contract: dict[str, Any]) -> str:
    digest_input = {key: value for key, value in contract.items() if key not in {"approval_digest", "idempotency_key", "policy"}}
    return hashlib.sha256(json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_contract(contract: Any, config: dict[str, Any], now: datetime, *, allow_expired: bool = False) -> dict[str, Any]:
    config = validate_config(config)
    if not isinstance(contract, dict): _fail("approval_required")
    if "approval_digest" not in contract or "idempotency_key" not in contract: _fail("approval_required")
    allowed = {"schema_version", "brand_id", "item_id", "revision", "message", "message_digest", "policy_digest", "audience_digest", "preview_generated_at", "preview_expires_at", "source_revision", "eligible_count", "suppressed_count", "send_at", "config_digest", "policy", "approval_digest", "idempotency_key"}
    if set(contract) != allowed or type(contract.get("schema_version")) is not int or contract.get("schema_version") != 1: _fail("invalid_contract")
    _id(contract["brand_id"], "brand_id"); _id(contract["item_id"], "item_id")
    if isinstance(contract["revision"], bool) or not isinstance(contract["revision"], int) or contract["revision"] < 1: _fail("invalid_revision")
    message = contract["message"]
    if not isinstance(message, dict) or set(message) != {"title", "subject", "body"} or any(not isinstance(message[key], str) for key in message): _fail("invalid_message")
    if not message["title"].strip() or len(message["title"]) > 240 or "\n" in message["title"] or "\r" in message["title"]: _fail("invalid_message")
    try:
        marketing_campaigns.validate_subject(message["subject"])
        if not marketing_campaigns.validate_copy(message["body"]).strip(): _fail('invalid_message')
        marketing_studio.validate_work_item({'brand_id':contract['brand_id'], 'kind':'email_campaign', 'channel':'email', 'title':message['title'], 'body':message['body'], 'brief':{}})
    except ValueError:
        _fail("invalid_message")
    if _digest(hashlib.sha256(json.dumps(message, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "message_digest") != contract["message_digest"]: _fail("message_digest_mismatch")
    try:
        policy = marketing_campaigns.validate_policy(contract["policy"])
    except ValueError:
        _fail("invalid_policy")
    if _policy_digest(policy) != contract["policy_digest"]: _fail("policy_digest_mismatch")
    _digest(contract["audience_digest"], "audience_digest")
    if not isinstance(contract["source_revision"], str) or not _OPAQUE.fullmatch(contract["source_revision"]): _fail("invalid_source_revision")
    for key in ("eligible_count", "suppressed_count"):
        if isinstance(contract[key], bool) or not isinstance(contract[key], int) or contract[key] < 0 or contract[key] > 100000: _fail("invalid_contract_count")
    current = _aware(now, "now")
    generated = _aware(contract["preview_generated_at"], "preview_generated_at")
    expires = _aware(contract["preview_expires_at"], "preview_expires_at")
    send_at = _aware(contract["send_at"], "send_at")
    if send_at < generated or send_at >= expires: _fail('invalid_contract_window')
    if generated > current or expires <= generated or expires > generated + timedelta(days=7) or (not allow_expired and expires <= current): _fail("invalid_contract_window")
    expected_config = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if contract["config_digest"] != expected_config: _fail("config_digest_mismatch")
    _digest(contract["approval_digest"], "approval_digest")
    if contract["approval_digest"] != _contract_digest(contract): _fail("approval_digest_mismatch")
    _digest(contract["idempotency_key"], "idempotency_key")
    if contract["idempotency_key"] != hashlib.sha256(("campaign:" + contract["approval_digest"]).encode()).hexdigest(): _fail("idempotency_mismatch")
    return dict(contract)


def validate_receipt(value: Any, contract: dict[str, Any]) -> dict[str, Any]:
    allowed = {"schema_version", "brand_id", "item_id", "revision", "idempotency_key", "audience_digest", "message_digest", "policy_digest", "status", "eligible_count", "delivered_count", "suppressed_count", "source_revision"}
    if not isinstance(value, dict) or set(value) != allowed or type(value.get("schema_version")) is not int or value.get("schema_version") != 1: _fail("invalid_receipt")
    for key in ("brand_id", "item_id"): _id(value[key], key)
    if value["brand_id"] != contract["brand_id"] or value["item_id"] != contract["item_id"] or isinstance(value["revision"], bool) or not isinstance(value["revision"], int) or value["revision"] != contract["revision"]: _fail("receipt_identity_mismatch")
    _digest(value["idempotency_key"], "idempotency_key")
    if value["idempotency_key"] != contract["idempotency_key"]: _fail("receipt_idempotency_mismatch")
    for key in ("audience_digest", "message_digest", "policy_digest"):
        _digest(value[key], key)
        if value[key] != contract[key]: _fail("receipt_digest_mismatch")
    if not isinstance(value['status'], str) or value["status"] not in {"accepted", "delivered", "partial", "blocked", "uncertain"}: _fail("invalid_receipt_status")
    for key in ("eligible_count", "delivered_count", "suppressed_count"):
        if isinstance(value[key], bool) or not isinstance(value[key], int) or value[key] < 0 or value[key] > 100000: _fail("invalid_receipt_count")
    if value["eligible_count"] > contract["eligible_count"] or value["delivered_count"] > value["eligible_count"] or value["delivered_count"] + value["suppressed_count"] > contract["eligible_count"]: _fail("receipt_count_exceeds_audience")
    if value['status'] == 'delivered' and (value['delivered_count'] != value['eligible_count'] or value['delivered_count'] + value['suppressed_count'] != contract['eligible_count']):
        _fail('incomplete_delivery_receipt')
    if value['status'] == 'blocked' and value['delivered_count']:
        _fail('invalid_blocked_receipt')
    if value["source_revision"] != contract["source_revision"]: _fail("receipt_source_mismatch")
    return dict(value)


def _credential(config: dict[str, Any], project: dict[str, Any]) -> str:
    import marketing_email_provider
    reader = getattr(marketing_email_provider, "read_owned_reference", None)
    if reader is None:
        _fail("owned_reference_reader_unavailable")
    return reader(config["credential_ref"], config["credential_name"], project)


def _request(method: str, endpoint: str, config: dict[str, Any], project: dict[str, Any], payload: dict[str, Any] | None = None, opener: Callable[..., Any] | None = None, *, token: str | None = None) -> dict[str, Any]:
    config = validate_config(config)
    token = token if token is not None else _credential(config, project)
    if not isinstance(token, str) or not token or "\r" in token or "\n" in token: _fail("invalid_adapter_credential")
    body = None if payload is None else json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    request = urllib.request.Request(config["base_url"] + endpoint, data=body, headers={"accept": "application/json", "content-type": "application/json", "authorization": "Bearer " + token}, method=method)
    if opener is None:
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl): _fail("redirect_rejected")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open
    try:
        with opener(request, timeout=15) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES: _fail("response_too_large")
            if status < 200 or status >= 300: _fail("source_http_error")
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict): _fail("invalid_source_response")
            return value
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        _fail("source_unavailable")


def request_preview(item: dict[str, Any], config: dict[str, Any], project: dict[str, Any], now: datetime, opener: Callable[..., Any] | None = None) -> dict[str, Any]:
    now = _aware(now, 'now')
    started = time.monotonic()
    request = preview_request(item, now)
    result = _request("POST", _PATHS["preview"], config, project, request, opener)
    # The source creates its snapshot during the request, after the caller's
    # initial timestamp. Validate freshness at the completed request boundary.
    completed = now + timedelta(seconds=max(0, time.monotonic() - started))
    checked = _validate_preview(result, completed)
    for key in ("schema_version", "brand_id", "item_id", "revision", "message_digest", "policy_digest"):
        if checked.get(key) != request[key]: _fail("preview_mismatch")
    return checked


def request_dispatch(contract: dict[str, Any], config: dict[str, Any], project: dict[str, Any], opener: Callable[..., Any] | None = None) -> dict[str, Any]:
    now = datetime.now(UTC)
    checked_contract = validate_contract(contract, config, now)
    if _aware(checked_contract["send_at"], "send_at") > now: _fail("send_not_due")
    token = _credential(validate_config(config), project)
    try:
        result = _request("POST", _PATHS["dispatch"], config, project, checked_contract, opener, token=token)
        return validate_receipt(result, checked_contract)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, OSError, urllib.error.URLError, TimeoutError):
        return {"status": "uncertain", "error": "source_unavailable"}


def request_receipt(contract: dict[str, Any], config: dict[str, Any], project: dict[str, Any], opener: Callable[..., Any] | None = None) -> dict[str, Any]:
    checked_contract = validate_contract(contract, config, datetime.now(UTC), allow_expired=True)
    key = checked_contract["idempotency_key"]
    result = _request("GET", _PATHS["receipt"] + "?idempotency_key=" + key, config, project, None, opener)
    return validate_receipt(result, checked_contract)

"""Validation and normalization for versioned marketing strategy reports.

This module deliberately contains no model, database, or network code.  A
collector or synthesis worker may produce a candidate mapping, then call
``normalize_report`` before persisting or rendering it.  The normalized
mapping is the dashboard contract.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import re


SCHEMA_VERSION = 1
SOURCE_STATES = frozenset({"available", "unavailable", "failed", "not_configured"})
FRESHNESS_STATES = frozenset({"fresh", "stale", "unknown"})
METRIC_STATES = frozenset({"observed", "unavailable", "failed"})
REPORT_STATUSES = frozenset({"complete", "partial", "blocked"})
ACTION_PRIORITIES = frozenset({"critical", "high", "medium", "low"})
ACTION_MODES = frozenset({"automated", "human", "review_required"})
ACTION_STATUSES = frozenset({"proposed", "approved", "blocked", "completed"})
CLAIM_TYPES = frozenset({"fact", "observation", "recommendation"})
CONFIDENCE = frozenset({"high", "medium", "low", "unknown"})

_MAX = {
    "report_id": 120,
    "subject_name": 200,
    "subject_url": 2048,
    "source_key": 80,
    "source_label": 160,
    "error": 500,
    "metric_key": 100,
    "metric_unit": 40,
    "action_id": 80,
    "action_title": 240,
    "action_detail": 2000,
    "claim_text": 1000,
}
_CLAIM_GATED_TERMS = re.compile(
    r"\b(verified|traffic|ranking|ranked|rank|position|sessions?|users?|visits?|impressions?|clicks?)\b",
    re.IGNORECASE,
)
_ISO_Z = re.compile(r"Z$")


class ReportValidationError(ValueError):
    """Raised when a candidate report cannot be safely rendered."""

    def __init__(self, errors):
        self.errors = tuple(str(error) for error in errors)
        super().__init__("; ".join(self.errors))


def _required(mapping, key, errors):
    if key not in mapping:
        errors.append(f"missing required field: {key}")
        return None
    return mapping[key]


def _string(value, field, errors, *, required=True, max_length=None):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty string")
        return None
    value = value.strip()
    limit = max_length or _MAX.get(field, 500)
    if len(value) > limit:
        errors.append(f"{field} exceeds {limit} characters")
    return value


def _enum(value, field, allowed, errors):
    if value not in allowed:
        errors.append(f"{field} must be one of {sorted(allowed)}")
        return None
    return value


def _list(value, field, errors, *, required=True, max_items=50):
    if value is None and not required:
        return []
    if not isinstance(value, list):
        errors.append(f"{field} must be a list")
        return []
    if len(value) > max_items:
        errors.append(f"{field} exceeds {max_items} items")
    return value


def _timestamp(value, field, errors):
    if not isinstance(value, str):
        errors.append(f"{field} must be an ISO-8601 timestamp")
        return None
    candidate = _ISO_Z.sub("+00:00", value.strip())
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        errors.append(f"{field} must be an ISO-8601 timestamp")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{field} must include a timezone")
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _metric(raw, source_key, errors):
    if not isinstance(raw, dict):
        errors.append(f"source {source_key} metric must be an object")
        return None
    local = []
    key = _string(raw.get("key"), "metric_key", local)
    state = _enum(raw.get("state"), "metric.state", METRIC_STATES, local)
    value = raw.get("value")
    if state == "observed":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            local.append("observed metric.value must be numeric, including zero")
        elif not math.isfinite(value):
            local.append("observed metric.value must be finite")
    elif value is not None:
        local.append("unavailable or failed metric.value must be null or omitted")
    unit = _string(raw.get("unit"), "metric_unit", local, required=False)
    if local:
        errors.extend(f"{source_key}: {item}" for item in local)
        return None
    result = {"key": key, "state": state}
    result["value"] = value if state == "observed" else None
    if unit:
        result["unit"] = unit
    return result


def _source(raw, errors):
    if not isinstance(raw, dict):
        errors.append("source must be an object")
        return None
    local = []
    key = _string(raw.get("key"), "source_key", local)
    label = _string(raw.get("label"), "source_label", local)
    state = _enum(raw.get("state"), "source.state", SOURCE_STATES, local)
    freshness = _enum(raw.get("freshness"), "source.freshness", FRESHNESS_STATES, local)
    checked_at = _timestamp(raw.get("checked_at"), "source.checked_at", local)
    observed_at = raw.get("observed_at")
    if observed_at is not None:
        observed_at = _timestamp(observed_at, "source.observed_at", local)
    metrics = []
    for metric in _list(raw.get("metrics", []), "source.metrics", local, max_items=50):
        normalized = _metric(metric, key or "unknown", local)
        if normalized is not None:
            metrics.append(normalized)
    error = _string(raw.get("error"), "error", local, required=False)
    if state == "failed" and not error:
        local.append("failed source requires error")
    if state != "failed" and error:
        local.append("error is only allowed for failed sources")
    if local:
        errors.extend(f"source: {item}" for item in local)
        return None
    result = {"key": key, "label": label, "state": state, "freshness": freshness,
              "checked_at": checked_at, "observed_at": observed_at, "metrics": metrics}
    if error:
        result["error"] = error
    return result


def _claim(raw, source_map, errors):
    if not isinstance(raw, dict):
        errors.append("claim must be an object")
        return None
    local = []
    text = _string(raw.get("text"), "claim_text", local)
    claim_type = _enum(raw.get("type"), "claim.type", CLAIM_TYPES, local)
    confidence = _enum(raw.get("confidence", "unknown"), "claim.confidence", CONFIDENCE, local)
    refs = _list(raw.get("source_refs", []), "claim.source_refs", local, max_items=20)
    normalized_refs = []
    for ref in refs:
        value = _string(ref, "source_ref", local, max_length=_MAX["source_key"])
        if value:
            normalized_refs.append(value)
            source = source_map.get(value)
            if source is None:
                local.append(f"claim references unknown source: {value}")
            elif source["state"] != "available":
                local.append(f"claim references non-available source: {value}")
    if text and _CLAIM_GATED_TERMS.search(text) and claim_type in {"fact", "observation"}:
        if not normalized_refs:
            local.append("traffic, ranking, and verified claims require an available source reference")
    if local:
        errors.extend(f"claim: {item}" for item in local)
        return None
    return {"text": text, "type": claim_type, "confidence": confidence,
            "source_refs": sorted(set(normalized_refs))}


def _action(raw, action_ids, source_map, errors):
    if not isinstance(raw, dict):
        errors.append("action must be an object")
        return None
    local = []
    action_id = _string(raw.get("id"), "action_id", local)
    title = _string(raw.get("title"), "action_title", local)
    detail = _string(raw.get("detail"), "action_detail", local)
    priority = _enum(raw.get("priority"), "action.priority", ACTION_PRIORITIES, local)
    mode = _enum(raw.get("mode"), "action.mode", ACTION_MODES, local)
    status = _enum(raw.get("status", "proposed"), "action.status", ACTION_STATUSES, local)
    human = raw.get("human_decision_required")
    if not isinstance(human, bool):
        local.append("action.human_decision_required must be boolean")
    if mode in {"human", "review_required"} and human is False:
        local.append("human or review_required action must require human decision")
    dependencies = _list(raw.get("dependencies", []), "action.dependencies", local, max_items=20)
    normalized_dependencies = []
    for dependency in dependencies:
        value = _string(dependency, "action.dependency", local, max_length=_MAX["action_id"])
        if value:
            normalized_dependencies.append(value)
            if value not in action_ids:
                local.append(f"action depends on unknown action: {value}")
    source_refs = _list(raw.get("source_refs", []), "action.source_refs", local, max_items=20)
    normalized_refs = []
    for ref in source_refs:
        value = _string(ref, "action.source_ref", local, max_length=_MAX["source_key"])
        if value:
            normalized_refs.append(value)
            if value not in source_map:
                local.append(f"action references unknown source: {value}")
    if local:
        errors.extend(f"action: {item}" for item in local)
        return None
    return {"id": action_id, "title": title, "detail": detail, "priority": priority,
            "mode": mode, "status": status, "human_decision_required": human,
            "dependencies": sorted(set(normalized_dependencies)),
            "source_refs": sorted(set(normalized_refs))}


def normalize_report(candidate):
    """Validate and return a deterministic, dashboard-safe report mapping.

    Raises :class:`ReportValidationError` for any unsafe or incomplete input.
    The input is never mutated.  In particular, an observed metric with value
    ``0`` is retained as zero, while unavailable and failed metrics normalize to
    ``None`` with their explicit state intact.
    """
    if not isinstance(candidate, dict):
        raise ReportValidationError(["report must be an object"])
    errors = []
    version = _required(candidate, "schema_version", errors)
    if version != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    report_id = _string(candidate.get("report_id"), "report_id", errors)
    status = _enum(candidate.get("status"), "status", REPORT_STATUSES, errors)
    generated_at = _timestamp(candidate.get("generated_at"), "generated_at", errors)
    subject = candidate.get("subject")
    if not isinstance(subject, dict):
        errors.append("subject must be an object")
        subject = {}
    subject_name = _string(subject.get("name"), "subject_name", errors)
    subject_url = _string(subject.get("url"), "subject_url", errors)
    sources = []
    for source in _list(candidate.get("sources"), "sources", errors, max_items=30):
        normalized = _source(source, errors)
        if normalized:
            sources.append(normalized)
    source_map = {source["key"]: source for source in sources}
    if len(source_map) != len(sources):
        errors.append("sources must have unique keys")
    claims = []
    for claim in _list(candidate.get("claims", []), "claims", errors, max_items=50):
        normalized = _claim(claim, source_map, errors)
        if normalized:
            claims.append(normalized)
    actions_raw = _list(candidate.get("actions"), "actions", errors, max_items=50)
    if not actions_raw:
        errors.append("actions must contain at least one prioritized next step")
    action_ids = []
    for raw in actions_raw:
        if isinstance(raw, dict) and isinstance(raw.get("id"), str):
            action_ids.append(raw["id"].strip())
    if len(set(action_ids)) != len(action_ids):
        errors.append("actions must have unique ids")
    actions = [_action(raw, set(action_ids), source_map, errors) for raw in actions_raw]
    actions = [action for action in actions if action is not None]
    if errors:
        raise ReportValidationError(errors)
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "status": status,
        "generated_at": generated_at,
        "subject": {"name": subject_name, "url": subject_url},
        "sources": sorted(sources, key=lambda item: item["key"]),
        "claims": sorted(claims, key=lambda item: (item["type"], item["text"])),
        "actions": sorted(actions, key=lambda item: (ACTION_PRIORITIES_ORDER[item["priority"]], item["id"])),
    }
    return deepcopy(normalized)


ACTION_PRIORITIES_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def validate_report(candidate):
    """Return ``True`` when valid, otherwise raise a descriptive error."""
    normalize_report(candidate)
    return True

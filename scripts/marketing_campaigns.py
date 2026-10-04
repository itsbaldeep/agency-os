"""Pure, fail-closed campaign policy and recipient eligibility contracts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re
from typing import Any

import marketing_studio

POLICY_FIELDS = {
    "category", "play", "inactivity_days", "cooldown_hours", "max_per_7_days",
    "quiet_start", "quiet_end", "timezone", "service_event",
}
CATEGORIES = {"marketing", "transactional"}
PLAYS = {"welcome", "inactivity", "product_update", "service_event"}
_CLOCK = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


def default_policy() -> dict[str, Any]:
    """Return the conservative dashboard starter policy."""
    return {
        "category": "marketing", "play": "inactivity", "inactivity_days": 7,
        "cooldown_hours": 24, "max_per_7_days": 2, "quiet_start": "22:00",
        "quiet_end": "08:00", "timezone": "UTC", "service_event": "",
    }


def _error(message: str):
    raise ValueError(message)


def _clock(value: Any, name: str) -> int:
    if not isinstance(value, str) or not _CLOCK.fullmatch(value):
        _error(f"{name} must be HH:MM")
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def _text(value: Any, name: str, limit: int, required: bool = True) -> str:
    if not isinstance(value, str):
        if value is None and not required:
            return ""
        _error(f"{name} must be text")
    value = value.strip()
    if required and not value:
        _error(f"{name} is required")
    if len(value) > limit:
        _error(f"{name} exceeds {limit} characters")
    return value


def validate_policy(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        _error("policy must be an object")
    unknown = set(payload) - POLICY_FIELDS
    if unknown:
        _error("policy contains unsupported fields")
    category = payload.get("category")
    play = payload.get("play")
    if not isinstance(category, str) or not isinstance(play, str) or category not in CATEGORIES or play not in PLAYS:
        _error("unsupported campaign category or play")
    inactivity_days = payload.get("inactivity_days")
    cooldown_hours = payload.get("cooldown_hours")
    max_per_7_days = payload.get("max_per_7_days")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (inactivity_days, cooldown_hours, max_per_7_days)):
        _error("campaign limits must be integers")
    if inactivity_days < 0 or inactivity_days > 365:
        _error("inactivity_days is out of bounds")
    if play == "inactivity" and inactivity_days < 7:
        _error("inactivity play requires at least 7 days")
    if cooldown_hours < 24 or cooldown_hours > 8760:
        _error("cooldown_hours is out of bounds")
    if max_per_7_days < 1 or max_per_7_days > 7:
        _error("max_per_7_days is out of bounds")
    timezone_name = _text(payload.get("timezone"), "timezone", 80)
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        _error("timezone must be an IANA timezone")
    quiet_start = _text(payload.get("quiet_start"), "quiet_start", 5)
    quiet_end = _text(payload.get("quiet_end"), "quiet_end", 5)
    if _clock(quiet_start, "quiet_start") == _clock(quiet_end, "quiet_end"):
        _error("quiet hours must have different start and end")
    service_event = _text(payload.get("service_event"), "service_event", 120, required=False)
    if category == "transactional" and not service_event:
        _error("transactional campaigns require service_event")
    if category == "marketing" and service_event:
        _error("marketing campaigns cannot set service_event")
    if category == "transactional" and play != "service_event":
        _error("transactional campaigns require service_event play")
    if category == "marketing" and play == "service_event":
        _error("service_event play is transactional only")
    marketing_studio._inspect({"service_event": service_event})
    return {
        "category": category, "play": play, "inactivity_days": inactivity_days,
        "cooldown_hours": cooldown_hours, "max_per_7_days": max_per_7_days,
        "quiet_start": quiet_start, "quiet_end": quiet_end,
        "timezone": timezone_name, "service_event": service_event,
    }


def validate_subject(subject: str) -> str:
    """Validate subject through the existing credential-safe studio contract."""
    if not isinstance(subject, str) or '\n' in subject or '\r' in subject:
        _error('subject must be single-line text')
    item = marketing_studio.validate_work_item({
        "brand_id": 1, "kind": "email_campaign", "channel": "email",
        "title": subject, "brief": {}, "body": "",
    })
    return item["title"]


def validate_copy(copy: str) -> str:
    """Validate copy through the existing credential-safe studio contract."""
    item = marketing_studio.validate_work_item({
        "brand_id": 1, "kind": "email_campaign", "channel": "email",
        "title": "Campaign copy", "brief": {}, "body": copy,
    })
    return item["body"]


def _timestamp(value: Any, name: str, *, allow_none: bool = False) -> datetime | None:
    if value is None and allow_none:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            value = None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an aware timestamp")
    return value.astimezone(timezone.utc)


def _result(eligible: bool, reason: str, next_at: datetime | None = None) -> dict[str, Any]:
    return {"eligible": eligible, "reason": reason,
            "next_eligible_at": next_at.astimezone(timezone.utc).isoformat() if next_at else None}


def _quiet_end(policy: dict[str, Any], now: datetime) -> datetime | None:
    local = now.astimezone(ZoneInfo(policy["timezone"]))
    start = _clock(policy["quiet_start"], "quiet_start")
    end = _clock(policy["quiet_end"], "quiet_end")
    minute = local.hour * 60 + local.minute
    in_quiet = (start < end and start <= minute < end) or (start > end and (minute >= start or minute < end))
    if not in_quiet:
        return None
    day = local.date() if minute < end or start < end else (local.date() + timedelta(days=1))
    if start > end and minute >= start:
        day = local.date() + timedelta(days=1)
    # A repeated hour has two possible UTC boundaries. Choose the future one.
    # For a skipped hour, conversion round-trips to the first real local time
    # after that boundary, which is outside this quiet interval.
    candidates = [datetime(day.year, day.month, day.day, end // 60, end % 60,
                           tzinfo=ZoneInfo(policy['timezone']), fold=fold).astimezone(timezone.utc)
                  for fold in (0, 1)]
    def outside_quiet(candidate):
        value = candidate.astimezone(ZoneInfo(policy['timezone']))
        value_minute = value.hour * 60 + value.minute
        return not ((start < end and start <= value_minute < end) or
                    (start > end and (value_minute >= start or value_minute < end)))
    candidates = [candidate for candidate in candidates if candidate > now and outside_quiet(candidate)]
    if candidates:
        return min(candidates)
    return now + timedelta(days=1)


def evaluate_recipient(policy: dict[str, Any], facts: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Return only an eligibility decision, reason code, and next time."""
    try:
        policy = validate_policy(policy)
    except ValueError:
        return _result(False, "invalid_policy")
    if not isinstance(facts, dict) or not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return _result(False, "missing_or_invalid_facts")
    now = now.astimezone(timezone.utc)
    required = {"active", "address_verified", "suppressed", "complaint", "bounce", "unsubscribed", "last_contact", "sent_last_7_days", "duplicate", "observed_at", "trigger_confirmed"}
    if policy["category"] == "marketing":
        required.add("marketing_consent")
    if policy["play"] == "inactivity":
        required.add("last_activity")
    if policy["category"] == "transactional":
        required.add("service_event")
    if any(key not in facts for key in required):
        return _result(False, "missing_or_invalid_facts")
    try:
        observed = _timestamp(facts['observed_at'], 'observed_at')
    except ValueError:
        return _result(False, 'missing_or_invalid_facts')
    if observed > now or now - observed > timedelta(minutes=5):
        return _result(False, 'stale_or_future_facts')
    if facts['trigger_confirmed'] is not True:
        return _result(False, 'trigger_not_confirmed')
    if facts.get("active") is not True or facts.get("address_verified") is not True:
        return _result(False, "inactive_or_unverified_address")
    if facts.get("suppressed") is not False or facts.get("complaint") is not False or facts.get("bounce") is not False or facts.get("unsubscribed") is not False:
        return _result(False, "suppressed_or_risk_flagged")
    if policy["category"] == "marketing" and facts.get("marketing_consent") is not True:
        return _result(False, "marketing_consent_required")
    if facts.get("duplicate") is not False:
        return _result(False, "duplicate_blocked")
    sent = facts.get("sent_last_7_days")
    if isinstance(sent, bool) or not isinstance(sent, int) or sent < 0:
        return _result(False, "missing_or_invalid_facts")
    if sent >= policy["max_per_7_days"]:
        return _result(False, "frequency_cap")
    try:
        last_contact = _timestamp(facts.get("last_contact"), "last_contact", allow_none=True)
    except ValueError:
        return _result(False, "missing_or_invalid_facts")
    if last_contact is not None and last_contact > now:
        return _result(False, 'stale_or_future_facts')
    if last_contact is not None and now < last_contact + timedelta(hours=policy["cooldown_hours"]):
        return _result(False, "cooldown", last_contact + timedelta(hours=policy["cooldown_hours"]))
    if policy["category"] == "transactional" and facts.get("service_event") != policy["service_event"]:
        return _result(False, "service_event_mismatch")
    if policy["play"] == "inactivity":
        try:
            last_activity = _timestamp(facts.get("last_activity"), "last_activity")
        except ValueError:
            return _result(False, "missing_or_invalid_facts")
        if last_activity > now:
            return _result(False, 'stale_or_future_facts')
        due = last_activity + timedelta(days=policy["inactivity_days"])
        if now < due:
            return _result(False, "inactivity_not_due", due)
    quiet_end = _quiet_end(policy, now)
    if quiet_end:
        return _result(False, "quiet_hours", quiet_end)
    return _result(True, "eligible")

"""Pure, project-agnostic marketing studio contracts.

The studio only prepares reviewable drafts.  Planned dates are bookkeeping and
never authorize sending, publishing, account creation, or provider access.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any

PROFILE_FIELDS = {"positioning", "audience", "offer", "voice", "primary_goal", "logo_url"}
KINDS = {"strategy", "social_post", "email_campaign", "video_brief", "channel_setup"}
CHANNELS = {"website", "blog", "help", "instagram", "youtube", "linkedin", "facebook", "x", "email"}
STATES = {"draft", "ready", "archived"}
_SECRET_KEY = re.compile(r"(?:^|[_-])(password|passwd|secret|token|api[_-]?key|access[_-]?key|credential|oauth|bearer|private[_-]?key)(?:$|[_-])", re.I)
_SECRET_VALUE = re.compile(r"(?:bearer\s+[A-Za-z0-9._~+/=-]{8,}|(?:api[_ -]?key|secret|password|token)\s*[:=]\s*\S+|-----BEGIN [A-Z ]+PRIVATE KEY-----|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", re.I)
_URL = re.compile(r"^https://[^\s]+$", re.I)
__all__ = ["GTM_PLAYBOOKS", "validate_profile", "validate_work_item", "render_work_item"]

def _inspect(value: Any, depth: int = 0, count: list[int] | None = None) -> None:
    """Reject credential-shaped structure while allowing ordinary prose."""
    count = count or [0]
    count[0] += 1
    if depth > 6 or count[0] > 250:
        raise ValueError("brief is too deeply nested or large")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 120 or _SECRET_KEY.search(key):
                raise ValueError("credential-like fields are not allowed")
            _inspect(child, depth + 1, count)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _inspect(child, depth + 1, count)
    elif isinstance(value, str):
        if _SECRET_VALUE.search(value):
            raise ValueError("credential-like values are not allowed")
        if value.lower().startswith("https://") and "@" in value.split("/", 3)[2]:
            raise ValueError("URLs with userinfo are not allowed")

def _safe_url(value: str, name: str) -> str:
    if not value:
        return ""
    if not _URL.match(value) or "@" in value.split("/", 3)[2]:
        raise ValueError(f"{name} must be a safe https URL")
    return value

GTM_PLAYBOOKS = [
    {"id": "search_intent_content", "title": "Search intent content", "trigger": "A validated query gap exists", "evidence": "GSC query and page evidence", "metric": "qualified organic clicks", "guardrails": "Draft from evidence; review claims and cannibalization."},
    {"id": "help_activation", "title": "Help activation", "trigger": "Users stall at a documented product step", "evidence": "Support or product analytics evidence", "metric": "help-assisted activation", "guardrails": "Explain current behavior; no invented product capability."},
    {"id": "technical_seo", "title": "Technical SEO remediation", "trigger": "Crawl or PageSpeed issue is verified", "evidence": "timestamped crawl/PageSpeed result", "metric": "indexability or CWV improvement", "guardrails": "Create a recommendation; implementation needs separate approval."},
    {"id": "competitor_gaps", "title": "Competitor content gaps", "trigger": "Comparable pages expose an addressable gap", "evidence": "dated competitor and owned-page comparison", "metric": "non-branded impressions", "guardrails": "No copied text, confidential inference, or unsupported superiority claim."},
    {"id": "internal_links", "title": "Internal link improvement", "trigger": "Relevant orphan or weakly linked page found", "evidence": "crawl link graph and target relevance", "metric": "discoverability and target clicks", "guardrails": "Suggest links only where context is clear."},
    {"id": "backlink_outreach", "title": "Backlink outreach", "trigger": "Relevant, legitimate publication opportunity found", "evidence": "source URL, relevance, and contact permission", "metric": "qualified referring domains", "guardrails": "Human review; no bulk outreach, scraping, or guaranteed placement."},
    {"id": "launch_video", "title": "Launch video", "trigger": "A reviewable product or campaign story is ready", "evidence": "approved facts, assets, and destination", "metric": "qualified video views", "guardrails": "Use supplied facts/assets; render only after approval."},
    {"id": "organic_social", "title": "Organic social", "trigger": "A useful approved story has a channel fit", "evidence": "approved source and channel objective", "metric": "engaged reach or profile actions", "guardrails": "Draft only; respect channel format and accessibility."},
    {"id": "welcome", "title": "Welcome sequence", "trigger": "A user opts into marketing communication", "evidence": "consent event and lifecycle state", "metric": "activation or retained users", "guardrails": "Marketing consent required; transactional messages remain separate."},
    {"id": "inactivity", "title": "Inactivity recovery", "trigger": "Eligible user has been inactive for at least 7 days", "evidence": "last activity timestamp and consent/suppression state", "metric": "returning active users", "guardrails": "No send when suppressed, unsubscribed, bounced, or recently contacted."},
    {"id": "product_updates", "title": "Product update", "trigger": "An approved change has a documented user impact", "evidence": "release note and affected audience", "metric": "feature adoption or reduced support friction", "guardrails": "Transactional notices are separate; do not imply availability before release."},
    {"id": "referral", "title": "Referral loop", "trigger": "A verified referral value proposition exists", "evidence": "approved offer, eligibility, and attribution plan", "metric": "qualified referrals", "guardrails": "Clear terms, consent, suppression, and frequency caps."},
]

def _text(value: Any, name: str, limit: int, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{name} is required")
    if len(value) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    if _SECRET_KEY.search(name) or _SECRET_VALUE.search(value):
        raise ValueError("credential-like fields or values are not allowed")
    return value

def validate_profile(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("profile must be an object")
    unknown = set(payload) - PROFILE_FIELDS
    if unknown or any(_SECRET_KEY.search(str(k)) for k in payload):
        raise ValueError("profile contains unsupported or credential-like fields")
    result = {k: _text(payload.get(k), k, 2000 if k != "logo_url" else 2048) for k in PROFILE_FIELDS}
    _safe_url(result["logo_url"], "logo_url")
    return result

def validate_work_item(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("work item must be an object")
    required = {"brand_id", "kind", "channel", "title"}
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"missing fields: {', '.join(sorted(missing))}")
    if isinstance(payload["brand_id"], bool) or not isinstance(payload["brand_id"], int) or payload["brand_id"] <= 0:
        raise ValueError("brand_id must be a positive integer")
    kind, channel = payload["kind"], payload["channel"]
    if kind not in KINDS or channel not in CHANNELS:
        raise ValueError("unsupported kind or channel")
    result = dict(payload)
    result["title"] = _text(payload["title"], "title", 240, True)
    result["brief"] = payload.get("brief", {})
    if not isinstance(result["brief"], dict) or len(str(result["brief"])) > 20000:
        raise ValueError("brief must be a bounded object")
    _inspect(result["brief"])
    result["body"] = _text(payload.get("body"), "body", 50000)
    result["state"] = payload.get("state", "draft")
    if result["state"] not in STATES:
        raise ValueError("unsupported state")
    result["revision"] = payload.get("revision", 1)
    if isinstance(result["revision"], bool) or not isinstance(result["revision"], int) or result["revision"] < 1:
        raise ValueError("revision must be a positive integer")
    if payload.get("task_id") is not None and (not isinstance(payload["task_id"], int) or payload["task_id"] <= 0):
        raise ValueError("task_id must be a positive integer")
    planned = payload.get("planned_at")
    if planned:
        if not isinstance(planned, str):
            raise ValueError("planned_at must be an ISO timestamp")
        try:
            _dt.datetime.fromisoformat(planned.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("planned_at must be an ISO timestamp") from exc
    for key in ("source_url", "cta_url"):
        if key in result["brief"]:
            _safe_url(str(result["brief"][key]), key)
    result["planned_at"] = planned
    return result

def render_work_item(brand: Any, profile: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    profile = validate_profile(profile)
    item = validate_work_item(item)
    brand_name = brand.get("name", "the brand") if isinstance(brand, dict) else str(brand or "the brand")
    brand_name = _text(brand_name, "brand", 240, True)
    brief = item["brief"]
    facts = brief.get("approved_facts", [])
    if isinstance(facts, str):
        facts = [facts]
    facts = [str(f).strip() for f in facts if str(f).strip()] if isinstance(facts, list) else []
    positioning = profile["positioning"] or "[positioning needed]"
    offer = profile["offer"] or "[offer needed]"
    cta = brief.get("cta_text") or "Learn more"
    source_url = brief.get("source_url", "")
    source_note = f" Source: {source_url}." if source_url else " Source URL needed."
    original = dict(brief)
    if item["kind"] == "video_brief":
        output_brief = {**original, "formats": ["9:16", "1:1", "16:9"], "duration_seconds": 20, "voiceover": "opt_in_only", "needs_input": []}
        if not brief.get("project_ui_asset"):
            output_brief["needs_input"].append("project_ui_asset")
        output_brief["scenes"] = [
            {"start": 0, "end": 4, "duration": 4, "purpose": "hook", "visual": facts[0] if facts else "approved problem needed", "on_screen": brand_name},
            {"start": 4, "end": 9, "duration": 5, "purpose": "context", "visual": "project UI asset", "on_screen": positioning},
            {"start": 9, "end": 15, "duration": 6, "purpose": "proof", "visual": facts[1] if len(facts) > 1 else "approved proof needed", "on_screen": offer},
            {"start": 15, "end": 20, "duration": 5, "purpose": "cta", "visual": "clean end card", "on_screen": cta},
        ]
        body = f"{brand_name}: 20-second video draft. Use only approved facts and the supplied project UI asset; voiceover requires explicit opt-in.{source_note}"
    elif item["kind"] == "channel_setup":
        display_name = brief.get("display_name") or brand_name
        bio = brief.get("bio") or " ".join(x for x in (positioning, offer) if x and not x.startswith("["))
        output_brief = {**original, "suggested_display_name": display_name, "suggested_bio": bio, "checklist": ["exact title", "bio", "logo", "banner", "links", "access and ownership review"], "account_creation": "not performed"}
        body = f"Channel setup draft for {brand_name}: display name: {display_name}; bio: {bio}. Supply approved logo, banner, and links. No account creation or credential handling is included."
    else:
        needs = [] if facts else ["approved_facts"]
        if item["kind"] == "email_campaign":
            subject = brief.get("subject") or f"{brand_name}: {cta}"
            copy = " ".join(facts) if facts else "[approved facts needed before sending]"
            body = f"Subject: {subject}\n\n{copy}\n\n{cta}." + source_note
            output_brief = {**original, "subject": subject, "needs_input": needs}
        else:
            copy = " ".join(facts) if facts else "[approved facts needed before publishing]"
            body = f"{copy}\n\n{cta}." + source_note
            output_brief = {**original, "needs_input": needs}
    output_brief.setdefault("approval", "human review before send or publish")
    return {"body": body, "brief": output_brief, "state": "draft", "reviewed": False, "send": False, "publish": False}

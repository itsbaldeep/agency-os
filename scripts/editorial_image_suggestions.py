"""Deterministic image-slot suggestion helpers.

The module only normalizes briefs and ranks already-available candidates. It
never calls a provider, uploads bytes, or marks an asset reviewed. Dashboard and
worker code can use the result to prefetch a small candidate set while keeping
the human review and publication gate intact.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


MAX_QUERY = 120
MAX_CANDIDATES = 5
_STOP = {
    "a", "an", "and", "for", "from", "how", "in", "of", "on", "or", "the",
    "to", "with", "your", "show", "use", "make", "image", "visual",
}
_DIAGRAM_TERMS = {
    "annotated", "chart", "comparison", "diagram", "example", "flow", "flowchart",
    "graph", "illustration", "illustrative", "infographic", "screenshot", "table", "timeline", "workflow",
}
_PHOTO_TERMS = {
    "candid", "desk", "headshot", "office", "person", "portrait", "professional", "workspace",
}
_DIAGRAM_KINDS = {"diagram", "illustration", "infographic", "chart", "flow", "comparison", "generated"}
_PHOTO_KINDS = {"photo", "photograph", "stock", "portrait"}


def _tokens(value: Any) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9][a-z0-9+#.-]{1,}", str(value or "").lower())
            if token not in _STOP]


def _clean_phrase(value: Any) -> str:
    words = []
    for token in _tokens(value):
        if token not in words:
            words.append(token)
    return " ".join(words)


def _semantic_tokens(value: Any) -> set[str]:
    return set(_tokens(value)) - _DIAGRAM_TERMS - _PHOTO_TERMS


def derive_intent(slot: dict[str, Any], title: str = "") -> dict[str, Any]:
    """Classify a slot as explanatory visual, stock-appropriate photo, or neutral."""
    if not isinstance(slot, dict):
        raise ValueError("image slot must be an object")
    text = " ".join(str(slot.get(key) or "") for key in ("brief", "alt", "prompt", "caption", "title", "placement",))
    tokens = set(_tokens(text))
    diagram_hits = sorted(tokens & _DIAGRAM_TERMS)
    photo_hits = sorted(tokens & _PHOTO_TERMS)
    if diagram_hits:
        kind, stock_appropriate = "explanatory_visual", False
    elif photo_hits:
        kind, stock_appropriate = "stock_photo", True
    else:
        kind, stock_appropriate = "neutral", True
    return {
        "kind": kind,
        "stock_appropriate": stock_appropriate,
        "requires_custom_visual": kind == "explanatory_visual",
        "signals": diagram_hits if kind == "explanatory_visual" else photo_hits,
        "title": _clean_phrase(title),
    }


def derive_query(slot: dict[str, Any], title: str = "") -> dict[str, Any]:
    """Build a bounded provider query and intent contract from slot metadata."""
    intent = derive_intent(slot, title)
    parts = [_clean_phrase(slot.get(key)) for key in ("alt", "brief", "prompt")]
    if intent["kind"] == "explanatory_visual":
        # This query is for discovery/context only. It must not cause a stock
        # photograph to be embedded for a diagram slot.
        parts.append("editorial visual")
    parts.append(intent["title"])
    words: list[str] = []
    for part in parts:
        for word in part.split():
            if word not in words:
                words.append(word)
    query = " ".join(words[:8])[:MAX_QUERY].strip()
    return {"query": query, **intent}


def _candidate_text(candidate: dict[str, Any]) -> str:
    provenance = candidate.get("provenance") if isinstance(candidate.get("provenance"), dict) else {}
    return " ".join(str(candidate.get(key) or "") for key in ("alt", "description", "caption", "kind", "visual_kind")) + " " + " ".join(str(value or "") for value in provenance.values())


def _text_for_candidate(candidate: dict[str, Any]) -> bool:
    return len(_tokens(candidate.get("alt") or candidate.get("description"))) >= 2


def _candidate_kind(candidate: dict[str, Any]) -> str:
    provenance = candidate.get("provenance") if isinstance(candidate.get("provenance"), dict) else {}
    raw_kind = candidate.get('kind') if candidate.get('kind') not in ('library', 'stock') else ''
    value = (candidate.get("visual_kind") or candidate.get("asset_visual_kind") or
             candidate.get("asset_kind") or candidate.get("raw_kind") or
             provenance.get("visual_kind") or raw_kind or provenance.get("kind") or candidate.get("provider") or "")
    return str(value).lower().replace("_", "-")


def rank_candidates(candidates: Iterable[dict[str, Any]], request: dict[str, Any], limit: int = MAX_CANDIDATES) -> list[dict[str, Any]]:
    """Rank project and provider candidates without selecting a reviewed asset."""
    if not isinstance(request, dict):
        raise ValueError("suggestion request must be an object")
    limit = max(1, min(int(limit), MAX_CANDIDATES))
    query_tokens = set(_tokens(request.get("query")))
    intent_kind = request.get("kind", "neutral")
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        candidate = dict(candidate)
        if not isinstance(candidate.get("provenance"), dict) or not candidate.get("provenance"):
            provider = candidate.get("provider")
            if provider:
                candidate["provenance"] = {
                    "provider": provider,
                    "source_url": candidate.get("source_url") or "",
                    "license_url": candidate.get("license_url") or "",
                    "photographer": candidate.get("photographer") or "",
                }
        url = candidate.get("url") or candidate.get("thumbnail_url") or candidate.get("thumbnail")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        text_tokens = set(_tokens(_candidate_text(candidate)))
        score = len(query_tokens & text_tokens) * 10
        kind = _candidate_kind(candidate)
        if intent_kind == "explanatory_visual":
            score += 35 if kind in _DIAGRAM_KINDS or any(term in kind for term in _DIAGRAM_TERMS) else -30
        elif intent_kind == "stock_photo":
            score += 25 if kind in _PHOTO_KINDS or kind == "pexels" else 0
        if candidate.get("asset_id") or candidate.get("id") and candidate.get("source") == "project":
            score += 20
        if candidate.get("current") is True:
            score += 100
        if candidate.get("reviewed") is True:
            score += 5
        ranked.append((score, str(candidate.get("id") or candidate.get("asset_id") or url), dict(candidate)))
    ranked.sort(key=lambda value: (-value[0], value[1]))
    output = []
    for score, _, candidate in ranked[:limit]:
        candidate["suggestion_score"] = score
        candidate["eligible_default"] = _eligible_default(candidate, request)
        output.append(candidate)
    return output


def _eligible_default(candidate: dict[str, Any], request: dict[str, Any]) -> bool:
    url = candidate.get("url") or candidate.get("thumbnail_url") or candidate.get("thumbnail")
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    provenance = candidate.get("provenance")
    if not isinstance(provenance, dict) or not provenance:
        return False
    # Existing article media is retained as the conservative first choice. A
    # newly suggested provider/library result needs a real semantic overlap and
    # descriptive alt text before it can be embedded as the default.
    if candidate.get("current") is True:
        return bool(_text_for_candidate(candidate))
    query_tokens = _semantic_tokens(request.get("query"))
    candidate_tokens = _semantic_tokens(' '.join(str(candidate.get(k) or '') for k in ('alt', 'description', 'caption')))
    if not query_tokens.intersection(candidate_tokens):
        return False
    if len(_tokens(candidate.get("alt"))) < 2:
        return False
    if request.get("kind") == "explanatory_visual":
        kind = _candidate_kind(candidate)
        visual_terms = set(_tokens(_candidate_text(candidate))) & _DIAGRAM_TERMS
        provider = candidate.get('provider') or provenance.get('provider')
        return (kind in _DIAGRAM_KINDS or any(term in kind for term in _DIAGRAM_TERMS) or bool(visual_terms)) and provider not in {"pexels", "stock"}
    return True


def _alt_for(slot: dict[str, Any], candidate: dict[str, Any], title: str) -> str:
    # A provider result with no own description must not receive invented
    # photographic alt text from the article title. The editor can still add it
    # manually before attachment.
    if not candidate.get("alt") and candidate.get("provider") and not candidate.get("current"):
        return ""
    value = str(candidate.get("alt") or slot.get("alt") or slot.get("brief") or title or "Editorial visual")
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:180] or "Editorial visual"


def build_suggestion(slot: dict[str, Any], candidates: Iterable[dict[str, Any]], title: str = "", limit: int = MAX_CANDIDATES) -> dict[str, Any]:
    """Return a UI-ready, review-required suggestion for one image slot."""
    request = derive_query(slot, title)
    ranked = rank_candidates(candidates, request, limit)
    default = next((candidate for candidate in ranked if candidate.get("eligible_default")), None)
    prepared = []
    for candidate in ranked:
        alt = _alt_for(slot, candidate, title)
        provenance = candidate.get("provenance") if isinstance(candidate.get("provenance"), dict) else {}
        library = bool(candidate.get("source") == "project" or candidate.get("asset_id"))
        asset_kind = _candidate_kind(candidate)
        caption = candidate.get("caption") or (f"{alt}." if request["kind"] == "explanatory_visual" and not candidate.get("current") else "")
        prepared.append({
            **candidate,
            "kind": "library" if library else "stock",
            "visual_kind": asset_kind,
            "provider_id": candidate.get("provider_id"),
            "thumbnail_url": candidate.get("thumbnail_url") or candidate.get("thumbnail") or candidate.get("url"),
            "alt": alt,
            "caption": caption,
            "suggested_alt": alt,
            "suggested_caption": candidate.get("caption") or (f"{alt}." if request["kind"] == "explanatory_visual" else ""),
            "provenance": provenance,
            "reviewed": False,
            "requires_review": True,
        })
    def key(candidate: dict[str, Any]) -> str:
        return str(candidate.get("id") or candidate.get("asset_id") or candidate.get("provider_id") or candidate.get("url") or "")
    selected = next((candidate for candidate in prepared if default and key(candidate) == key(default)), None)
    return {
        **request,
        "candidates": prepared,
        "default": selected,
        "default_requires_review": selected is not None,
        "needs_custom_visual": request["requires_custom_visual"] and selected is None,
    }


def _current_candidate(slot: dict[str, Any]) -> dict[str, Any] | None:
    url = slot.get("url") or slot.get("image_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    asset = slot.get("asset") or slot.get("asset_metadata") or {}
    return {
        "id": asset.get("id") or "current",
        "asset_id": asset.get("id"),
        "source": "project",
        "current": True,
        "url": url,
        "alt": slot.get("alt") or asset.get("alt") or "",
        "caption": slot.get("caption") or asset.get("caption") or "",
        "provenance": asset.get("provenance") if isinstance(asset, dict) else {},
    }


def suggest_slots(blocks: Iterable[dict[str, Any]], library_candidates: Iterable[dict[str, Any]] = (),
                  stock_candidates: Iterable[dict[str, Any]] = (), title: str = "", limit: int = MAX_CANDIDATES) -> dict[str, Any]:
    """Return the dashboard contract for every image slot in an article.

    Existing resolved assets are placed first and marked as current, but remain
    ``reviewed=False`` in this suggestion result unless the caller has a
    separately recorded review. Provider results are candidates only and never
    become article URLs through this helper.
    """
    slots = []
    queries = []
    library = list(library_candidates or [])
    stock = list(stock_candidates or [])
    for index, slot in enumerate(blocks or []):
        if not isinstance(slot, dict) or slot.get("type") != "image_slot":
            continue
        request = derive_query(slot, title)
        query = request["query"]
        queries.append(query)
        current = _current_candidate(slot)
        candidates = ([current] if current else []) + library + stock
        suggestion = build_suggestion(slot, candidates, title, limit)
        if suggestion["default"] is not None:
            reason = "Conservative visual match selected; review alt text, provenance and rights before attaching."
        elif suggestion["needs_custom_visual"]:
            reason = "This slot describes an explanatory visual. No stock default was selected; use a reviewed diagram or illustration."
        else:
            reason = "No conservative default selected. Review the candidates before attaching an image."
        slots.append({
            "index": index,
            "query": query,
            "reason": reason,
            "kind": request["kind"],
            "candidates": suggestion["candidates"],
            "default": suggestion["default"],
            "requires_review": True,
        })
    return {"slots": slots, "queries": queries, "count": len(slots)}

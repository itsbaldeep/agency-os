"""Pure, deterministic quality checks for article outlines and composed drafts.

This module intentionally has no database, network, storage, or model dependency.
It is suitable for both worker gates and dashboard preview diagnostics.  A draft
may be saved with warnings, but publication must have no blocking findings.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


_BLOCK_TYPES = {
    "intro", "prose", "heading", "key_takeaways", "steps", "table",
    "chart", "callout", "image_slot", "faq", "editorial_visual",
}
_EVIDENCE_TYPES = {"table", "chart", "callout"}
_PLACEHOLDER_RE = re.compile(
    r"(?:\[\s*(?:placeholder|insert|todo|tbd)[^\]]*\]|"
    r"\b(?:image\s+placeholder|concept\s+placeholder|lorem\s+ipsum|tbd|todo)\b)",
    re.IGNORECASE,
)
_FAQ_RE = re.compile(r"\b(?:faq|frequently\s+asked\s+questions)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    block_index: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _visible_text(block: dict[str, Any]) -> str:
    values: list[str] = []
    # brief/prompt are production metadata, not reader-visible copy. Including
    # them here would reject a valid article merely because its asset brief
    # contains the word "placeholder".
    for key in ("heading", "markdown", "answer", "question", "stat", "label", "alt", "title"):
        value = block.get(key)
        if isinstance(value, str):
            values.append(value)
    for key in ("points", "steps"):
        value = block.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value if item is not None)
    return " ".join(values)


def _severity(mode: str) -> str:
    return "blocker" if mode == "publish" else "warning"


def _add(findings: list[Finding], mode: str, code: str, message: str, index: int | None = None) -> None:
    findings.append(Finding(code, _severity(mode), message, index))


def validate_content(blocks: Any, mode: str = "draft") -> dict[str, Any]:
    """Return deterministic findings for an outline or composed content array.

    ``mode`` is ``draft`` (warnings are reviewable and saving remains possible)
    or ``publish`` (the same findings are blockers).  The check never mutates
    its input and returns stable codes suitable for API/UI contracts.
    """
    if mode not in {"draft", "publish"}:
        raise ValueError("mode must be 'draft' or 'publish'")
    findings: list[Finding] = []
    if not isinstance(blocks, list) or not blocks:
        _add(findings, mode, "empty_content", "content must contain at least one block")
        return _result(findings)

    valid: list[tuple[int, dict[str, Any]]] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            _add(findings, mode, "invalid_block", "block is not an object", index)
            continue
        valid.append((index, block))
        block_type = block.get("type")
        if block_type not in _BLOCK_TYPES:
            _add(findings, mode, "unknown_block_type", f"unknown block type: {block_type!r}", index)
            continue
        _validate_payload(findings, mode, index, block)
        if _PLACEHOLDER_RE.search(_visible_text(block)):
            _add(findings, mode, "placeholder_text", "reader-visible placeholder text remains", index)

    # A heading at the end, or immediately before only other headings, has no
    # body.  FAQ headings are stricter: an answer block must occur after them.
    for position, (index, block) in enumerate(valid):
        if block.get("type") != "heading":
            continue
        heading = _text(block.get("markdown") or block.get("heading") or block.get("brief"))
        next_block = valid[position + 1][1] if position + 1 < len(valid) else None
        following = [b for _, b in valid[position + 1:] if b.get("type") != "heading"]
        if next_block is None or next_block.get("type") == "heading" or not following:
            _add(findings, mode, "orphan_heading", "heading has no following content", index)
        if _FAQ_RE.search(heading):
            faq_after = any(b.get("type") == "faq" and (_text(b.get("brief")) or _text(b.get("question")))
                            for _, b in valid[position + 1:])
            if not faq_after:
                _add(findings, mode, "empty_faq", "FAQ heading has no answered FAQ blocks after it", index)

    return _result(findings)


def _validate_payload(findings: list[Finding], mode: str, index: int, block: dict[str, Any]) -> None:
    block_type = block.get("type")
    if block_type in {"intro", "prose"} and not _text(block.get("markdown")):
        _add(findings, mode, "empty_payload", f"{block_type} requires non-empty markdown", index)
    elif block_type == "heading" and not _text(block.get("heading") or block.get("brief")):
        _add(findings, mode, "empty_payload", "heading requires text", index)
    elif block_type == "key_takeaways":
        points = block.get("points")
        if not isinstance(points, list) or not points or not all(_text(str(p)) for p in points):
            _add(findings, mode, "empty_payload", "key_takeaways requires non-empty points", index)
    elif block_type == "steps":
        steps = block.get("steps")
        if not isinstance(steps, list) or len(steps) < 2 or not all(_text(str(s)) for s in steps):
            _add(findings, mode, "empty_payload", "steps requires at least two non-empty steps", index)
    elif block_type == "table":
        columns, rows = block.get("columns"), block.get("rows")
        if not isinstance(columns, list) or len(columns) < 2 or not all(_text(str(c)) for c in columns):
            _add(findings, mode, "empty_payload", "table requires at least two non-empty columns", index)
        if not isinstance(rows, list) or not rows or not all(isinstance(row, list) and len(row) == len(columns or []) for row in rows):
            _add(findings, mode, "empty_payload", "table requires rows matching its columns", index)
    elif block_type == "chart":
        series = block.get("data_series") or {}
        if isinstance(series, dict):
            labels, values = series.get("labels"), series.get("values")
        else:
            labels, values = None, None
        if not isinstance(labels, list) or not isinstance(values, list) or not labels or len(labels) != len(values):
            _add(findings, mode, "empty_payload", "chart requires equal non-empty labels and values", index)
    elif block_type == "callout" and (not _text(block.get("stat")) or not _text(block.get("label"))):
        _add(findings, mode, "empty_payload", "callout requires stat and label", index)
    elif block_type == "faq" and (not _text(block.get("brief") or block.get("question")) or not _text(block.get("answer"))):
        _add(findings, mode, "empty_payload", "FAQ requires a question and answer", index)
    elif block_type == "image_slot":
        if not _text(block.get("alt")):
            _add(findings, mode, "missing_alt", "image_slot requires descriptive alt text", index)
        url = _text(block.get("image_url") or block.get("url"))
        if not url:
            _add(findings, mode, "unresolved_image", "image_slot has no resolved asset URL", index)
        elif "placeholder" in url.lower() or "imgph" in url.lower():
            _add(findings, mode, "placeholder_asset", "image_slot points to a placeholder asset", index)
    elif block_type == "editorial_visual":
        if block.get("kind") in {"image", "photo"}:
            if not _text(block.get("image_url") or block.get("url")):
                _add(findings, mode, "unresolved_image", "editorial image has no asset URL", index)
            if not _text(block.get("alt")):
                _add(findings, mode, "missing_alt", "editorial image requires descriptive alt text", index)

    if block_type in _EVIDENCE_TYPES:
        if not isinstance(block.get("fact_ids"), list) or not block.get("fact_ids"):
            _add(findings, mode, "missing_evidence", f"{block_type} requires verified fact_ids", index)
        if not isinstance(block.get("sources"), list) or not block.get("sources"):
            _add(findings, mode, "missing_sources", f"{block_type} requires source URLs", index)


def _result(findings: Iterable[Finding]) -> dict[str, Any]:
    items = list(findings)
    return {
        "ok": not items,
        "blocking": any(item.severity == "blocker" for item in items),
        "findings": [item.as_dict() for item in items],
    }


def publication_blockers(blocks: Any) -> list[dict[str, Any]]:
    """Convenience API for worker/publisher gates."""
    return validate_content(blocks, "publish")["findings"]

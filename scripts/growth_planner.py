"""Evidence bounded TrueApply content recommendations after SEO refreshes."""
from __future__ import annotations
import re

MAX_ARTICLES, MAX_HELP = 3, 3
QUERY_RE = re.compile(r"\b(resume|résumé|resum|tailor|tailoring|job|application|ats|cover letter|career|experience|bullet|profile|match)\b", re.I)
TECHNICAL_RULES = frozenset({"missing_title", "missing_description", "duplicate_title", "duplicate_description", "missing_jsonld", "invalid_jsonld", "canonical_mismatch", "sitemap_redirect", "indexable_absent_sitemap"})
OWNER_HELP = ("How to upload and build your TrueApply profile", "How to review your TrueApply profile", "How to read an evidence match and create a tailored kit")

def _query_rows(audit):
    query = ((audit or {}).get("sources") or {}).get("gsc", {})
    return ((query or {}).get("query") or {}).get("row_summaries") or []

def _query_value(row):
    values = row.get("keys") if isinstance(row, dict) else []
    return str(values[0]).strip() if values else ""

def _candidate(query, rank, audit_id=None):
    return {"kind": "article", "title": query[:120].capitalize(), "target_keyword": query[:200], "rank": rank,
            "evidence": {"source": "gsc_query", "query": query, "audit_id": audit_id}, "evidence_status": "verified_query",
            "rationale": "Current GSC query evidence supports this topic; volume and conversion demand remain unverified.", "status": "suggested"}

def _title_key(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()

def recommend(audit, existing=None, *, max_articles=MAX_ARTICLES, max_help=MAX_HELP, owner_feedback=False):
    """Return article/help queues plus repairs, preserving human entries."""
    audit = audit if isinstance(audit, dict) else {}; existing = existing if isinstance(existing, list) else []
    competitors = audit.get("competitor_urls") or ((audit.get("sources") or {}).get("competitor_urls") or [])
    if not competitors:
        competitors = [row.get("url") for row in (audit.get("competitors") or []) if isinstance(row, dict) and row.get("url")]
    active = {"accepted", "scheduled", "research_queued", "in_progress", "outline", "draft", "calendar", "planned"}
    def dedupe(items):
        out, keys = [], set()
        for item in items:
            key = _title_key(item.get("title"))
            if key and key not in keys:
                out.append(item); keys.add(key)
        return out
    articles = dedupe([dict(x) for x in existing if x.get("kind", "article") == "article" and x.get("status", "suggested") in active])[:max_articles]
    helps = dedupe([dict(x) for x in existing if x.get("kind") == "help" and x.get("status", "suggested") in active])[:max_help]
    seen = {("article", _title_key(x.get("title"))) for x in articles}
    seen.update(("help", _title_key(x.get("title"))) for x in helps)
    repairs = []
    for finding in audit.get("findings") or []:
        if isinstance(finding, dict) and finding.get("rule") in TECHNICAL_RULES:
            repairs.append({"kind": "repair", "rule": finding.get("rule"), "url": finding.get("url"), "evidence": finding.get("evidence_id"), "rationale": "Repair the existing page using deterministic SEO evidence."})
    ranked = []
    for row in _query_rows(audit):
        query = _query_value(row)
        if query and QUERY_RE.search(query) and query.lower() not in {"truepal", "how well known"}:
            ranked.append((float(row.get("impressions") or 0), float(row.get("clicks") or 0), query))
    ranked.sort(key=lambda x: (-x[0], -x[1], x[2].lower()))
    for _impressions, _clicks, query in ranked:
        if len(articles) >= max_articles: break
        candidate = _candidate(query, len(articles) + 1, audit.get("audit_id"))
        candidate["competitor_urls"] = [str(url) for url in competitors[:5]]
        if ("article", _title_key(candidate["title"])) not in seen:
            articles.append(candidate); seen.add(("article", _title_key(candidate["title"])))
    if owner_feedback:
        for title in OWNER_HELP:
            if len(helps) >= max_help: break
            if ("help", _title_key(title)) in seen: continue
            helps.append({"kind": "help", "title": title, "target_keyword": "", "rank": len(helps) + 1,
                          "evidence": {"source": "owner_feedback", "audit_id": audit.get("audit_id")}, "evidence_status": "owner_feedback",
                          "rationale": "Repeated onboarding confusion supports this help topic; search demand is unverified.", "status": "suggested"})
            seen.add(("help", _title_key(title)))
    activation = audit.get("activation") or {}
    cohort = activation.get("signup_cohort_totals") or {}
    gaps = []
    if cohort.get("signups", 0) and cohort.get("resume_processed", 0) < cohort.get("signups", 0):
        gaps.append({"kind": "activation", "hypothesis": "Some signups do not reach resume processing; improve first-use guidance before claiming content demand.", "evidence": "activation"})
    if cohort.get("resume_processed", 0) and cohort.get("kit_completed", 0) < cohort.get("resume_processed", 0):
        gaps.append({"kind": "activation", "hypothesis": "Users drop between resume processing and kit completion; inspect onboarding and help coverage.", "evidence": "activation"})
    crawl_pages = (((audit.get("sources") or {}).get("crawl") or {}).get("pages") or [])
    gaps.append({"kind": "coverage", "hypothesis": "Current owned pages should be checked for overlap before adding a topic.", "evidence": {"owned_pages": len(crawl_pages), "competitor_urls": [str(url) for url in (audit.get("competitor_urls") or [])[:5]], "competitor_evidence": bool((audit.get("competitors") or (audit.get("sources") or {}).get("competitors")) or audit.get("competitor_urls")), "activation_cohort_available": bool(cohort)}})
    return {"articles": articles, "article": articles, "help": helps, "repairs": repairs[:50], "gaps": gaps,
            "evidence_available": bool(ranked or repairs or owner_feedback or cohort or crawl_pages)}

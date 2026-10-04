"""Evidence-bounded content recommendations after SEO refreshes."""
from __future__ import annotations
import re

MAX_ARTICLES, MAX_HELP = 3, 3
TECHNICAL_RULES = frozenset({"missing_title", "missing_description", "duplicate_title", "duplicate_description", "missing_jsonld", "invalid_jsonld", "canonical_mismatch", "sitemap_redirect", "indexable_absent_sitemap"})

def _query_rows(audit):
    query = ((audit or {}).get("sources") or {}).get("gsc", {})
    return ((query or {}).get("query") or {}).get("row_summaries") or []

def _query_value(row):
    values = row.get("keys") if isinstance(row, dict) else []
    return str(values[0]).strip() if values else ""


def _brand_context(audit):
    context = (audit or {}).get("brand_context")
    return context if isinstance(context, dict) else {}


def _query_re(audit):
    terms = _brand_context(audit).get("query_terms")
    if isinstance(terms, str):
        terms = [terms]
    terms = [str(term).strip() for term in (terms or []) if str(term).strip()]
    return re.compile("|".join(re.escape(term) for term in terms), re.I) if terms else None

def _candidate(query, rank, audit_id=None):
    return {"kind": "article", "title": query[:120].capitalize(), "target_keyword": query[:200], "rank": rank,
            "evidence": {"source": "gsc_query", "query": query, "audit_id": audit_id}, "evidence_status": "verified_query",
            "rationale": "Current GSC query evidence supports this topic; volume and conversion demand remain unverified.", "status": "suggested"}

def _goal_candidates(audit, seen, competitors, audit_id):
    """Suggest bounded owner-goal coverage when query demand is unavailable."""
    pages = (((audit.get("sources") or {}).get("crawl") or {}).get("pages") or [])
    if not pages:
        return []
    inventory = " ".join(str((page.get("url") or "") + " " + str((page.get("fields") or {}).get("title") or "")).lower() for page in pages if isinstance(page, dict))
    goals = []
    for raw in _brand_context(audit).get("goals", []):
        if not isinstance(raw, dict) or not raw.get("title") or not raw.get("keyword"):
            continue
        goals.append((str(raw["title"])[:160], str(raw["keyword"])[:200], str(raw.get("hypothesis") or "Owner-supplied goal; search demand and conversion intent are unverified.")[:500]))
    out = []
    for title, keyword, hypothesis in goals:
        key = _title_key(title)
        if key in seen or any(token in inventory for token in ("chosen role", "evidence match", "career change" ) if token in title.lower()):
            continue
        out.append({"kind": "article", "title": title, "target_keyword": keyword, "rank": len(out) + 1,
                    "competitor_urls": [str(url) for url in competitors[:5]], "evidence": {"source": "owner_goal_coverage", "audit_id": audit_id, "owned_page_count": len(pages)},
                    "evidence_status": "owner_goal_hypothesis", "rationale": hypothesis + "; search demand and conversion intent are unverified.", "status": "suggested"})
    return out

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
    query_re = _query_re(audit)
    for row in _query_rows(audit):
        query = _query_value(row)
        if query and (query_re is None or query_re.search(query)):
            ranked.append((float(row.get("impressions") or 0), float(row.get("clicks") or 0), query))
    ranked.sort(key=lambda x: (-x[0], -x[1], x[2].lower()))
    for _impressions, _clicks, query in ranked:
        if len(articles) >= max_articles: break
        candidate = _candidate(query, len(articles) + 1, audit.get("audit_id"))
        candidate["competitor_urls"] = [str(url) for url in competitors[:5]]
        if ("article", _title_key(candidate["title"])) not in seen:
            articles.append(candidate); seen.add(("article", _title_key(candidate["title"])))
    if owner_feedback and len(articles) < max_articles:
        for candidate in _goal_candidates(audit, seen, competitors, audit.get("audit_id")):
            if len(articles) >= max_articles:
                break
            articles.append(candidate); seen.add(("article", _title_key(candidate["title"])))
    help_topics = _brand_context(audit).get("help_topics")
    if isinstance(help_topics, str):
        help_topics = [help_topics]
    help_topics = [str(topic).strip()[:160] for topic in (help_topics or []) if str(topic).strip()]
    if owner_feedback and help_topics:
        for title in help_topics:
            if len(helps) >= max_help: break
            if ("help", _title_key(title)) in seen: continue
            helps.append({"kind": "help", "title": title, "target_keyword": "", "rank": len(helps) + 1,
                          "evidence": {"source": "owner_feedback", "audit_id": audit.get("audit_id")}, "evidence_status": "owner_feedback",
                          "rationale": "Repeated onboarding confusion supports this help topic; search demand is unverified.", "status": "suggested"})
            seen.add(("help", _title_key(title)))
    activation = audit.get("activation") or {}
    cohort = activation.get("signup_cohort_totals") or {}
    gaps = []
    for stage in _brand_context(audit).get("journey_stages", []):
        if not isinstance(stage, dict):
            continue
        source, target = stage.get("from"), stage.get("to")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        if isinstance(cohort.get(source), int) and isinstance(cohort.get(target), int) and cohort[source] and cohort[target] < cohort[source]:
            gaps.append({"kind": "activation", "hypothesis": str(stage.get("hypothesis") or "Observed journey-stage drop; inspect the supplied product guidance before claiming content demand.")[:500], "evidence": "activation", "from_stage": source, "to_stage": target})
    crawl_pages = (((audit.get("sources") or {}).get("crawl") or {}).get("pages") or [])
    gaps.append({"kind": "coverage", "hypothesis": "Current owned pages should be checked for overlap before adding a topic.", "evidence": {"owned_pages": len(crawl_pages), "competitor_urls": [str(url) for url in (audit.get("competitor_urls") or [])[:5]], "competitor_evidence": bool((audit.get("competitors") or (audit.get("sources") or {}).get("competitors")) or audit.get("competitor_urls")), "activation_cohort_available": bool(cohort)}})
    return {"articles": articles, "article": articles, "help": helps, "repairs": repairs[:50], "gaps": gaps,
            "evidence_available": bool(ranked or repairs or help_topics or cohort or crawl_pages)}

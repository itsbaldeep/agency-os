#!/usr/bin/env python3
"""suggestion-engine.py — generate prioritized, source-traced, compliance-checked suggestions from audit data."""
import json, urllib.request, sys, os, socket, re, time

ENV_PATH = os.environ.get("AGENCY_ENV_FILE", "/home/agency/.config/agency/core.env")
for line in open(ENV_PATH):
    lp = line.strip()
    if "=" in lp and not lp.startswith("#"):
        k, v = lp.split("=", 1)
        os.environ[k] = v
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com").rstrip("/")
ZEN_URL = OPENAI_BASE_URL + "/chat/completions"
ZEN_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

MODEL_CONFIG = {
    "quality": "deepseek-v4-pro",           # suggestion generation
    "temp_structured": 0.1,                # low temperature for JSON output
}

FREE_FALLBACK_MODELS = (
    ("https://api.z.ai/api/paas/v4", "ZAI_API_KEY", "glm-4.5-flash"),
    ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
     os.environ.get("OPENROUTER_FREE_MODEL", "deepseek/deepseek-r1:free")),
)

def zen(prompt, max_tokens=1200, temperature=None, json_mode=False,
        _fb_index=0, _base_url=None, _api_key=None, _model=None):
    model = _model or MODEL_CONFIG["quality"]
    base_url = (_base_url or OPENAI_BASE_URL).rstrip("/")
    api_key = ZEN_KEY if _api_key is None else _api_key
    body_dict = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}
    if temperature is not None:
        body_dict["temperature"] = temperature
    if "api.deepseek.com" in base_url:
        body_dict["thinking"] = {"type": "disabled"}
        if json_mode:
            body_dict["response_format"] = {"type": "json_object"}
    body = json.dumps(body_dict).encode()
    req = urllib.request.Request(base_url + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "AgencyOS-Suggestions/1.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        c = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        return {"ok": True, "content": c, "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0), "model": model}
    except Exception as e:
        emsg = str(e)[:300]
        error_text = emsg.lower()
        status_code = getattr(e, "code", None)
        # Credits exhausted or free-model rate-limited → try the next fallback model
        if _fb_index < len(FREE_FALLBACK_MODELS) and (
            "creditserror" in error_text or "insufficient balance" in error_text
            or "freeusagelimiterror" in error_text or "rate limit" in error_text
            or status_code in (401, 402, 429)):
            for fb_index in range(_fb_index, len(FREE_FALLBACK_MODELS)):
                fb_base_url, fb_key_env, fb_model = FREE_FALLBACK_MODELS[fb_index]
                fb_key = os.environ.get(fb_key_env, "")
                if not fb_key:
                    print(f"[sug-engine] {fb_key_env} is unset; skipping {fb_model}", flush=True)
                    continue
                print(f"[sug-engine] LLM {model} blocked, falling back to {fb_model} at {fb_base_url}", flush=True)
                return zen(prompt, max_tokens=max_tokens, temperature=temperature, json_mode=json_mode,
                           _fb_index=fb_index + 1, _base_url=fb_base_url,
                           _api_key=fb_key, _model=fb_model)
        return {"ok": False, "error": emsg, "model": model}

SUPERLATIVE_PATTERNS = re.compile(r'\b(cleanest|best|greatest|number one|top rated|leading|most popular|the best)\b', re.IGNORECASE)
HEALTH_CLAIM_PATTERNS = re.compile(r'\b(cure|heal|treat|prevent|reduce risk|boost immunity|detox|cleanse)\b', re.IGNORECASE)

REMEDIATIVE_ACTIONS = re.compile(r'\b(remove|rewrite|update|revise|replace|drop|substantiate|back.?up|cite|source|qualify|tone.?down|fix|correct|retire|retract)\b', re.IGNORECASE)
AMPLIFYING_ACTIONS = re.compile(r'\b(create|launch|build|produce|write|develop|campaign|advertise?|promote|publish|start|roll.?out|produce)\b', re.IGNORECASE)
SUPERLATIVE_PATTERNS = re.compile(r'\b(cleanest|best|greatest|number one|top rated|leading|most popular|the best|highest quality|premium quality)\b', re.IGNORECASE)
HEALTH_CLAIM_PATTERNS = re.compile(r'\b(cure|heal|treat|prevent|reduce risk|boost immunity|detox|cleanse|antibacterial|antimicrobial)\b', re.IGNORECASE)
REVIEW_INCENTIVE = re.compile(r'\b(incentiv(e|ise)|discount.*review|review.*(earn|reward|coupon|gift|swap|program)|gift.*review)\b', re.IGNORECASE)

def check_compliance(title, rationale):
    """Judge the EFFECT of executing the suggestion — does it CREATE or REMOVE risk?"""
    flags = []
    combined = (title + " " + rationale).lower()

    is_remediative = bool(REMEDIATIVE_ACTIONS.search(combined))
    is_amplifying = bool(AMPLIFYING_ACTIONS.search(combined))
    has_superlative = bool(SUPERLATIVE_PATTERNS.search(combined))
    has_health_claim = bool(HEALTH_CLAIM_PATTERNS.search(combined))
    has_review_incentive = bool(REVIEW_INCENTIVE.search(combined))

    # Superlative / health-claim risk: only flag if the suggestion would CREATE or AMPLIFY the claim.
    # A remediative suggestion (e.g. "remove the unsubstantiated superlative") is the fix — clean.
    if (has_superlative or has_health_claim) and is_amplifying and not is_remediative:
        if has_superlative:
            flags.append({"type": "amplified_superlative_claim", "severity": "yellow",
                          "detail": "This content would lean on an unsubstantiated superlative claim. Substantiate or qualify the claim before publishing, or flag it as marketing language."})
        if has_health_claim:
            flags.append({"type": "amplified_health_claim", "severity": "red",
                          "detail": "This content would amplify a health claim without clinical evidence. Not permitted for food/beverage marketing in most jurisdictions."})

    # Review incentives: flag unless the suggestion is to STOP or REMOVE the incentive.
    if has_review_incentive:
        stops_incentive = bool(re.search(r'\b(stop|remove|avoid|retire|end|halt|discontinue)\b', combined))
        if not stops_incentive:
            flags.append({"type": "platform_tos_reviews", "severity": "yellow",
                          "detail": "Incentivized reviews may violate Amazon/Google/Shopify ToS and FTC endorsement guidelines. Must be disclosed and comply with platform-specific policies."})

    # Marketplace tactics: flag if suggesting something new on a platform
    if is_amplifying and not is_remediative:
        if re.search(r'\b(amazon|flipkart|meesho|nykaa)\b', combined) and re.search(r'\b(listing|a\+|rating|seller)\b', combined):
            flags.append({"type": "marketplace_restriction", "severity": "yellow",
                          "detail": "Marketplace-specific tactic — verify against platform seller policies before execution."})

    return flags

def compute_impact(action_type, channel, category):
    channel = (channel or "").lower()
    action_type = (action_type or "").lower()
    cat_lower = (category or "").lower()

    if "quick-commerce" in channel or "marketplace" in channel:
        if "listing" in action_type or "rating" in action_type or "review" in action_type or "marketplace" in action_type:
            return "high"
        if "schema" in action_type or "structured data" in action_type:
            return "high"
        if "content" in action_type or "blog" in action_type or "pillar" in action_type:
            return "medium"
        return "medium"

    if "dtc" in channel or "ecommerce" in channel or "direct" in channel:
        if "content" in action_type or "pillar" in action_type or "seo" in action_type:
            return "high"
        if "schema" in action_type or "structured data" in action_type:
            return "high"
        if "comparison" in action_type or "competitive" in action_type:
            return "high"
        return "medium"

    if "retail" in channel:
        if "comparison" in action_type or "shelf" in action_type or "distributor" in action_type:
            return "high"
        if "packaging" in action_type or "label" in action_type:
            return "high"
        return "medium"

    if "wholesale" in channel or "b2b" in channel:
        if "case stud" in action_type or "technical" in action_type or "spec" in action_type:
            return "high"
        return "medium"

    return "medium"


def generate_suggestions(brand_id, audit_id, summary, biz_info, crawl_text, confidence, competitor_gap):
    category = biz_info.get("category") or "unknown"
    positioning = biz_info.get("positioning") or ""
    flagship = biz_info.get("flagship_product") or ""
    channel = biz_info.get("primary_sales_channel") or "DTC ecommerce"
    stage = biz_info.get("business_stage") or "early"
    visibility_blocked = confidence == "low"
    brand_cited = summary.get("brand_cited_count", 0)
    total_prompts = summary.get("prompts_queried", 0)
    share_pct = summary.get("brand_share_of_voice_pct", 0)
    comp_citations = summary.get("competitor_citation_counts", {})

    chan = channel.lower()
    high_for_channel = []
    medium_for_channel = []
    if "quick-commerce" in chan or "marketplace" in chan:
        high_for_channel = ["listing optimization", "ratings", "reviews", "marketplace SEO", "product page schema", "structured data"]
        medium_for_channel = ["blog", "content", "long-form"]
    elif "dtc" in chan or "ecommerce" in chan:
        high_for_channel = ["content marketing", "organic SEO", "conversion", "product schema", "comparison", "pillar", "structured data"]
        medium_for_channel = ["social", "email"]
    elif "retail" in chan:
        high_for_channel = ["shelf", "comparison", "distributor", "packaging", "label", "transparency"]
        medium_for_channel = ["blog", "social"]
    else:
        high_for_channel = ["technical", "spec", "case study", "b2b content"]
        medium_for_channel = ["general"]

    visibility_note = ""
    competitor_note = ""
    if visibility_blocked:
        visibility_note = "Visibility confidence is LOW. Do NOT suggest anything about AI visibility or LLM citations. Only suggest from: technical site issues, flagship product, channel optimization."
    if competitor_gap:
        competitor_note = "No competitors found. Do NOT suggest competitor comparisons."

    brand_context = crawl_text[:500].strip() if crawl_text else ""
    prompt = f"""Suggest 6-10 brand improvements for a {category} brand (flagship: {flagship}, channel: {channel}, stage: {stage}).

About the brand: {brand_context[:300]}

{visibility_note}
{competitor_note}

For this channel, HIGH impact = {', '.join(high_for_channel)}. MEDIUM = {', '.join(medium_for_channel)}.

Check each for compliance: superlatives without evidence = RED, health claims = RED, incentivized reviews = YELLOW.

Return ONLY a JSON object with a "suggestions" array. Example:
{{"suggestions":[{{"title":"Add product schema","rationale":"Structured data helps search engines understand products.","impact":"high","effort":"medium","action_type":"monitor","compliance_flags":[],"sources":[{{"type":"audit_finding","finding":"No schema found on homepage"}}]}}]}}"""

    suggestions = None
    last_raw = ""
    total_prompt_tokens = total_completion_tokens = 0
    total_cost = 0.0
    last_model = MODEL_CONFIG["quality"]
    for attempt in range(2):
        r = zen(prompt, max_tokens=1800, json_mode=True)
        total_prompt_tokens += r.get("prompt_tokens", 0)
        total_completion_tokens += r.get("completion_tokens", 0)
        total_cost += r.get("cost", 0)
        last_model = r.get("model") or last_model
        if not r["ok"]:
            continue
        last_raw = r["content"]
        for trim in [last_raw, last_raw[last_raw.find('['):last_raw.rfind(']')+1] if '[' in last_raw else '']:
            trim = trim.strip()
            if not trim:
                continue
            try:
                data = json.loads(trim)
                if isinstance(data, dict) and isinstance(data.get("suggestions"), list):
                    suggestions = data["suggestions"]
                    break
            except:
                continue
        if suggestions:
            break
        if attempt < 1:
            prompt += "\n\nSTRICT: Return ONLY a JSON object with a suggestions array. No other text."

    if suggestions is None:
        return {"ok": False, "error": "Could not parse suggestion output as JSON after 2 attempts",
                "prompt_tokens": total_prompt_tokens, "completion_tokens": total_completion_tokens,
                "cost": round(total_cost, 8), "model": last_model}

    validated = []
    for s in suggestions:
        title = s.get("title", "").strip()
        rationale = s.get("rationale", "").strip()
        if not title or not rationale:
            continue

        combined_lower = (title + " " + rationale).lower()
        is_visibility_only = False
        if visibility_blocked:
            visibility_keywords = ["visibility", "cited", "llm", "ai mention", "ai response"]
            non_visibility_grounding = ["schema", "meta", "heading", "structured data", "flagship", "product page",
                                         "channel", "listing", "rating", "review", "comparison", "delivery",
                                         "logistics", "label", "nutrition", "certification", "seo", "content strategy",
                                         "pillar", "blog", "technical"]
            only_visibility = any(kw in combined_lower for kw in visibility_keywords)
            has_grounding = any(kw in combined_lower for kw in non_visibility_grounding)
            is_visibility_only = only_visibility and not has_grounding

        if is_visibility_only:
            continue

        if competitor_gap:
            comp_keywords = ["competitor", "comparison", "vs ", "versus", "cross-shop"]
            is_competitive = any(kw in combined_lower for kw in comp_keywords)
            if is_competitive:
                continue

        compliance = s.get("compliance_flags", [])
        if not compliance:
            compliance = check_compliance(title, rationale)

        action_type = s.get("action_type", "monitor")
        computed = compute_impact(action_type, channel, category)
        final_impact = s.get("impact", computed)

        validated.append({
            "title": title,
            "rationale": rationale,
            "impact": final_impact,
            "effort": s.get("effort", "medium"),
            "action_type": action_type,
            "compliance_flags": compliance,
            "sources": s.get("sources", [{"type": "audit_finding", "finding": f"From audit {audit_id}"}]),
        })

    return {"ok": True, "suggestions": validated, "count": len(validated),
            "prompt_tokens": total_prompt_tokens, "completion_tokens": total_completion_tokens,
            "cost": round(total_cost, 8), "model": last_model}


if __name__ == "__main__":
    print("suggestion-engine.py — import and call generate_suggestions()", flush=True)

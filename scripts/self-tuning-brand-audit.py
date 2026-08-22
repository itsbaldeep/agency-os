#!/usr/bin/env python3
"""self-tuning-brand-audit.py — run a full black-box audit given only a domain.

Usage: python3 self-tuning-brand-audit.py brevo.com
       python3 self-tuning-brand-audit.py brevo.com --brand-id 1  (re-run on existing brand)

Steps:
  1. Crawl homepage → extract text
  2. Zen: classify category/positioning from homepage text
  3. Zen: propose 3 competitors for this category
  4. Zen: generate 12-15 brand-neutral buying-intent prompts for the category
  5. Record all assumptions (category, competitors, prompts) on the brand
  6. Run ai-visibility-audit against Zen with the generated prompts
  7. Write results to ClickHouse + update audit record
"""
import json, os, sys, time, urllib.request, urllib.error, base64, socket, re, subprocess

# ── config ────────────────────────────────────────────────────────────────────
ENV_PATH = "/home/agency/agency-os/.env"
OPENAI_BASE_URL = "https://api.deepseek.com"
ZEN_URL = ""
ZEN_KEY = ""
CH_AUTH = ""
CH_HOST = "http://100.64.0.1:8123"
DB_HOST = "100.64.0.1"
DB_NAME = "agencyos"
DB_USER = "agency"
DB_PASS = ""

def load_env():
    global OPENAI_BASE_URL, ZEN_URL, ZEN_KEY, CH_AUTH, DB_PASS
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if "=" not in line or line.startswith("#"): continue
            k, v = line.split("=", 1)
            os.environ[k] = v
            if k == "OPENAI_BASE_URL": OPENAI_BASE_URL = v.rstrip("/")
            elif k == "DEEPSEEK_API_KEY": ZEN_KEY = v
            elif k == "CLICKHOUSE_PASSWORD": CH_AUTH = base64.b64encode(f"agency:{v}".encode()).decode()
            elif k == "POSTGRES_PASSWORD": DB_PASS = v
load_env()
ZEN_URL = OPENAI_BASE_URL + "/chat/completions"

import psycopg2, psycopg2.extras

def db():
    return psycopg2.connect(host=DB_HOST, port=5432, dbname=DB_NAME, user=DB_USER, password=DB_PASS)

FREE_FALLBACK_MODELS = (
    ("https://api.z.ai/api/paas/v4", "ZAI_API_KEY", "glm-4.5-flash"),
    ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
     os.environ.get("OPENROUTER_FREE_MODEL", "deepseek/deepseek-r1:free")),
)

def zen(prompt, model="deepseek-chat", max_tokens=800, _fb_index=0, _base_url=None, _api_key=None):
    model = "deepseek-chat" if model in ("deepseek-v4-flash", "glm-5.2") else model
    base_url = (_base_url or OPENAI_BASE_URL).rstrip("/")
    api_key = ZEN_KEY if _api_key is None else _api_key
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(base_url + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "AgencyOS-Audit/1.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        c = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        return {"ok": True, "content": c, "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0), "model": model}
    except Exception as e:
        emsg = str(e)[:300]
        # Credits exhausted or free-model rate-limited → try the next fallback model
        if _fb_index < len(FREE_FALLBACK_MODELS) and (
            "CreditsError" in emsg or "Insufficient balance" in emsg
            or "FreeUsageLimitError" in emsg or "Rate limit" in emsg
            or "401" in emsg or "429" in emsg):
            fb_base_url, fb_key_env, fb_model = FREE_FALLBACK_MODELS[_fb_index]
            fb_key = os.environ.get(fb_key_env, "")
            if not fb_key:
                return zen(prompt, model=model, max_tokens=max_tokens, _fb_index=_fb_index + 1)
            print(f"[audit] LLM {model} blocked, falling back to {fb_model} at {fb_base_url}", flush=True)
            return zen(prompt, model=fb_model, max_tokens=max_tokens, _fb_index=_fb_index + 1,
                       _base_url=fb_base_url, _api_key=fb_key)
        return {"ok": False, "error": emsg, "model": model}

def crawl_homepage(domain):
    urls = [f"https://{domain}", f"https://www.{domain}"]
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    for url in urls:
        print(f"  Crawling {url}...", flush=True)
        for attempt in range(2):
            try:
                result = subprocess.run(["curl", "-sL", "--max-time", "15", "-A", ua, url], capture_output=True, text=True, timeout=20)
                if result.returncode != 0 or len(result.stdout) < 500:
                    if result.stderr and "429" in result.stderr:
                        print(f"    429, retrying in 5s...", flush=True)
                        time.sleep(5)
                        continue
                    print(f"    {url}: empty response", flush=True)
                    break
                html = result.stdout
                # Strip scripts, styles, SVGs, noscript, head before extracting text
                clean_html = re.sub(r'<head[^>]*>.*?</head>', '', html, flags=re.DOTALL | re.IGNORECASE)
                clean_html = re.sub(r'<(script|style|svg|noscript|template)[^>]*>.*?</\1>', '', clean_html, flags=re.DOTALL | re.IGNORECASE)
                # Strip remaining inline style attributes and CSS-like content
                clean_html = re.sub(r'\sstyle="[^"]*"', '', clean_html)
                clean_html = re.sub(r'<!--.*?-->', '', clean_html, flags=re.DOTALL)
                text = re.sub(r'<[^>]+>', ' ', clean_html)
                text = re.sub(r'&[a-z]+;', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                # If text is mostly CSS-like garbage (lots of colons/braces), try extracting just visible text
                if text.count('{') > 10 or text.count(':') > len(text) * 0.05:
                    # Fallback: extract text from common content tags only
                    content_tags = re.findall(r'<(?:p|h[1-6]|li|a|span|div|td|strong|em)[^>]*>(.*?)</(?:p|h[1-6]|li|a|span|div|td|strong|em)>', html, flags=re.DOTALL | re.IGNORECASE)
                    if content_tags:
                        text = ' '.join(re.sub(r'<[^>]+>', ' ', ct) for ct in content_tags)
                        text = re.sub(r'\s+', ' ', text).strip()
                text = text[:3000]
                return {"ok": True, "text": text, "html_len": len(html), "url": url}
            except Exception as e:
                print(f"    {url}: {str(e)[:80]}", flush=True)
                break
    return {"ok": False, "error": f"Could not reach {domain} or www.{domain}"}

def classify_category(domain, homepage_text):
    prompt = f"""From the homepage text below, identify the single most specific business category / market vertical for this company. 
Output ONLY a JSON object with these fields:
- "category": the category (e.g. "email marketing platform", "CRM for small business", "ecommerce analytics", "project management software", "website builder")
- "positioning": a one-sentence description of how they position themselves
- "confidence": "high" if clear from text, "medium" if inferred, "low" if guessing

Homepage text:
{homepage_text[:2000]}"""
    r = zen(prompt)
    if not r["ok"]: return r
    try:
        data = json.loads(r["content"])
        return {"ok": True, "category": data.get("category","unknown"), "positioning": data.get("positioning",""), "confidence": data.get("confidence","medium"), "tokens": (r.get("prompt_tokens",0), r.get("completion_tokens",0))}
    except:
        return {"ok": True, "category": "unknown", "positioning": r["content"][:200], "confidence": "low", "raw": r["content"]}

def propose_competitors(domain, category, homepage_text):
    prompt = f"""You are a market researcher. Given a company's homepage text, identify its REAL competitors.

Company domain: {domain}
Category: {category}

Homepage text:
{homepage_text[:1500]}

From the text, infer: pricing model, target customer, and whether their go-to-market is self-serve or sales-led.

Then name exactly 3 competitors a REAL buyer would cross-shop — same price point, same target, same self-serve/sales model.

Respond ONLY with a valid JSON object (no markdown, no code fences):
{{"pricing_model":"...","target_customer":"...","go_to_market":"self-serve","competitors":[{{"name":"Company","domain":"company.com","why":"reason"}}]}}"""
    r = zen(prompt, max_tokens=1000)
    if not r["ok"]: return r
    raw = r["content"]
    print(f"      [DEBUG] Raw Zen response (first 500 chars): {raw[:500]}", flush=True)
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
    json_str = json_match.group(1) if json_match else raw
    for attempt_raw in [json_str, raw]:
        try:
            data = json.loads(attempt_raw)
            comps = data.get("competitors", [])
            return {"ok": True, "pricing_model": data.get("pricing_model","unknown"), "target_customer": data.get("target_customer","unknown"), "go_to_market": data.get("go_to_market","unknown"), "competitors": comps[:3], "raw": raw}
        except: pass
    comps = []
    for line in raw.split("\n"):
        line = line.strip()
        for prefix in ["- ", "* ", "1.", "2.", "3."]:
            if line.startswith(prefix):
                name = line.replace(prefix, "").strip().split("(")[0].strip()
                if name and len(name) < 60:
                    comps.append({"name": name, "domain": "", "why": ""})
    return {"ok": True, "competitors": comps[:3], "raw": raw, "pricing_model": "unknown", "target_customer": "unknown", "go_to_market": "unknown"}

def generate_prompts(category, positioning):
    prompt = f"""You are generating 15 brand-neutral buying-intent search prompts for market research on the category "{category}".
The company positions itself as: {positioning}

RULES (non-negotiable):
- NEVER include any brand name in any prompt
- Each prompt must be a realistic question a buyer would type into a search engine or AI
- Span the category's main concern areas (pricing, features, comparisons, use cases, integrations, alternatives, reviews, getting started)
- Output ONLY a JSON array of 15 strings, one per line

Example format for "email marketing":
["best email marketing tool for small business", "cheapest email automation for startups", ...]"""
    r = zen(prompt, max_tokens=1200)
    if not r["ok"]: return r
    raw = r["content"]
    print(f"      [DEBUG] Prompts raw (first 300): {raw[:300]}", flush=True)
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
    json_str = json_match.group(1) if json_match else raw
    for attempt_raw in [json_str, raw]:
        try:
            data = json.loads(attempt_raw)
            if isinstance(data, list):
                prompts = data
            elif isinstance(data, dict):
                prompts = list(data.values())[0] if data else []
            else:
                prompts = data
            if isinstance(prompts, list) and len(prompts) >= 5:
                return {"ok": True, "prompts": prompts[:15], "count": min(len(prompts), 15), "raw": raw}
        except: pass
    # Line-by-line fallback
    prompts = [l.strip().strip('"').strip("'").strip("[").strip("]").strip(",") for l in raw.split("\n") if l.strip().startswith('"') or (l.strip() and l.strip()[0].isdigit() and "." in l.strip()[:3])]
    prompts = [p for p in prompts if len(p) > 15]
    return {"ok": True, "prompts": prompts[:15], "count": min(len(prompts), 15), "raw": raw}

def run_audit(domain, brand_id, category, competitors, prompts, market_tier=None, brand_name="Brand", crawl_text=None):
    brand_lower = brand_name.lower()
    print(f"\n  Running {len(prompts)} visibility queries...", flush=True)
    # NOTE: do NOT pre-DELETE rows — ClickHouse mutations are expensive and can
    # stack up under memory pressure, blocking all subsequent INSERTs. Instead,
    # we just insert new rows with the current timestamp. The report page shows
    # the latest audit's rows by joining on audit_id (future) or by timestamp.
    
    results = []
    ch_failures = 0
    for i, prompt in enumerate(prompts):
        print(f"    [{i+1}/{len(prompts)}] Querying...", end=" ", flush=True)
        r = zen(prompt)
        if not r["ok"]:
            print(f"ERROR: {r.get('error','')}", flush=True)
            continue
        content = r["content"].lower()
        b = brand_lower in content
        brands_cited = []
        for comp in competitors:
            cn = comp.get("name","").lower()
            if cn and len(cn) >= 3 and cn in content:
                brands_cited.append(comp.get("name","?"))
        cited_comps = ",".join(brands_cited) if brands_cited else "none"
        print(f"cited={int(b)} others={cited_comps}", flush=True)
        results.append({"prompt": prompt, "cited": int(b), "competitors": cited_comps, "content": r["content"][:200]})
        detail = r["content"][:200].replace('\t',' ').replace('\n',' ')
        prompt_escaped = prompt.replace('\t',' ').replace('\n',' ')
        sql = f"INSERT INTO default.ai_visibility_checks (brand_id, engine, prompt, cited, position, competitors_cited, detail) FORMAT TabSeparated\n{brand_id}\tdeepseek/deepseek-chat\t{prompt_escaped}\t{int(b)}\t{i+1}\t{cited_comps}\t{detail}"
        try:
            req = urllib.request.Request(f"{CH_HOST}/", data=sql.encode(), headers={"Authorization": f"Basic {CH_AUTH}"})
            urllib.request.urlopen(req, timeout=10)
        except Exception as che:
            ch_failures += 1
            print(f"    [CH INSERT FAILED: {str(che)[:100]}]", flush=True)
        time.sleep(0.3)
    
    total = len(results)
    brand_cited = sum(r["cited"] for r in results)
    comp_cited_counts = {}
    for r in results:
        for cname in r.get("competitors","").split(","):
            cname = cname.strip()
            if cname and cname != "none":
                comp_cited_counts[cname] = comp_cited_counts.get(cname, 0) + 1
    print(f"\n  Results: {brand_name} {brand_cited}/{total} ({round(brand_cited/total*100)}%)", flush=True)
    for cname, cnt in sorted(comp_cited_counts.items(), key=lambda x:-x[1]):
        print(f"           {cname}: {cnt}/{total}", flush=True)
    
    # Update audit record
    conn = db()
    try:
        cur = conn.cursor()
        comp_citation_data = {}
        for cname, cnt in comp_cited_counts.items():
            comp_citation_data[cname] = cnt
        summary = json.dumps({
            "status":"completed","engine":"deepseek/deepseek-chat","methodology":"Self-tuning audit. Category auto-detected from crawl. Competitors auto-proposed. 15 brand-neutral prompts auto-generated.",
            "domain":domain,"category":category,
            "market_tier":market_tier or {"pricing_model":"?","target_customer":"?","go_to_market":"?"},
            "competitors":[{"name":c["name"],"domain":c.get("domain",""),"why":c.get("why","")} for c in competitors],
            "prompts_used":prompts,
            "prompts_queried":total,"brand_cited":brand_cited,
            "brand_share_of_voice_pct":round(brand_cited/total*100) if total else 0,
            "competitor_citation_counts":comp_citation_data,
            "all_competitors_total_citations":sum(comp_cited_counts.values()),
            "note":"Training-knowledge proxy — not live web AI-visibility. All prompts brand-neutral (no brand names in prompts). Competitors auto-proposed — verify before relying on.",
            "ch_insert_failures": ch_failures
        })
        sources = json.dumps([{"type":"self_tuning_audit","domain":domain,"category":category,"methodology":"auto-detect category → auto-propose competitors → auto-generate prompts → run queries"}])
        cur.execute("INSERT INTO audits (brand_id, audit_type, summary, sources, crawl_text) VALUES (%s, 'ai_visibility', %s, %s, %s) RETURNING id", (brand_id, summary, sources, crawl_text))
        audit_id = cur.fetchone()[0]
        conn.commit()
        print(f"  Audit record {audit_id} created.", flush=True)
    finally:
        conn.close()
    return {"audit_id": audit_id, "summary": json.loads(summary), "brand_cited": brand_cited, "total": total, "competitor_citation_counts": dict(comp_cited_counts)}

def main(domain, brand_id=None):
    print(f"\n{'='*60}", flush=True)
    print(f"Self-tuning audit for: {domain}", flush=True)
    print(f"{'='*60}", flush=True)
    
    # 1. Crawl
    print("\n[1/5] Crawling homepage...", flush=True)
    crawl = crawl_homepage(domain)
    if not crawl["ok"]:
        print(f"  Crawl failed: {crawl['error']}", flush=True)
        # Try without https
        return
    print(f"  Got {crawl['html_len']} bytes of HTML", flush=True)
    
    # 2. Classify category
    print("\n[2/5] Classifying category...", flush=True)
    cat = classify_category(domain, crawl["text"])
    if not cat["ok"]:
        print(f"  Classification failed: {cat.get('error','')}", flush=True)
        return
    category = cat.get("category", "unknown")
    positioning = cat.get("positioning", "")
    print(f"  Category: {category} (confidence: {cat.get('confidence','?')})", flush=True)
    print(f"  Positioning: {positioning[:100]}", flush=True)
    
    # 3. Propose competitors (market-tier aware)
    print("\n[3/5] Proposing competitors (market-tier aware)...", flush=True)
    comps = propose_competitors(domain, category, crawl["text"])
    competitors = comps.get("competitors", [])
    print(f"  Pricing model:     {comps.get('pricing_model', '?')}", flush=True)
    print(f"  Target customer:   {comps.get('target_customer', '?')}", flush=True)
    print(f"  Go-to-market:      {comps.get('go_to_market', '?')}", flush=True)
    print(f"  Competitors:", flush=True)
    for c in competitors:
        print(f"    - {c.get('name','?')} ({c.get('domain','?')})", flush=True)
        if c.get('why'):
            print(f"      Why: {c['why']}", flush=True)
    
    # 4. Generate prompts
    print("\n[4/5] Generating brand-neutral prompts...", flush=True)
    prompts_resp = generate_prompts(category, positioning)
    prompts = prompts_resp.get("prompts", [])
    print(f"  Generated {len(prompts)} prompts", flush=True)
    for i, p in enumerate(prompts):
        print(f"    {i+1}. {p[:80]}", flush=True)
    
    # 5. Run audit
    if brand_id and prompts:
        print("\n[5/5] Running visibility queries...", flush=True)
        brand_name = domain.split(".")[0].title()
        if brand_id:
            try:
                conn2 = db()
                c2 = conn2.cursor()
                c2.execute("SELECT name FROM brands WHERE id=%s", (brand_id,))
                r2 = c2.fetchone()
                if r2: brand_name = r2[0]
                conn2.close()
            except: pass
        market_tier = {"pricing_model": comps.get("pricing_model","?"), "target_customer": comps.get("target_customer","?"), "go_to_market": comps.get("go_to_market","?")}
        run_audit(domain, brand_id, category, competitors, prompts, market_tier, brand_name)
    else:
        print("\n[5/5] Skipping audit (no brand_id or no prompts).", flush=True)
    
    print(f"\n{'='*60}", flush=True)
    print(f"Done. Category: {category} | {len(competitors)} competitors | {len(prompts)} prompts", flush=True)
    print(f"{'='*60}", flush=True)

if __name__ == "__main__":
    domain = sys.argv[1] if len(sys.argv) > 1 else "brevo.com"
    brand_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
    main(domain, brand_id)

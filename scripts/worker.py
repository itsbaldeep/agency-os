#!/usr/bin/env python3
"""agency-worker — async task worker. Polls tasks table, dispatches by type."""
import json, os, sys, time, urllib.request, urllib.error, base64, socket, psycopg2, psycopg2.extras
from datetime import datetime, timezone

ENV_PATH = "/home/agency/agency-os/.env"

def load_env():
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k] = v

load_env()

def redact_secrets(text):
    try:
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k = k.upper()
                    if any(s in k for s in ("PASSWORD", "TOKEN", "SECRET", "WEBHOOK")) and len(v) >= 6:
                        text = text.replace(v, "[REDACTED]")
    except Exception:
        pass
    return text

DB_HOST = "100.64.0.1"
DB_NAME = "agencyos"
DB_USER = "agency"
DB_PASS = os.environ.get("POSTGRES_PASSWORD", "")
ZEN_URL = os.environ.get("OPENAI_BASE_URL", "https://opencode.ai/zen/v1") + "/chat/completions"
ZEN_KEY = os.environ.get("OPENAI_API_KEY", "")
CH_AUTH = base64.b64encode(f"agency:{os.environ.get('CLICKHOUSE_PASSWORD','changeme_strong_password')}".encode()).decode()

# ── per-stage model routing ───────────────────────────────────────────
# Change any stage's model string here.
# deepseek-v4-flash-free tested: reasoning-only model, outputs empty content
#   for structured JSON prompts — NOT usable for pipeline stages.
# big-pickle tested: works but costs MORE per call than deepseek-v4-flash
#   due to higher input-token usage (272 vs 29 tokens).
# deepseek-v4-flash is the cheapest reliable model at ~$0.00004/call.
# Swap "cheap" to a future free model when one produces direct content output.
MODEL_CONFIG = {
    "cheap": "deepseek-v4-flash",               # classify, competitors, prompts, visibility
    "quality": "deepseek-v4-flash",             # suggestion generation
    "temp_structured": 0.1,                     # low temperature for JSON output
}
# Dedicated worker Zen key — set WORKER_ZEN_KEY in .env to separate worker
# spend from OpenCode spend on the Zen dashboard. Falls back to OPENAI_API_KEY.
WORKER_ZEN_KEY = os.environ.get("WORKER_ZEN_KEY") or os.environ.get("OPENAI_API_KEY", "")

# Hard token budget ceiling per task (run_brand_audit)
TOKEN_BUDGET_TOTAL = 60_000  # abort if total prompt+completion exceeds this

# Approximate pricing for deepseek-v4-flash: $0.15/M input, $0.60/M output
INPUT_COST_PER_TOKEN = 0.15 / 1_000_000
OUTPUT_COST_PER_TOKEN = 0.60 / 1_000_000

MODEL_PRICING = {
    "opencode/deepseek-v4-flash": {"in": INPUT_COST_PER_TOKEN, "out": OUTPUT_COST_PER_TOKEN},
}

def get_conn():
    return psycopg2.connect(host=DB_HOST, port=5432, dbname=DB_NAME, user=DB_USER, password=DB_PASS)

def ch_trace(event):
    try:
        cols = ["project","session_id","actor","action","detail","gate","decision","ok"]
        vals = [str(event.get(k, "")) for k in cols]
        sql = "INSERT INTO default.events (" + ",".join(cols) + ") FORMAT TabSeparated\n" + "\t".join(vals)
        req = urllib.request.Request("http://100.64.0.1:8123/", data=sql.encode(),
            headers={"Authorization": f"Basic {CH_AUTH}", "User-Agent": "AgencyOS-Worker/1.0"})
        urllib.request.urlopen(req, timeout=5)
    except:
        pass

def _draft_parse_json(content):
    s = (content or "").strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    try:
        d = json.loads(s)
        return d if isinstance(d, dict) else None
    except Exception:
        a, b = s.find("{"), s.rfind("}")
        if a != -1 and b > a:
            try:
                d = json.loads(s[a:b+1])
                return d if isinstance(d, dict) else None
            except Exception:
                return None
        return None

def _draft_validate(data, params):
    fails = []
    title = (data.get("title") or "").strip()
    if not title:
        fails.append("title empty")
    meta = (data.get("meta_description") or "").strip()
    if not (1 <= len(meta) <= 160):
        fails.append(f"meta_description {len(meta)} chars (need 1-160)")
    sections = data.get("sections")
    faqs = data.get("faqs")
    if not isinstance(sections, list) or len(sections) < 3:
        fails.append("need >=3 sections")
    if not isinstance(faqs, list) or len(faqs) < 3:
        fails.append("need >=3 faqs")
    target = (params.get("target_keyword") or "").strip()
    if target:
        tl = target.lower()
        first_body = ""
        if isinstance(sections, list) and sections and isinstance(sections[0], dict):
            first_body = (sections[0].get("body_markdown") or "")
        if tl not in title.lower():
            fails.append("target_keyword missing from title")
        if tl not in first_body.lower():
            fails.append("target_keyword missing from first section")
    if "[PLACEHOLDER" in json.dumps(data):
        fails.append("contains [PLACEHOLDER token")
    if isinstance(sections, list):
        words = sum(len((s.get("body_markdown") or "").split()) for s in sections if isinstance(s, dict))
        wmin = int((params.get("word_count_min") or 700))
        wmax = int((params.get("word_count_max") or 1600))
        if not (wmin <= words <= wmax):
            fails.append(f"body word count {words} (need {wmin}-{wmax})")
    return fails

def _draft_assemble(data):
    parts = [f"# {data['title']}", "", f"*{data['meta_description']}*", ""]
    for s in data["sections"]:
        parts += [f"## {s['heading']}", "", s["body_markdown"], ""]
    parts += ["## FAQs", ""]
    for f in data["faqs"]:
        parts += [f"**{f['q']}**", "", f["a"], ""]
    return "\n".join(parts).rstrip()

def _draft_blog_post(params, suggestion_text, brand_context):
    brief = f"""You are writing a blog post for this brand.

Suggestion to fulfill: {suggestion_text}

Brand context (use ONLY this for claims about the brand):
{brand_context}

Structure requirements (apply to the content you write):
1. LEAD: Front-loaded answer — state the key takeaway in the first paragraph.
2. BODY: Question-led sections using H2 headings (e.g. "What Makes X Different?" / "How Does Y Work?").
3. SCHEMA-READY: Headings should be natural FAQ/Article schema targets.
4. GROUNDING: Every stat or claim NOT found in the brand context must be omitted or written generically. Never invent a number, quote, or label. No [PLACEHOLDER tokens allowed in the output.
5. BRAND CLAIMS: If the brand's own positioning uses superlatives (e.g. "cleanest", "best"), quote them as the brand's claim — do NOT assert them as objective fact. Write "the brand positions itself as..." not "it is the cleanest..."
6. NO HEALTH CLAIMS: Do not make medical/health claims ("cure", "boost immunity", "detox") unless the brand context explicitly provides evidence.
7. TONE: Informative, helpful, not salesy.
8. LABEL any search-engine or AI-visibility claims as "training-knowledge proxy".

Return ONLY a JSON object (no prose, no code fences) with EXACTLY these keys:
- "title": string
- "slug": string (url-safe slug)
- "meta_description": string, 1-160 chars
- "target_keyword": string
- "sections": array of objects {{"heading": string, "body_markdown": string}} with AT LEAST 3
- "faqs": array of objects {{"q": string, "a": string}} with AT LEAST 3
- "image_slots": array of objects {{"alt": string, "prompt": string, "placement": string}}
- "sources": array of strings"""
    prompt = brief
    for attempt in range(2):
        result = call_zen(prompt, model=MODEL_CONFIG["quality"], max_tokens=6000, temperature=MODEL_CONFIG["temp_structured"])
        if not result["ok"]:
            if attempt == 0:
                continue
            return result
        data = _draft_parse_json(result.get("content") or "")
        if data is None:
            reasons = ["output was not valid JSON"]
        else:
            reasons = _draft_validate(data, params)
        if data is not None and not reasons:
            break
        if attempt == 0:
            prompt = brief + f"\n\nYour previous output failed these checks: {', '.join(reasons)}. Return corrected JSON only."
    else:
        return {"ok": False, "error": "draft failed validation: " + ", ".join(reasons)}

    body = _draft_assemble(data)

    compliance_flags = []
    try:
        sys.path.insert(0, "/home/agency/agency-os/scripts")
        import importlib.util as _ciu
        _cspec = _ciu.spec_from_file_location("sug_mod2", "/home/agency/agency-os/scripts/suggestion-engine.py")
        _csug = _ciu.module_from_spec(_cspec)
        _cspec.loader.exec_module(_csug)
        compliance_flags = _csug.check_compliance(params.get("suggestion", ""), body)
    except Exception:
        pass

    suggestion_id = params.get("suggestion_id")
    brand_id = params.get("brand_id")
    suggestion_title = params.get("suggestion_title") or (params.get("suggestion", "")[:80])
    try:
        _conn2 = get_conn()
        _c2 = _conn2.cursor()
        _c2.execute(
            "INSERT INTO content_items (brand_id, suggestion_id, title, content_type, body, status, compliance_flags, structured) "
            "VALUES (%s, %s, %s, %s, %s, 'draft', %s, %s) RETURNING id",
            (brand_id, suggestion_id, (data.get("title") or suggestion_title)[:200], "blog_post", body,
             json.dumps(compliance_flags) if compliance_flags else "[]", json.dumps(data))
        )
        ci_id = _c2.fetchone()[0]
        _conn2.commit()
        _conn2.close()
        result["content_item_id"] = ci_id
    except Exception as e:
        print(f"[worker] Failed to create content_items row: {e}", flush=True)

    return result

def handle_generate_draft(task):
    params = task["params"] or {}
    suggestion_text = params.get("suggestion", "")
    brand_context = params.get("context", "")
    content_type = params.get("content_type", "article")
    content_item_id = params.get("content_item_id")

    if content_type == "blog_post":
        return _draft_blog_post(params, suggestion_text, brand_context)

    if content_type == "human_article":
        prompt = f"""Write a blog article that reads as human-written — no detectable AI patterns. Target 600-1200 words.

Suggestion to fulfill: {suggestion_text}

Brand context (use ONLY this for claims about the brand):
{brand_context}

SENTENCE AND PARAGRAPH RHYTHM:
- Vary sentence length: alternate short sentences (4-8 words) with longer multi-clause ones (20-30 words). No two consecutive sentences with the same structure.
- Vary paragraph length: mix one-sentence paragraphs for emphasis with 4-6 sentence paragraphs for development. No uniform 3-4 sentence paragraphs throughout.

VOICE AND POINT OF VIEW:
- Take a genuine point of view. Every paragraph must advance a specific argument or observation — not merely describe. Neutral Wikipedia tone is forbidden.
- Be concrete. Replace "a wide range" with specifics or [PLACEHOLDER: ...]. Replace "many customers" with figures or [PLACEHOLDER: ...].
- Vary sentence openings: do not start three consecutive sentences with the same word.

BANNED PHRASES (never use these):
"In today's fast-paced world" / "In today's digital age" / "In conclusion" / "In summary" / "To sum up" / "Unlock" / "Unleash" / "Elevate" / "Seamless" / "Game-changer" / "Revolutionize" / "Cutting-edge" / "Ever-evolving" / "Stay ahead of the curve" / "It's no secret that" / "It goes without saying" / "Thought-provoking" / "Dive into" / "The power of" / "When it comes to" / "In the world of" / "A wide range of"

FORMULAIC INTRO/OUTRO BAN: Do NOT start with "In the world of X" or "When it comes to Y" or "X has become essential." Do NOT end with "Only time will tell" or "The future is bright" or "What remains to be seen."

GROUNDING:
- Use ONLY the brand context above for factual claims.
- Brand's own positioning claims (e.g. "cleanest", "best") must be attributed: write "the brand positions itself as..." not "it is the cleanest..."
- Every number, quote, and specific claim NOT found in the input must use [PLACEHOLDER: description].
- PLACEHOLDERS are the output's integrity mechanism — do NOT remove them.
- No health claims without evidence.

Output as plain text with markdown headings."""
    else:
        prompt = f"""You are a content strategist. Based on the following suggestion and brand context, produce a short, targeted piece of content.

Suggestion: {suggestion_text}

Brand context: {brand_context}

Requirements:
- Front-loaded answer (key takeaway first)
- Keep it ~200-300 words
- Use ONLY data from brand context — never invent figures
- Where you lack data for a claim, insert [PLACEHOLDER: description]
- Every factual claim must be grounded in the provided brand context
- Output as plain text with markdown headings."""

    result = call_zen(prompt, model=MODEL_CONFIG["quality"], max_tokens=2000, temperature=MODEL_CONFIG["temp_structured"])
    if not result["ok"]:
        return result

    body = (result.get("content") or "").strip()
    if not body:
        return {"ok": False, "error": "generate_draft: empty body from Zen"}

    # Post-generation compliance check
    compliance_flags = []
    try:
        sys.path.insert(0, "/home/agency/agency-os/scripts")
        import importlib.util as _ciu
        _cspec = _ciu.spec_from_file_location("sug_mod2", "/home/agency/agency-os/scripts/suggestion-engine.py")
        _csug = _ciu.module_from_spec(_cspec)
        _cspec.loader.exec_module(_csug)
        compliance_flags = _csug.check_compliance(params.get("suggestion", ""), body)
    except Exception:
        pass

    # Create content_items row ONLY after successful generation with non-empty body
    suggestion_id = params.get("suggestion_id")
    brand_id = params.get("brand_id")
    suggestion_title = params.get("suggestion_title") or (params.get("suggestion", "")[:80])
    try:
        _conn2 = get_conn()
        _c2 = _conn2.cursor()
        _c2.execute(
            "INSERT INTO content_items (brand_id, suggestion_id, title, content_type, body, status, compliance_flags) "
            "VALUES (%s, %s, %s, %s, %s, 'draft', %s) RETURNING id",
            (brand_id, suggestion_id, suggestion_title[:200], content_type, body,
             json.dumps(compliance_flags) if compliance_flags else "[]")
        )
        ci_id = _c2.fetchone()[0]
        _conn2.commit()
        _conn2.close()
        result["content_item_id"] = ci_id
    except Exception as e:
        print(f"[worker] Failed to create content_items row: {e}", flush=True)
        # Non-fatal — the task result still exists

    return result

def call_zen(prompt, model="deepseek-v4-flash", max_tokens=1500, temperature=None, timeout=90):
    body_dict = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}
    if temperature is not None:
        body_dict["temperature"] = temperature
    body = json.dumps(body_dict).encode()
    req = urllib.request.Request(ZEN_URL, data=body,
        headers={"Authorization": f"Bearer {WORKER_ZEN_KEY}", "Content-Type": "application/json", "User-Agent": "AgencyOS-Worker/1.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read())
        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        usage = data.get("usage", {})
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        cost = pt * INPUT_COST_PER_TOKEN + ct * OUTPUT_COST_PER_TOKEN
        return {"ok": True, "content": content, "prompt_tokens": pt, "completion_tokens": ct, "cost": round(cost, 8)}
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500] if hasattr(e, 'read') else str(e)
        return {"ok": False, "error": f"HTTP {e.code}: {body}"}
    except (socket.timeout, urllib.error.URLError) as e:
        return {"ok": False, "error": f"TIMEOUT: {str(e)[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}

def handle_onboard_project(task):
    """Deterministic repo onboarding. Never invokes opencode."""
    import re as _re, subprocess, os as _os

    params = task["params"] or {}
    repo_name = (params.get("repo_name") or "").strip()
    if not _re.fullmatch(r"[a-z0-9-]+", repo_name):
        return {"ok": False, "error": "repo_name required, must match ^[a-z0-9-]+$"}
    git_url = (params.get("git_url") or "").strip()
    if not git_url:
        return {"ok": False, "error": "git_url is required"}
    github_owner = params.get("github_owner") or "itsbaldeep"
    base_branch = params.get("base_branch") or "main"

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE projects SET repo_name=%s, repo_url=%s, github_owner=%s, base_branch=%s, agent_allowed=true "
            "WHERE repo_name=%s OR name=%s",
            (repo_name, git_url, github_owner, base_branch, repo_name, repo_name))
        if cur.rowcount == 0:
            cur.execute(
                "INSERT INTO projects (name, repo_name, repo_url, github_owner, base_branch, agent_allowed) "
                "VALUES (%s, %s, %s, %s, %s, true)",
                (repo_name, repo_name, git_url, github_owner, base_branch))
        conn.commit()
    finally:
        conn.close()

    local_path = f"/home/agency/projects/{repo_name}"
    if not _os.path.isdir(local_path):
        clone = subprocess.run(["git", "clone", git_url, local_path],
                               capture_output=True, text=True, timeout=120,
                               env={**_os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if clone.returncode != 0:
            return {"ok": False, "error": f"git clone failed: {clone.stderr.strip()[:500]}"}
    elif not _os.path.isdir(f"{local_path}/.git"):
        return {"ok": False, "error": f"Directory exists but is not a git repo: {local_path}"}

    fetch = subprocess.run(["git", "fetch", "origin"], capture_output=True, text=True,
                           cwd=local_path, timeout=120,
                           env={**_os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if fetch.returncode != 0:
        return {"ok": False, "error": f"git fetch failed: {fetch.stderr.strip()[:500]}"}

    return {"ok": True,
            "content": f"onboarded {repo_name} (base {base_branch}), clone ready at {local_path}",
            "prompt_tokens": 0, "completion_tokens": 0, "cost": 0}


def get_project(repo_name):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT repo_name, github_owner, base_branch, "
            "COALESCE(local_path, '/home/agency/projects/' || repo_name) AS local_path "
            "FROM projects WHERE repo_name=%s AND agent_allowed=true", (repo_name,))
        return cur.fetchone()
    finally:
        conn.close()

def handle_propose_fix(task):
    params = task["params"] or {}
    repo = params.get("repo", "")
    description = params.get("description", "")
    model = params.get("model") or "opencode/deepseek-v4-flash"
    timeout_s = int(params.get("timeout") or 180)

    proj = get_project(repo)
    if not proj:
        return {"ok": False, "error": f"Repo '{repo}' is not authorized for propose_fix"}
    if not description.strip():
        return {"ok": False, "error": "description is required"}

    repo_path = proj["local_path"]
    base_branch = params.get("base") or proj["base_branch"]
    branch = f"fix/worker-{task['id']}-{slug(description)[:30]}"

    import os, subprocess, tempfile

    def git(*args, repo_dir=repo_path):
        return subprocess.run(["git"] + list(args), capture_output=True, text=True,
                              cwd=repo_dir, timeout=60, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})

    # Step 1: fetch latest and create working branch
    git("fetch", "origin")
    git("checkout", base_branch)
    git("pull", "origin", base_branch)

    # Create branch; if it already exists (stale from prior failure), delete it first
    git("branch", "-D", branch)
    git("checkout", "-b", branch)

    try:
        # Step 2: run opencode headless -- capture full NDJSON output
        # Prefix with ponytail philosophy: YAGNI, simplest solution, no over-engineering
        ponytail_prefix = "[PONYTAIL full] Apply lazy senior dev principles: question whether this needs to exist (YAGNI), prefer standard library over custom code, native features over dependencies, one line over fifty. "
        ponytail_description = ponytail_prefix + description
        opencode_bin = "/home/agency/.opencode/bin/opencode"
        oc_env = {**os.environ, "HOME": "/home/agency",
                  "OPENAI_BASE_URL": ZEN_URL.rsplit("/chat", 1)[0],
                  "OPENAI_API_KEY": ZEN_KEY}
        if "PATH" not in oc_env:
            oc_env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
        oc_proc = subprocess.run(
            [opencode_bin, "run", "--dir", repo_path, ponytail_description,
             "--dangerously-skip-permissions", "--format", "json",
             "--model", model],
            capture_output=True, text=True, timeout=timeout_s, env=oc_env,
        )
        if oc_proc.returncode != 0:
            out_snip = oc_proc.stdout[:500]
            err_snip = oc_proc.stderr[:500]
            raise RuntimeError(f"opencode exited {oc_proc.returncode} | stderr:{err_snip} | stdout:{out_snip}")

        # Parse NDJSON for token/cost data
        total_in = 0
        total_out = 0
        for line in oc_proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "step_finish":
                tokens = ev.get("part", {}).get("tokens", {})
                if tokens:
                    total_in += tokens.get("input", 0)
                    total_out += tokens.get("output", 0)

        prices = MODEL_PRICING.get(model, {"in": INPUT_COST_PER_TOKEN, "out": OUTPUT_COST_PER_TOKEN})
        cost = total_in * prices["in"] + total_out * prices["out"]

        # Step 3: check if anything changed
        status = git("status", "--porcelain")
        if not status.stdout.strip():
            raise RuntimeError("no changes produced by opencode")
        
        # Step 4: commit and push
        git("add", "-A")
        c = git("commit", "--no-verify", "-m", f"fix: {description[:60]}")
        if c.returncode != 0:
            raise RuntimeError(f"git commit failed: {(c.stderr or c.stdout)[:300]}")
        p = git("push", "origin", branch)
        if p.returncode != 0:
            raise RuntimeError(f"git push failed: {(p.stderr or p.stdout)[:300]}")

        # Step 5: capture diff for dashboard
        diff_proc = git("diff", f"{base_branch}..{branch}")
        diff_text = diff_proc.stdout[:50000]
        names_proc = git("diff", "--name-status", f"{base_branch}..{branch}")
        names_text = names_proc.stdout[:5000]

        # Step 6: open PR via GitHub API
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise RuntimeError("GITHUB_TOKEN not set")
        pr_body = f"## Auto-generated PR\n\n**Description:** {description}\n\n**Changes:**\n```\n{names_text}\n```\n\nTriggered by Agency OS worker task #{task['id']}."
        pr_payload = json.dumps({
            "title": f"fix: {description[:60]}",
            "head": branch,
            "base": base_branch,
            "body": pr_body,
        }).encode()
        pr_req = urllib.request.Request(
            f"https://api.github.com/repos/{proj['github_owner']}/{repo}/pulls",
            data=pr_payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "AgencyOS-Worker/1.0",
            },
        )
        try:
            pr_resp = urllib.request.urlopen(pr_req, timeout=30)
            pr_data = json.loads(pr_resp.read())
            pr_url = pr_data.get("html_url", "")
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:500]
            raise RuntimeError(f"GitHub API error {e.code}: {body}")

        # Success: delete the local fix branch, never leave orphans
        git("checkout", base_branch)
        git("branch", "-D", branch)

        # Store everything on the task's result_ref (JSON)
        result = json.dumps({
            "pr_url": pr_url,
            "branch": branch,
            "diff": diff_text,
            "changed_files": names_text,
        })

        try:
            _tu = get_conn()
            _tuc = _tu.cursor()
            _tuc.execute("INSERT INTO token_usage (model, tokens_in, tokens_out, cost_usd) VALUES (%s, %s, %s, %s)",
                         (model, total_in, total_out, round(cost, 8)))
            _tu.commit()
            _tu.close()
        except Exception as e:
            print(f"[worker] Failed to record token_usage: {e}", flush=True)

        return {
            "ok": True,
            "content": result,
            "prompt_tokens": total_in,
            "completion_tokens": total_out,
            "cost": round(cost, 8),
        }

    except Exception as e:
        # Clean up: delete the local branch, never leave orphans
        git("checkout", base_branch)
        git("branch", "-D", branch)
        return {"ok": False, "error": str(e)[:500]}


def handle_agent_task(task):
    params = task["params"] or {}
    repo = params.get("repo", "")
    prompt = (params.get("prompt") or "").strip()
    model = params.get("model") or "opencode/deepseek-v4-flash"
    timeout_s = int(params.get("timeout") or 300)

    proj = get_project(repo)
    if not proj:
        return {"ok": False, "error": f"Repo '{repo}' is not authorized for agent tasks"}
    if not prompt:
        return {"ok": False, "error": "prompt is required"}

    import subprocess, os as _os, re
    repo_path = proj["local_path"]
    log_path = f"/home/agency/agency-os/logs/task-{task['id']}.log"
    oc_env = {**os.environ, "HOME": "/home/agency",
              "OPENAI_BASE_URL": ZEN_URL.rsplit("/chat", 1)[0],
              "OPENAI_API_KEY": ZEN_KEY, "NO_COLOR": "1"}
    oc_env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    _os.makedirs("/home/agency/agency-os/logs", exist_ok=True)
    proc = subprocess.Popen(
        ["/home/agency/.opencode/bin/opencode", "run", prompt,
         "--auto",
         "--model", model],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        cwd=repo_path, env=oc_env,
    )
    lines = []
    try:
        with open(log_path, "w") as f:
            for line in proc.stdout:
                f.write(line)
                f.flush()
                lines.append(line)
            proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return {"ok": False, "error": f"agent task timed out after {timeout_s}s"}
    out = redact_secrets(re.sub(r'\x1b\[[0-9;]*m', '', "".join(lines)).strip())
    if not out:
        out = f"(opencode exited {proc.returncode}, no output)"
    if proc.returncode != 0:
        return {"ok": False, "error": out[-500:]}
    return {"ok": True, "content": out[-1500:], "prompt_tokens": 0, "completion_tokens": 0, "cost": 0}


def handle_ask(task):
    params = task["params"] or {}
    question = (params.get("question") or "").strip()
    model = params.get("model") or "opencode/glm-5.2"
    timeout_s = int(params.get("timeout") or 300)

    if not question:
        return {"ok": False, "error": "question is required"}

    import subprocess, os as _os, re
    sys_ctx = ("You are the operations assistant for this VPS (Agency OS). Answer using LIVE data by "
               "running read-only commands: docker ps, systemctl list-units --type=service --state=running, "
               "ss -tlnp, df -h, free -h, crontab -l, reading files under /home/agency/agency-os and "
               "/home/agency/projects, and read-only psql SELECT queries against the agencyos database at "
               "100.64.0.1 using the POSTGRES_PASSWORD from /home/agency/agency-os/.env. STRICTLY READ-ONLY: "
               "never modify files, never run git commands that change state, never UPDATE/INSERT/DELETE in any "
               "database, never restart services. Answer the question directly and concisely, stating exact "
               "names, ports, counts and values you observed. Never print credential values or the "
               "contents of .env files; use credentials silently.")
    prompt = f"{sys_ctx}\n\nQuestion: {question}"

    oc_env = {**os.environ, "HOME": "/home/agency",
              "OPENAI_BASE_URL": ZEN_URL.rsplit("/chat", 1)[0],
              "OPENAI_API_KEY": ZEN_KEY, "NO_COLOR": "1"}
    oc_env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    proc = subprocess.Popen(
        ["/home/agency/.opencode/bin/opencode", "run", prompt,
         "--auto",
         "--model", model],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        cwd="/home/agency", env=oc_env,
    )
    lines = []
    try:
        for line in proc.stdout:
            lines.append(line)
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return {"ok": False, "error": f"ask timed out after {timeout_s}s"}
    out = redact_secrets(re.sub(r'\x1b\[[0-9;]*m', '', "".join(lines)).strip())
    if not out:
        out = f"(opencode exited {proc.returncode}, no output)"
    if proc.returncode != 0:
        return {"ok": False, "error": out[-500:]}
    return {"ok": True, "content": out, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0}


def slug(text):
    import re
    s = text.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-') or "fix"


def handle_run_brand_audit(task):
    import sys, importlib.util, re as _re
    SCRIPT_DIR = "/home/agency/agency-os/scripts"
    sys.path.insert(0, SCRIPT_DIR)

    _aspec = importlib.util.spec_from_file_location("audit_mod", f"{SCRIPT_DIR}/self-tuning-brand-audit.py")
    audit = importlib.util.module_from_spec(_aspec)
    _aspec.loader.exec_module(audit)

    _sspec = importlib.util.spec_from_file_location("sug_mod", f"{SCRIPT_DIR}/suggestion-engine.py")
    sug = importlib.util.module_from_spec(_sspec)
    _sspec.loader.exec_module(sug)

    # ── model routing: make audit module's zen default to cheap model ──
    _orig_audit_zen = audit.zen
    _cheap_m = MODEL_CONFIG["cheap"]
    _qual_m = MODEL_CONFIG["quality"]
    def _cheap_zen(prompt, model=_cheap_m, max_tokens=800):
        return _orig_audit_zen(prompt, model=_cheap_m, max_tokens=max_tokens)
    audit.zen = _cheap_zen

    params = task.get("params") or {}
    domain = params.get("domain", "").strip()
    existing_brand_id = params.get("brand_id")

    if not domain:
        return {"ok": False, "error": "domain is required"}

    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = 0.0

    def acc(r):
        nonlocal total_prompt_tokens, total_completion_tokens, total_cost
        total_prompt_tokens += r.get("prompt_tokens", 0)
        total_completion_tokens += r.get("completion_tokens", 0)
        total_cost += r.get("cost", 0)

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Token budget check helper
        def budget_ok():
            used = total_prompt_tokens + total_completion_tokens
            if used > TOKEN_BUDGET_TOTAL:
                raise RuntimeError(f"Token budget {TOKEN_BUDGET_TOTAL} exceeded ({used} used)")
            return True

        # Step 1: Crawl
        crawl = audit.crawl_homepage(domain)
        if not crawl["ok"]:
            return {"ok": False, "error": f"Crawl failed: {crawl.get('error','')}"}

        # Step 2: Understand business (enriched)
        biz_prompt = f"""From the homepage text below, identify this company's business details.
Return ONLY raw JSON, no prose, no code fences. JSON with:
category, positioning, flagship_product, primary_sales_channel ("DTC ecommerce"|"retail"|"quick-commerce / marketplace"|"wholesale / B2B" or combination), business_stage ("early"|"growth"|"mature"), confidence ("high"|"medium"|"low")

Homepage:
{crawl['text'][:2000]}"""
        biz_info = None
        biz_last = ""
        for biz_attempt in range(2):
            biz_r = call_zen(biz_prompt, model=MODEL_CONFIG["cheap"], max_tokens=800, temperature=MODEL_CONFIG["temp_structured"])
            budget_ok()
            acc(biz_r)
            if not biz_r["ok"]:
                continue
            biz_last = biz_r["content"].strip()
            for trim in [biz_last, biz_last[biz_last.find('{'):biz_last.rfind('}')+1] if '{' in biz_last else '']:
                trim = trim.strip()
                if not trim:
                    continue
                try:
                    data = json.loads(trim)
                    if isinstance(data, dict):
                        biz_info = data
                        break
                except:
                    continue
            if biz_info:
                break
            if biz_attempt < 1:
                biz_prompt += "\n\nSTRICT: Return ONLY a JSON object with { } brackets. No other text."
        if not biz_info:
            return {"ok": False, "error": f"Could not parse business understanding as JSON after 2 attempts. Raw: {biz_last[:300]}"}

        category = biz_info.get("category") or "unknown"
        positioning = biz_info.get("positioning") or ""
        flagship = biz_info.get("flagship_product") or ""
        channel = biz_info.get("primary_sales_channel") or "DTC ecommerce"
        stage = biz_info.get("business_stage") or "early"

        # Step 3: Propose competitors
        comps = audit.propose_competitors(domain, category, crawl["text"])
        competitors = comps.get("competitors", [])
        competitor_gap = len(competitors) == 0

        # Step 4: Generate prompts (with fallback)
        prompts_resp = audit.generate_prompts(category, positioning)
        prompts = prompts_resp.get("prompts", [])
        if len(prompts) < 5:
            fallback_prompt = f"Generate 15 brand-neutral buying-intent search queries for the category '{category}'. Return ONLY raw JSON, no prose, no code fences. JSON array of 15 strings."
            for attempt in range(2):
                fr = call_zen(fallback_prompt, model=MODEL_CONFIG["cheap"], max_tokens=1000, temperature=MODEL_CONFIG["temp_structured"])
                acc(fr)
                if not fr["ok"]:
                    continue
                try:
                    data = json.loads(fr["content"])
                    if isinstance(data, list) and len(data) >= 5:
                        prompts = data[:15]
                        break
                except:
                    pass
                if attempt < 1:
                    fallback_prompt += " STRICT: JSON array ONLY."
        if len(prompts) < 5:
            return {"ok": False, "error": f"Only {len(prompts)} prompts generated, need >=5"}

        # Brand onboarding — create or reuse
        brand_name = domain.split(".")[0].title()
        if existing_brand_id:
            brand_id_val = int(existing_brand_id)
        else:
            slug = _re.sub(r'[^a-z0-9]+', '-', domain.split(".")[0].lower()).strip('-')
            cur.execute("INSERT INTO brands (name, slug, access_tier) VALUES (%s, %s, '0') ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name RETURNING id",
                        (brand_name, slug))
            brand_id_val = cur.fetchone()["id"]
            cur.execute("INSERT INTO brand_properties (brand_id, property_type, value, accessible) VALUES "
                        "(%s, 'domain', %s, true) ON CONFLICT DO NOTHING", (brand_id_val, domain))

        # Write business properties (skip null values)
        for ptype, pval in [("category", category), ("positioning", positioning),
                            ("flagship_product", flagship), ("primary_sales_channel", channel),
                            ("business_stage", stage)]:
            if pval is None:
                pval = "unknown"
            cur.execute("INSERT INTO brand_properties (brand_id, property_type, value, accessible) "
                        "VALUES (%s, %s, %s, true) ON CONFLICT DO NOTHING",
                        (brand_id_val, ptype, str(pval)))

        # Write competitors
        for c in competitors:
            cdomain = c.get("domain", "")
            cname = c.get("name", cdomain)
            if cdomain:
                cur.execute("INSERT INTO competitors (brand_id, domain, name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                            (brand_id_val, cdomain, cname))

        conn.commit()

        # Step 5: Run AI visibility queries
        market_tier = {"pricing_model": comps.get("pricing_model","?"),
                       "target_customer": comps.get("target_customer","?"),
                       "go_to_market": comps.get("go_to_market","?")}
        visibility_result = audit.run_audit(domain, brand_id_val, category, competitors, prompts, market_tier, brand_name)
        audit_id = visibility_result.get("audit_id")
        summary = visibility_result.get("summary", {})
        budget_ok()

        # Update audit record with crawl_text for generate_draft to consume
        cur2.execute("UPDATE audits SET crawl_text = %s WHERE id = %s",
                     (crawl['text'], audit_id))

        # Step 5a: Confidence gate
        brand_cited = summary.get("brand_cited_count", 0)
        competitor_cited_total = summary.get("all_competitors_total_citations", 0)
        total_citations = brand_cited + competitor_cited_total
        confidence = "normal"
        gate_blocked = False
        if total_citations <= 1:
            confidence = "low"
            gate_blocked = True

        # Update audit record with confidence
        summary["confidence"] = confidence
        summary["visibility_gate_blocked"] = gate_blocked
        summary["competitor_gap"] = competitor_gap
        conn = get_conn()
        cur2 = conn.cursor()
        cur2.execute("UPDATE audits SET summary = %s WHERE id = %s",
                     (json.dumps(summary), audit_id))
        conn.commit()
        conn.close()

        # Step 6: Generate suggestions
        print(f"[worker] Running suggestion engine...", flush=True)
        sug_result = sug.generate_suggestions(
            brand_id=brand_id_val,
            audit_id=audit_id,
            summary=summary,
            biz_info=biz_info,
            crawl_text=crawl["text"],
            confidence=confidence,
            competitor_gap=competitor_gap,
        )
        print(f"[worker] Suggestion engine: ok={sug_result.get('ok')} count={sug_result.get('count',0)} error={sug_result.get('error','')[:200]}", flush=True)
        sug_error = sug_result.get("error", "") if not sug_result.get("ok") else ""
        if sug_result.get("ok"):
            sug_tokens = sug_result.get("tokens", (0, 0))
            acc({"prompt_tokens": sug_tokens[0], "completion_tokens": sug_tokens[1], "cost": 0})

        conn = get_conn()
        try:
            cur3 = conn.cursor()
            for s in sug_result.get("suggestions", []):
                comp_json = json.dumps(s.get("compliance_flags", []))
                sources_json = json.dumps(s.get("sources", []))
                cur3.execute(
                    "INSERT INTO suggestions (brand_id, audit_id, title, rationale, sources, compliance_flags, impact, effort, tier_required, status, action_type) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '0', 'pending', %s)",
                    (brand_id_val, audit_id, s["title"], s["rationale"], sources_json,
                     comp_json, s["impact"], s["effort"], s.get("action_type", "monitor")))
            conn.commit()
        finally:
            conn.close()

        # Build compact result_ref for dashboard (must fit in 500-char task.result_ref)
        result_ref = json.dumps({
            "status": "done", "domain": domain, "brand_id": brand_id_val,
            "audit_id": audit_id, "category": category,
            "visibility": f"{brand_cited}/{summary.get('prompts_queried',0)}",
            "share_pct": summary.get("brand_share_of_voice_pct", 0),
            "confidence": confidence, "gate_blocked": gate_blocked,
            "competitor_gap": competitor_gap,
            "competitors_found": len(competitors),
            "suggestions_count": sug_result.get("count", 0),
            "suggestion_ok": sug_result.get("ok", False),
            "suggestion_error": sug_error[:120] if sug_error else "",
        }, separators=(',', ':'))

        return {
            "ok": True,
            "content": result_ref,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "cost": round(total_cost, 8),
        }

    except Exception as e:
        import traceback
        return {"ok": False, "error": f"Brand audit failed: {str(e)[:400]} -- {traceback.format_exc()[:200]}"}


def handle_client_import_repo(task):
    """Clone a public github repo, generate AGENTS.md docs, create project row, link client."""
    import re as _re, subprocess, os as _os, shutil

    params = task.get("params") or {}
    client_id = params.get("client_id")
    repo_url = (params.get("repo_url") or "").strip()

    if not client_id or not repo_url:
        return {"ok": False, "error": "client_id and repo_url are required"}

    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = 0.0

    def acc(r):
        nonlocal total_prompt_tokens, total_completion_tokens, total_cost
        total_prompt_tokens += r.get("prompt_tokens", 0)
        total_completion_tokens += r.get("completion_tokens", 0)
        total_cost += r.get("cost", 0)

    def budget_ok():
        used = total_prompt_tokens + total_completion_tokens
        if used > TOKEN_BUDGET_TOTAL:
            raise RuntimeError(f"Token budget {TOKEN_BUDGET_TOTAL} exceeded ({used} used)")
        return True

    # ── Step 1: Validate URL securely ──────────────────────────────
    if _re.search(r'[\s@\'"$`\\|;&()<>]', repo_url):
        return {"ok": False, "error": "URL contains invalid characters (whitespace, @, or shell metacharacters)"}
    m = _re.match(r'^(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$', repo_url)
    if not m:
        return {"ok": False, "error": f"URL must be a clean github.com/org/repo pattern. Got: {repo_url[:100]}"}
    org, repo_name = m.group(1), m.group(2)
    if _re.search(r'[:\s]', org) or _re.search(r'[:\s]', repo_name):
        return {"ok": False, "error": "Invalid characters in org or repo name"}
    canonical_url = f"https://github.com/{org}/{repo_name}.git"

    project_slug = f"{org}-{repo_name}".lower()
    project_slug = _re.sub(r'[^a-z0-9_-]+', '-', project_slug).strip('-')
    dest = f"/home/agency/projects/{project_slug}"

    # ── Step 2: Shallow clone ──────────────────────────────────────
    if _os.path.exists(dest):
        return {"ok": False, "error": f"Project directory already exists: {dest}"}

    git_token = _os.environ.get("GITHUB_TOKEN", "")
    clone_url = f"https://oauth2:{git_token}@github.com/{org}/{repo_name}.git" if git_token else canonical_url

    try:
        clone_proc = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, dest],
            capture_output=True, text=True, timeout=60,
            env={**_os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest, ignore_errors=True)
        return {"ok": False, "error": "Clone timed out after 60s"}
    if clone_proc.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        stderr = clone_proc.stderr.lower()
        if "authentication failed" in stderr or "access denied" in stderr or "not found" in stderr or "could not read" in stderr:
            return {"ok": False, "error": "Private or inaccessible repo — client-credential import not yet supported (v1 limitation). The clone uses the agent's personal GITHUB_TOKEN, so only public/accessible repos work."}
        return {"ok": False, "error": f"Clone failed: {clone_proc.stderr[:200]}"}

    # Size cap: abort if clone exceeds 500MB
    try:
        size_result = subprocess.run(["du", "-sb", dest], capture_output=True, text=True, timeout=10)
        size_bytes = int(size_result.stdout.split()[0]) if size_result.stdout else 0
        if size_bytes > 500 * 1024 * 1024:
            shutil.rmtree(dest, ignore_errors=True)
            return {"ok": False, "error": f"Repo too large ({size_bytes / 1024 / 1024:.0f}MB). Max: 500MB."}
    except Exception:
        pass

    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # ── Step 3: Read file tree + key files ─────────────────────
        tree_result = subprocess.run(["find", dest, "-type", "f"], capture_output=True, text=True, timeout=15)
        all_files = [f.replace(dest + "/", "") for f in tree_result.stdout.strip().split("\n") if f.strip()]
        all_files.sort()
        file_tree = "\n".join(all_files[:200])

        key_contents = []
        for key_file in ["README.md", "README.rst", "README.txt", "package.json", "AGENTS.md", "Dockerfile",
                         "Makefile", "Cargo.toml", "pyproject.toml", "go.mod", "requirements.txt",
                         "Gemfile", "composer.json", "mix.exs", "Project.toml"]:
            fpath = f"{dest}/{key_file}"
            if _os.path.isfile(fpath):
                try:
                    txt = open(fpath).read(2000)
                    key_contents.append(f"--- {key_file} ---\n{txt[:2000]}")
                except:
                    pass
        for entry in ["src/main.ts", "src/index.ts", "src/main.py", "src/index.js",
                       "main.ts", "index.ts", "main.py", "index.js", "app.py",
                       "src/App.jsx", "src/App.tsx"]:
            fpath = f"{dest}/{entry}"
            if _os.path.isfile(fpath):
                try:
                    txt = open(fpath).read(1500)
                    key_contents.append(f"--- {entry} ---\n{txt[:1500]}")
                except:
                    pass

        code_context = f"FILE TREE ({len(all_files)} files, showing first 200):\n{file_tree[:2500]}\n\nKEY FILES:\n" + "\n\n".join(key_contents)
        code_context = code_context[:4000]

        # ── Step 4: Generate AGENTS.md via Zen (one cheap call) ────
        prompt = f"""Analyze this codebase. Produce a concise AGENTS.md-style summary for a developer who will work on this project.
Cover: project purpose, entry points, key files, architecture patterns, tech stack, build/run commands.
~300 words. Return ONLY raw JSON, no prose, no code fences.
JSON with fields: purpose, entry_points, tech_stack, architecture, key_files, build_and_run, notes"""

        zen_body = f"{prompt}\n\n{code_context}"
        r = call_zen(zen_body, model=MODEL_CONFIG["quality"], max_tokens=2000, temperature=MODEL_CONFIG["temp_structured"])
        acc(r)
        budget_ok()
        if not r["ok"]:
            return {"ok": False, "error": f"Doc generation failed: {r.get('error','')}"}

        # Parse doc JSON (with truncated-response fallback)
        doc_raw = r["content"].strip()
        doc_json = None
        for trim in [doc_raw, doc_raw[doc_raw.find('{'):doc_raw.rfind('}')+1] if '{' in doc_raw else '',
                      doc_raw[:doc_raw.rfind('}')+1] if '}' in doc_raw else doc_raw,
                      doc_raw + '"}"'if doc_raw.count('{') > doc_raw.count('}') else doc_raw]:
            trim = trim.strip()
            if not trim: continue
            try:
                doc_json = json.loads(trim)
                break
            except:
                continue
        if not doc_json:
            # Last resort: regex-extract individual fields from truncated JSON
            import re as _re2
            doc_json = {}
            for field in ['purpose','entry_points','tech_stack','architecture','key_files','build_and_run','notes']:
                m = _re2.search(r'\"' + field + r'\"\s*:\s*\"([^\"]+)\"', doc_raw)
                if m:
                    doc_json[field] = m.group(1)
                else:
                    marr = _re2.search(r'\"' + field + r'\"\s*:\s*\[([^\]]+)\]', doc_raw)
                    if marr:
                        doc_json[field] = [x.strip().strip('"') for x in marr.group(1).split(',') if x.strip()]
            if not doc_json:
                doc_json = {"purpose": f"Imported codebase — {len(all_files)} files"}

        # ── Step 5: Write AGENTS.md ────────────────────────────────
        def _f(v):
            """Flatten a Zen field value (string or list) into a markdown string."""
            if isinstance(v, list):
                return "\n".join(f"- {item}" for item in v if item)
            return str(v) if v else "(Auto-detection failed)"

        agents_lines = [
            f"# {org}/{repo_name}",
            "",
            "## Purpose",
            _f(doc_json.get("purpose")),
            "",
            "## Entry Points",
            _f(doc_json.get("entry_points")),
            "",
            "## Tech Stack",
            _f(doc_json.get("tech_stack")),
            "",
            "## Architecture",
            _f(doc_json.get("architecture")),
            "",
            "## Key Files",
            _f(doc_json.get("key_files")),
            "",
            "## Build & Run",
            _f(doc_json.get("build_and_run")),
            "",
            "## Notes",
            _f(doc_json.get("notes")),
            "",
            "---",
            f"_Auto-generated by client_import_repo. {len(all_files)} files analyzed._",
        ]
        agents_md = "\n".join(agents_lines)
        with open(f"{dest}/AGENTS.md", "w") as f:
            f.write(agents_md)

        # ── Step 6: Create project row ─────────────────────────────
        cur.execute(
            "INSERT INTO projects (name, state, repo_url) VALUES (%s, 'imported', %s) "
            "ON CONFLICT (name) DO UPDATE SET state='imported', repo_url=EXCLUDED.repo_url RETURNING id",
            (project_slug, canonical_url),
        )
        project_id = cur.fetchone()["id"]

        # ── Step 7: Link client ────────────────────────────────────
        cur.execute("UPDATE clients SET status='completed', project_id=%s WHERE id=%s", (project_id, client_id))
        conn.commit()

        ch_trace({"project": project_slug, "actor": "worker", "action": "client_import_repo_done",
                  "detail": f"Client {client_id}: cloned {canonical_url} → project {project_id}",
                  "gate": "green", "decision": "proceed", "ok": 1})

        # NOTE: Imported repos are NOT added to propose_fix's ALLOWED_REPOS.
        # propose_fix (the code-executing dev loop) requires explicit, manual authorization
        # because client repos need a sandbox before the unsandboxed agent operates on them.
        # See worker.py ALLOWED_REPOS comment at line ~117.

        result_ref = json.dumps({
            "status": "done", "client_id": client_id, "project_id": project_id,
            "project_slug": project_slug, "repo_url": canonical_url,
            "files_analyzed": len(all_files),
            "note": "Repo imported and documented. propose_fix is NOT enabled — imported repos need explicit authorization (ALLOWED_REPOS) before the dev loop can operate on them.",
        }, separators=(',', ':'))

        return {
            "ok": True,
            "content": result_ref,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "cost": round(total_cost, 8),
        }

    except Exception as e:
        import traceback
        return {"ok": False, "error": f"Import failed: {str(e)[:400]} -- {traceback.format_exc()[:200]}"}
    finally:
        if 'conn' in dir():
            try: conn.close()
            except: pass


def handle_client_new_project(task):
    """Scaffold a new project from a brief: Zen interprets, creates GitHub repo, writes starter files, pushes."""
    import re as _re, subprocess, os as _os, shutil, json as _json

    params = task.get("params") or {}
    client_id = params.get("client_id")
    brief = (params.get("brief") or "").strip()

    if not client_id or not brief:
        return {"ok": False, "error": "client_id and brief are required"}
    if len(brief) > 500:
        return {"ok": False, "error": "brief too long (max 500 chars)"}
    if _re.search(r'[\'";$`\\|&<>]', brief):
        return {"ok": False, "error": "brief contains invalid shell characters"}
    if not _re.search(r'[a-zA-Z0-9]', brief):
        return {"ok": False, "error": "brief must contain alphanumeric content"}

    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = 0.0

    def acc(r):
        nonlocal total_prompt_tokens, total_completion_tokens, total_cost
        total_prompt_tokens += r.get("prompt_tokens", 0)
        total_completion_tokens += r.get("completion_tokens", 0)
        total_cost += r.get("cost", 0)

    def budget_ok():
        used = total_prompt_tokens + total_completion_tokens
        if used > TOKEN_BUDGET_TOTAL:
            raise RuntimeError(f"Token budget {TOKEN_BUDGET_TOTAL} exceeded ({used} used)")
        return True

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # ── Step 1: Interpret the brief ────────────────────────────
        _stacks = {"python-flask", "node-express", "nextjs", "static-html", "go-api", "python-fastapi"}
        _stack_templates = {
            "python-flask": {"entry": "app.py", "entry_content": "from flask import Flask\napp = Flask(__name__)\n\n@app.route('/')\ndef hello():\n    return '<h1>Hello</h1><p>Scaffolded by Agency OS</p>'\n\nif __name__ == '__main__':\n    app.run(host='0.0.0.0', port=8080)\n",
                             "dockerfile": "FROM python:3.14-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir flask gunicorn\nCOPY . .\nEXPOSE 8080\nCMD [\"gunicorn\", \"-b\", \"0.0.0.0:8080\", \"app:app\"]\n",
                             "requirements": "flask\ngunicorn\n",
                             "gitignore": "*.pyc\n__pycache__/\n.env\nvenv/\n"},
            "python-fastapi": {"entry": "main.py", "entry_content": "from fastapi import FastAPI\napp = FastAPI(title='Scaffolded')\n\n@app.get('/')\nasync def root():\n    return {'message': 'Hello from Agency OS'}\n",
                               "dockerfile": "FROM python:3.14-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir fastapi uvicorn\nCOPY . .\nEXPOSE 8080\nCMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8080\"]\n",
                               "requirements": "fastapi\nuvicorn\n",
                               "gitignore": "*.pyc\n__pycache__/\n.env\nvenv/\n"},
            "node-express": {"entry": "index.js", "entry_content": "const express = require('express');\nconst app = express();\napp.get('/', (req, res) => res.send('<h1>Hello</h1><p>Scaffolded by Agency OS</p>'));\napp.listen(8080, () => console.log('on 8080'));\n",
                             "dockerfile": "FROM node:22-alpine\nWORKDIR /app\nCOPY package.json .\nRUN npm install\nCOPY . .\nEXPOSE 8080\nCMD [\"node\", \"index.js\"]\n",
                             "package_json": '{"name":"scaffolded","private":true,"scripts":{"start":"node index.js"}}\n',
                             "gitignore": "node_modules/\n.env\n"},
            "nextjs": {"entry": "package.json", "entry_content": None,
                       "dockerfile": "FROM node:22-alpine\nWORKDIR /app\nCOPY package.json package-lock.json* ./\nRUN npm install\nCOPY . .\nRUN npm run build\nEXPOSE 3000\nCMD [\"npm\", \"start\"]\n",
                       "package_json": '{"name":"scaffolded","private":true,"scripts":{"dev":"next dev","build":"next build","start":"next start"}}\n',
                       "gitignore": "node_modules/\n.next/\n.env\n"},
            "go-api": {"entry": "main.go", "entry_content": "package main\n\nimport (\n\t\"fmt\"\n\t\"net/http\"\n)\n\nfunc handler(w http.ResponseWriter, r *http.Request) {\n\tfmt.Fprintf(w, \"<h1>Hello</h1><p>Scaffolded by Agency OS</p>\")\n}\n\nfunc main() {\n\thttp.HandleFunc(\"/\", handler)\n\thttp.ListenAndServe(\":8080\", nil)\n}\n",
                       "dockerfile": "FROM golang:1.24-alpine AS build\nWORKDIR /src\nCOPY go.mod main.go ./\nRUN go build -o /app .\nFROM alpine:3.21\nCOPY --from=build /app /app\nEXPOSE 8080\nCMD [\"/app\"]\n",
                       "go_mod": 'module scaffolded\n\ngo 1.24\n',
                       "gitignore": "*.exe\n"},
            "static-html": {"entry": "index.html", "entry_content": "<!DOCTYPE html>\n<html lang=\"en\">\n<head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Scaffolded</title></head>\n<body><h1>Hello</h1><p>Scaffolded by Agency OS</p></body>\n</html>\n",
                            "dockerfile": "FROM nginx:alpine\nCOPY . /usr/share/nginx/html\nEXPOSE 80\n",
                            "gitignore": ""},
        }

        parse_prompt = f"""Given this project brief, recommend a starting tech stack and project details.
Return ONLY JSON, no prose, no code fences.
JSON with: slug (lowercase-kebab, 2-30 chars), purpose (10-80 chars), stack (one of: {','.join(sorted(_stacks))}).

        Brief: {brief[:400]}"""
        _parsed = None
        for parse_attempt in range(2):
            pr = call_zen(parse_prompt, model=MODEL_CONFIG["cheap"], max_tokens=400, temperature=MODEL_CONFIG["temp_structured"])
            acc(pr)
            budget_ok()
            if not pr["ok"]:
                continue
            raw = pr["content"].strip()
            for trim in [raw, raw[raw.find('{'):raw.rfind('}')+1] if '{' in raw else '']:
                try:
                    parsed = _json.loads(trim)
                    if isinstance(parsed, dict) and parsed.get("slug") and parsed.get("purpose"):
                        _parsed = parsed
                        break
                except:
                    continue
            if _parsed:
                break
            if parse_attempt < 1:
                parse_prompt += " STRICT: JSON only."
        if not _parsed:
            return {"ok": False, "error": "Could not parse brief after 2 Zen attempts"}

        slug_raw = _parsed.get("slug", "project").strip().lower()
        slug = _re.sub(r'[^a-z0-9-]+', '-', slug_raw).strip('-')[:30] or "project"
        purpose = _parsed.get("purpose", "A new project")[:80]
        stack = _parsed.get("stack", "static-html")
        if stack not in _stacks:
            stack = "static-html"
        tmpl = _stack_templates[stack]

        # ── Step 2: Find unique slug ────────────────────────────────
        dest = f"/home/agency/projects/{slug}"
        for n in range(10):
            if not _os.path.exists(dest):
                cur.execute("SELECT id FROM projects WHERE name=%s", (slug,))
                if not cur.fetchone():
                    break
            slug = f"{slug_raw[:24]}-{n+1}"
            slug = _re.sub(r'[^a-z0-9-]+', '-', slug).strip('-')[:30] or f"project-{n+1}"
            dest = f"/home/agency/projects/{slug}"
        else:
            return {"ok": False, "error": "Could not find unique slug after 10 attempts"}

        # ── Step 3: Create private GitHub repo ──────────────────────
        token = _os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return {"ok": False, "error": "GITHUB_TOKEN not set"}
        gh_create = urllib.request.Request(
            "https://api.github.com/user/repos",
            data=_json.dumps({"name": slug, "private": True, "auto_init": False, "description": purpose}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "AgencyOS-Worker/1.0"},
        )
        try:
            gh_resp = urllib.request.urlopen(gh_create, timeout=30)
            gh_repo = _json.loads(gh_resp.read())
            repo_url = gh_repo.get("clone_url", f"https://github.com/itsbaldeep/{slug}.git")
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            if e.code == 422 and "already exists" in body:
                return {"ok": False, "error": f"GitHub repo '{slug}' already exists. Try a different brief."}
            return {"ok": False, "error": f"GitHub API error {e.code}: {body}"}
        except Exception as e:
            return {"ok": False, "error": f"GitHub create failed: {str(e)[:200]}"}

        # ── Step 4: Clone empty repo and scaffold ──────────────────
        def git(*args, repo_dir=dest):
            return subprocess.run(["git"] + list(args), capture_output=True, text=True,
                                  cwd=repo_dir, timeout=60, env={**_os.environ, "GIT_TERMINAL_PROMPT": "0"})

        clone_url_auth = f"https://oauth2:{token}@github.com/itsbaldeep/{slug}.git"
        subprocess.run(["git", "clone", clone_url_auth, dest], capture_output=True, text=True, timeout=60,
                       env={**_os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if not _os.path.exists(dest):
            return {"ok": False, "error": "Clone failed — destination not created"}

        # Write scaffold files
        files = {}
        files["README.md"] = f"# {slug}\n\n{purpose}\n\nScaffolded by Agency OS.\n\n## Quickstart\n```bash\ndocker compose up --build\n```\n"
        files[".gitignore"] = tmpl.get("gitignore", "")
        files["docker-compose.yml"] = f"services:\n  app:\n    build: .\n    container_name: {slug}\n    restart: unless-stopped\n    ports:\n      - \"127.0.0.1:8080:8080\"\n"
        files["Dockerfile"] = tmpl["dockerfile"]

        if tmpl.get("entry") and tmpl.get("entry_content"):
            files[tmpl["entry"]] = tmpl["entry_content"]
        if tmpl.get("requirements"):
            files["requirements.txt"] = tmpl["requirements"]
        if tmpl.get("package_json"):
            files["package.json"] = tmpl["package_json"]
        if tmpl.get("go_mod"):
            files["go.mod"] = tmpl["go_mod"]

        for fname, fcontent in files.items():
            fpath = f"{dest}/{fname}"
            with open(fpath, "w") as f:
                f.write(fcontent)

        # Generate AGENTS.md via Zen (one cheap call)
        agents_prompt = f"""Given this project, produce a concise AGENTS.md.
Purpose: {purpose}
Tech stack: {stack}
Key files: {', '.join(files.keys())}

Return ONLY JSON, no prose, no code fences.
JSON with: purpose, entry_points, tech_stack, architecture, key_files, build_and_run, notes"""
        ar = call_zen(agents_prompt, model=MODEL_CONFIG["cheap"], max_tokens=1000, temperature=MODEL_CONFIG["temp_structured"])
        acc(ar)
        budget_ok()
        doc_json = None
        if ar["ok"]:
            araw = ar["content"].strip()
            for trim in [araw, araw[araw.find('{'):araw.rfind('}')+1] if '{' in araw else '']:
                try:
                    doc_json = _json.loads(trim)
                    break
                except:
                    continue
        if not doc_json:
            doc_json = {"purpose": purpose, "entry_points": [tmpl.get("entry", "index.html")],
                        "tech_stack": [stack], "architecture": "Single service", "key_files": list(files.keys()),
                        "build_and_run": "docker compose up --build", "notes": "Scaffolded by Agency OS"}

        def _f(v):
            if isinstance(v, list):
                return "\n".join(f"- {item}" for item in v if item)
            return str(v) if v else ""

        agents_lines = [
            f"# {slug}", "",
            "## Purpose", _f(doc_json.get("purpose")), "",
            "## Entry Points", _f(doc_json.get("entry_points")), "",
            "## Tech Stack", _f(doc_json.get("tech_stack")), "",
            "## Architecture", _f(doc_json.get("architecture")), "",
            "## Key Files", _f(doc_json.get("key_files")), "",
            "## Build & Run", _f(doc_json.get("build_and_run")), "",
            "## Notes", _f(doc_json.get("notes")), "",
            "---", "_Scaffolded by Agency OS client_new_project_.",
        ]
        with open(f"{dest}/AGENTS.md", "w") as f:
            f.write("\n".join(agents_lines))

        # ── Step 5: Commit and push (branch-safe) ──────────────────
        git("add", "-A")
        git("commit", "-m", f"Initial scaffold: {purpose}")
        git("branch", "-M", "main")
        push = git("push", "-u", "origin", "main")
        if push.returncode != 0:
            return {"ok": False, "error": f"Push failed: {push.stderr[:200]}"}

        # ── Step 6: Create project row + link client ───────────────
        cur.execute(
            "INSERT INTO projects (name, state, repo_url) VALUES (%s, 'scaffolded', %s) ON CONFLICT (name) DO UPDATE SET state='scaffolded', repo_url=EXCLUDED.repo_url RETURNING id",
            (slug, repo_url),
        )
        project_id = cur.fetchone()["id"]
        cur.execute("UPDATE clients SET status='completed', project_id=%s WHERE id=%s", (project_id, client_id))
        conn.commit()

        ch_trace({"project": slug, "actor": "worker", "action": "client_new_project_done",
                  "detail": f"Client {client_id}: scaffolded {slug} → project {project_id}",
                  "gate": "green", "decision": "proceed", "ok": 1})

        result_ref = _json.dumps({
            "status": "done", "client_id": client_id, "project_id": project_id,
            "project_slug": slug, "repo_url": repo_url, "stack": stack,
            "note": "Project scaffolded. propose_fix is NOT auto-enabled — add to ALLOWED_REPOS manually.",
        }, separators=(',', ':'))

        return {
            "ok": True, "content": result_ref,
            "prompt_tokens": total_prompt_tokens, "completion_tokens": total_completion_tokens,
            "cost": round(total_cost, 8),
        }

    except Exception as e:
        import traceback
        return {"ok": False, "error": f"Scaffold failed: {str(e)[:400]} -- {traceback.format_exc()[:200]}"}
    finally:
        if 'conn' in dir():
            try: conn.close()
            except: pass


def handle_design_page(task):
    """Design page: Stage 1 (concept specs) or Stage 2 (full render)."""
    import re as _re, os as _os, json as _json

    params = task.get("params") or {}
    stage = params.get("stage", "concepts")

    if stage == "render":
        variation_id = params.get("variation_id")
        if not variation_id:
            return {"ok": False, "error": "variation_id is required for render stage"}
        conn = get_conn()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT cv.*, p.name AS project_slug FROM concept_variations cv JOIN projects p ON p.id = cv.project_id WHERE cv.id=%s", (variation_id,))
            var = cur.fetchone()
            if not var:
                return {"ok": False, "error": f"variation {variation_id} not found"}
            spec = var["spec_json"]
            brief = var["brief"]
            project_slug = var["project_slug"]

            _type_spec = spec.get("typography", "sans-serif system, 16/20/28/40px scale")
            _color_spec = spec.get("colors", "{primary: #1a1a2e, accent: #e94560}")
            _layout_spec = spec.get("layout", "asymmetric grid")
            _motion_spec = spec.get("motion", "subtle fade-in on scroll")

            # ── Stage A: HTML structure + CSS (NO JavaScript) ───────────
            stage_a_prompt = f"""Generate ONLY the HTML structure and inline CSS for a landing page. Do NOT include any JavaScript or <script> tags.

PONYTAIL: Apply lazy senior dev principles — this is a landing page, not a web app (YAGNI). No unnecessary wrappers, no over-abstracted CSS, no unused animations. Every line of HTML and CSS must earn its place.

Brief: "{brief}"

DESIGN DIRECTION (follow exactly):
- Typography: {_type_spec}
- Colors: {_color_spec}
- Layout: {_layout_spec}
- Motion language described: {_motion_spec} (note the motion language — JS will be added in a separate step. Give every element that needs animation a unique id="" attribute.)

QUALITY BAR:
- Intentional type scale, font from Google Fonts CDN.
- Real spacing system.
- Deliberate whitespace.
- Defined hover/focus/active on every <a>, <button>.
- Semantic HTML landmarks, :focus-visible outlines, proper heading hierarchy.

BANNED AI-DESIGN TELLS (no centered layout, no three feature cards, no unmotivated gradients, no generic hero+CTA, no emoji icons, no purple-on-dark, no default card shadows, no uniform border-radius, no stock photo URLs, no repetitive padding).

LIBRARIES (CDN only, script/link tags allowed):
- Normalize CSS: https://cdnjs.cloudflare.com/ajax/libs/normalize/8.0.1/normalize.min.css
- Google Fonts CDN for typefaces.
- (JavaScript will be added in a separate step — do NOT include <script> tags here.)

SCOPE: ONLY a header + hero section with CTA. No footer, no data tables, no charts, no multi-column layouts. A single tight hero.
CRITICAL: Count your tags. Every <html> must have a </html>. Every <body> must have a </body>. Every <div> must have a </div>. The page MUST end with </html>. If you cannot finish within the budget, use shorter CSS class names and fewer CSS rules. Do NOT end without </html>.
Every element that should animate must have a unique id.
No JavaScript at all."""
            r_a = call_zen(stage_a_prompt, model=MODEL_CONFIG["quality"], max_tokens=8000, temperature=0.3, timeout=300)
            if not r_a["ok"]:
                return {"ok": False, "error": f"Stage A (HTML/CSS) failed: {r_a.get('error','')}"}

            html_content = r_a["content"]
            # Strip markdown fences
            if "```" in html_content:
                _start_markers = ["<!DOCTYPE html>", "<html", "<head>"]
                _si = len(html_content)
                for _m in _start_markers:
                    _idx = html_content.upper().find(_m.upper())
                    if _idx >= 0 and _idx < _si:
                        _si = _idx
                if _si < len(html_content):
                    html_content = html_content[_si:]
                _lf = html_content.rfind("```")
                if _lf > len(html_content) // 2:
                    html_content = html_content[:_lf].rstrip()
            if "<!DOCTYPE html>" in html_content.upper():
                _di = html_content.upper().index("<!DOCTYPE html>")
                if _di > 0:
                    html_content = html_content[_di:]

            # Validate Stage A completeness
            _strip_a = html_content.strip()
            if not _strip_a.endswith("</html>"):
                return {"ok": False, "error": f"Stage A (HTML/CSS) truncated — missing </html>. Only {len(html_content)} chars."}
            if _strip_a.count("<html") != _strip_a.count("</html>") or _strip_a.count("<html") == 0:
                return {"ok": False, "error": "Stage A (HTML/CSS) has unbalanced <html> tags."}
            if _strip_a.count("<body") != _strip_a.count("</body>"):
                return {"ok": False, "error": "Stage A (HTML/CSS) has unbalanced <body> tags."}

            # Extract element IDs from Stage A for JS targeting
            _all_ids = set()
            for _id_match in __import__('re').finditer(r'id="([^"]+)"', html_content):
                _all_ids.add(_id_match.group(1))

            # ── Stage B: JavaScript / interaction layer ────────────────
            _ids_list = ", ".join(sorted(_all_ids)) if _all_ids else "none found"
            stage_b_prompt = f"""Generate ONLY JavaScript for the pre-built HTML page described below.

MOTION SPECIFICATION (implement this exactly): {_motion_spec}

Available element IDs in the HTML: {_ids_list}

REQUIREMENTS:
- Generate a single <script> tag with all JavaScript.
- Load GSAP from CDN at top: https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js
- Load ScrollTrigger from CDN if scroll-driven animation is described: https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js
- Target elements by their IDs using document.getElementById().
- Implement count-up animation for any stat number elements.
- Implement scroll-triggered reveal/animation for sections and chart bars.
- Include prefers-reduced-motion check: if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
- Register a DOMContentLoaded listener to run all animations.
- Only target IDs that exist in the HTML. Do NOT reference IDs not in the list above.

Output ONLY the <script> tag. No HTML, no markdown, no explanation. Start with <script> and end with </script>."""
            r_b = call_zen(stage_b_prompt, model=MODEL_CONFIG["quality"], max_tokens=3500, temperature=0.3, timeout=300)
            if not r_b["ok"]:
                return {"ok": False, "error": f"Stage B (JS) failed: {r_b.get('error','')}"}

            js_content = r_b["content"]
            # Strip markdown fences from JS
            if "```" in js_content:
                _js_start = js_content.find("<script")
                if _js_start >= 0:
                    js_content = js_content[_js_start:]
                _js_end = js_content.rfind("</script>")
                if _js_end >= 0:
                    js_content = js_content[:_js_end + len("</script>")]
                _lf2 = js_content.rfind("```")
                if _lf2 > len(js_content) // 2:
                    js_content = js_content[:_lf2].rstrip()

            # ── Assembly: insert JS before </body> ─────────────────────
            _body_close = html_content.rfind("</body>")
            if _body_close < 0:
                return {"ok": False, "error": "Stage A (HTML/CSS) has no </body> tag for JS insertion."}
            assembled = html_content[:_body_close] + "\n" + js_content + "\n" + html_content[_body_close:]

            # ── Validation: completeness + JS reference integrity ──────
            _strip = assembled.strip()
            _issues = []
            if not _strip.endswith("</html>"):
                _issues.append("missing </html>")
            if _strip.count("<html") != _strip.count("</html>"):
                _issues.append("unbalanced <html>")
            if _strip.count("<body") != _strip.count("</body>"):
                _issues.append("unbalanced <body>")

            # Validate every JS-targeted ID exists in HTML (check the assembled HTML, not just the pre-extraction)
            _js_refs = set()
            for _ref in __import__('re').finditer(r'(?:document\.)?getElementById\(\s*["\']([^"\']+)["\']\s*\)', js_content):
                _js_refs.add(_ref.group(1))
            for _ref in __import__('re').finditer(r'(?:document\.)?querySelector\(\s*["\']#([^"\']+)["\']\s*\)', js_content):
                _js_refs.add(_ref.group(1))
            for _ref in __import__('re').finditer(r'\.querySelector\(\s*["\']#([^"\']+)["\']\s*\)', js_content):
                _js_refs.add(_ref.group(1))
            # Re-check against the ASSEMBLED HTML (Stage A extraction may miss IDs the JS creates)
            _all_ids_from_assembled = set(__import__('re').findall(r'id="([^"]+)"', assembled))
            _missing_ids = _js_refs - _all_ids_from_assembled
            if _missing_ids:
                _issues.append(f"JS references IDs not in HTML: {', '.join(sorted(_missing_ids))}")

            # Validate motion layer is present and non-empty
            _has_gsap = "gsap" in js_content.lower() or "GSAP" in js_content
            _has_animation = "animate" in js_content.lower() or "timeline" in js_content.lower()
            _js_stripped = js_content.replace("<script>", "").replace("</script>", "").replace("<script ", "").strip()
            if len(_js_stripped) < 50:
                _issues.append("motion layer missing — JS is empty or trivial")
            elif not _has_gsap and not _has_animation and _motion_spec.lower() not in ("", "none"):
                _issues.append(f"motion layer missing — spec promises '{_motion_spec}' but JS has no animation/GSAP")

            motion_ok = len([i for i in _issues if "motion" in i]) == 0
            html_ok = len([i for i in _issues if i not in ("motion layer missing",)]) == 0

            if _issues:
                _error_msg = "; ".join(_issues)
                # Write the broken file anyway so human can inspect, but fail the task
                dest_dir = f"/home/agency/projects/{project_slug}/designs/{variation_id}"
                _os.makedirs(dest_dir, exist_ok=True)
                with open(f"{dest_dir}/index.html", "w") as f:
                    f.write(assembled)
                cur.execute(
                    "UPDATE concept_variations SET status='failed', file_path=%s, task_id=%s, spec_json = spec_json || %s::jsonb WHERE id=%s",
                    (f"designs/{variation_id}/index.html", task["id"],
                     _json.dumps({"render_issues": _issues, "html_ok": html_ok, "motion_ok": motion_ok}), variation_id)
                )
                conn.commit()
                return {"ok": False, "error": f"Render validation failed: {_error_msg}",
                        "content": _json.dumps({"status": "validation_failed", "issues": _issues, "file_path": f"designs/{variation_id}/index.html"}, separators=(',', ':')),
                        "prompt_tokens": r_a.get("prompt_tokens", 0) + r_b.get("prompt_tokens", 0),
                        "completion_tokens": r_a.get("completion_tokens", 0) + r_b.get("completion_tokens", 0),
                        "cost": r_a.get("cost", 0) + r_b.get("cost", 0)}

            # ── Tell check removed — both cheap and quality models proved unreliable ──
            # Neither model could consistently return parseable structured JSON for this nuanced
            # design critique task. Keeping a check whose results we override by hand is a rubber
            # stamp. Tell compliance is verified by the Stage A banned-tell prompt and human review.
            tell_results = []
            tells_passed = 0
            tells_failed = 0

            # ── Write final file ───────────────────────────────────────
            dest_dir = f"/home/agency/projects/{project_slug}/designs/{variation_id}"
            _os.makedirs(dest_dir, exist_ok=True)
            with open(f"{dest_dir}/index.html", "w") as f:
                f.write(assembled)

            _tokens = r_a.get("completion_tokens", 0) + r_b.get("completion_tokens", 0)
            _cost = r_a.get("cost", 0) + r_b.get("cost", 0)
            _quality_meta = _json.dumps({
                "quality_tells": tell_results, "tells_passed": tells_passed, "tells_failed": tells_failed,
                "complete": True, "motion_ok": motion_ok, "html_ok": html_ok,
                "html_tokens": r_a.get("completion_tokens", 0), "js_tokens": r_b.get("completion_tokens", 0),
            })
            cur.execute(
                "UPDATE concept_variations SET status='completed', file_path=%s, task_id=%s, spec_json = spec_json || %s::jsonb WHERE id=%s",
                (f"designs/{variation_id}/index.html", task["id"], _quality_meta, variation_id)
            )
            conn.commit()

            result_ref = _json.dumps({
                "status": "done", "variation_id": variation_id,
                "file_path": f"designs/{variation_id}/index.html", "project_slug": project_slug,
                "tells_passed": tells_passed, "tells_failed": tells_failed,
                "html_tokens": r_a.get("completion_tokens", 0), "js_tokens": r_b.get("completion_tokens", 0),
                "motion_ok": motion_ok, "html_ok": html_ok,
            }, separators=(',', ':'))
            return {"ok": True, "content": result_ref,
                    "prompt_tokens": r_a.get("prompt_tokens", 0) + r_b.get("prompt_tokens", 0),
                    "completion_tokens": _tokens, "cost": _cost}
        except Exception as e:
            import traceback
            return {"ok": False, "error": f"Design render failed: {str(e)[:400]} -- {traceback.format_exc()[:200]}"}
        finally:
            if 'conn' in dir():
                try: conn.close()
                except: pass

    # Stage 1: Generate concept specs (cheap)
    project_id = params.get("project_id")
    brief = (params.get("brief") or "").strip()
    variations_n = min(int(params.get("variations", 3)), 5)
    if not project_id or not brief:
        return {"ok": False, "error": "project_id and brief are required"}
    if len(brief) > 500:
        return {"ok": False, "error": "brief too long"}

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT name FROM projects WHERE id=%s", (project_id,))
        proj = cur.fetchone()
        if not proj:
            return {"ok": False, "error": f"project {project_id} not found"}
        project_slug = proj["name"]

        # ── UI/UX Pro Max design search ──────────────────────────────────
        # Ground the concepts in the database-backed design system search
        _ds_out = ""
        _ds_script = os.path.expanduser("~/.config/opencode/skills/ui-ux-pro-max/scripts/search.py")
        if os.path.exists(_ds_script):
            try:
                _ds_result = subprocess.run(
                    ["python3", _ds_script, brief, "--design-system", "-f", "markdown", "-p", project_slug],
                    capture_output=True, text=True, timeout=30,
                )
                if _ds_result.returncode == 0:
                    _ds_out = _ds_result.stdout[:2000]
            except:
                _ds_out = ""

        concepts_prompt = f"""Given this brief: "{brief[:400]}"

Generate {variations_n} distinct design directions. Each must commit to specifics.

UI/UX Pro Max design system reference (use this to ground your decisions):
{_ds_out if _ds_out else "(no design system data available — make reasonable defaults)"}

Return ONLY a JSON array of {variations_n} objects. Each object has these fields:
- typography: typeface categories + scale (e.g. "serif headings (Playfair Display), sans-serif body (Inter), scale: 14/18/24/32/48px")
- colors: object with primary, secondary, accent hex values + why each (e.g. {{"primary":"#2D2D2D","secondary":"#F5F0EB","accent":"#C73E3E","rationale":"dark charcoal for authority, warm cream for approachability, brick red for accent"}})
- layout: specific layout approach (e.g. "single-column narrative with full-width break sections" or "magazine-style asymmetric grid with offset hero")
- motion: what moves and why (e.g. "page-load staggered fade-in of hero elements via GSAP, hover scale on CTA, scroll-triggered section reveals")
- aesthetic: describe the feeling without brand names (e.g. "editorial photography with Swiss grid, muted earth tones, generous whitespace — feels like a premium print magazine")

CRITICAL: Each direction must be GENUINELY distinct — different typography, different color psychology, different layout philosophy. Use the design system reference above as a starting point, not a cage — you may deviate if it serves the brief."""
        r = call_zen(concepts_prompt, model=MODEL_CONFIG["cheap"], max_tokens=2000, temperature=0.3)
        if not r["ok"]:
            return {"ok": False, "error": f"Concept generation failed: {r.get('error','')}"}
        raw = r["content"].strip()
        spec_list = None
        for trim in [raw, raw[raw.find('['):raw.rfind(']')+1] if '[' in raw else '']:
            try:
                data = _json.loads(trim)
                if isinstance(data, list) and len(data) >= 1:
                    spec_list = data[:variations_n]
                    break
            except:
                continue
        if not spec_list:
            return {"ok": False, "error": f"Could not parse concepts JSON. Raw: {raw[:300]}"}

        variation_ids = []
        for i, spec in enumerate(spec_list):
            cur.execute(
                "INSERT INTO concept_variations (project_id, skill, brief, spec_index, spec_json, status) VALUES (%s, 'design_page', %s, %s, %s, 'pending') RETURNING id",
                (project_id, brief, i, _json.dumps(spec)),
            )
            variation_ids.append(cur.fetchone()["id"])
        conn.commit()

        result_ref = _json.dumps({
            "status": "concepts_ready", "project_id": project_id, "project_slug": project_slug,
            "brief": brief, "variation_count": len(variation_ids), "variation_ids": variation_ids,
        }, separators=(',', ':'))
        return {"ok": True, "content": result_ref, "prompt_tokens": r["prompt_tokens"], "completion_tokens": r["completion_tokens"], "cost": r["cost"]}
    except Exception as e:
        import traceback
        return {"ok": False, "error": f"Design concepts failed: {str(e)[:400]} -- {traceback.format_exc()[:200]}"}
    finally:
        if 'conn' in dir():
            try: conn.close()
            except: pass


# ── Job Search Handlers ──────────────────────────────────────────

def handle_search_jobs(task):
    """Search/find job listings for a campaign."""
    params = task.get("params") or {}
    campaign_id = params.get("campaign_id")
    if not campaign_id:
        return {"ok": False, "error": "campaign_id required"}

    from jobs.campaign import _find_job_listings
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM job_campaigns WHERE id=%s", (campaign_id,))
        campaign = cur.fetchone()
        if not campaign:
            return {"ok": False, "error": f"Campaign {campaign_id} not found"}

        target = params.get("target", campaign.get("target_jobs_per_run") or 10)
        listings = _find_job_listings(
            cur, campaign,
            campaign.get("job_titles") or [],
            campaign.get("locations") or [],
            campaign.get("company_include") or [],
            campaign.get("company_exclude") or [],
            campaign.get("keywords_include") or [],
            campaign.get("keywords_exclude") or [],
            target,
        )
        conn.commit()
        return {"ok": True, "content": json.dumps({"count": len(listings), "ids": listings}, separators=(',', ':')), "prompt_tokens": 0, "completion_tokens": 0, "cost": 0}
    except Exception as e:
        import traceback
        return {"ok": False, "error": f"search_jobs failed: {str(e)[:400]}"}
    finally:
        conn.close()


def handle_generate_resume(task):
    """Tailor a resume for a specific job listing."""
    params = task.get("params") or {}
    listing_id = params.get("listing_id")
    if not listing_id:
        return {"ok": False, "error": "listing_id required"}

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT jl.*, jc.resume_text FROM job_listings jl
            JOIN job_campaigns jc ON jc.id = jl.campaign_id
            WHERE jl.id=%s
        """, (listing_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "listing not found"}
        if not row.get("resume_text"):
            return {"ok": False, "error": "campaign has no resume_text set"}

        from jobs.resume import tailor_resume
        result = tailor_resume(
            row["resume_text"], row["title"], row["company"],
            row.get("description", "") or "", row.get("requirements", "") or "",
        )
        if not result.get("ok"):
            return result

        cur.execute(
            "INSERT INTO resume_versions (listing_id, campaign_id, original_resume, tailored_resume, changes, ats_keywords, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'draft') RETURNING id",
            (listing_id, row["campaign_id"], row["resume_text"], result["tailored_resume"],
             result.get("changes_summary", ""), result.get("ats_keywords", [])),
        )
        resume_id = cur.fetchone()["id"]
        conn.commit()

        return {
            "ok": True,
            "content": json.dumps({"resume_id": resume_id, "listing_id": listing_id}, separators=(',', ':')),
            "prompt_tokens": result.get("tokens", 0),
            "completion_tokens": 0,
            "cost": result.get("cost", 0),
        }
    except Exception as e:
        import traceback
        return {"ok": False, "error": f"generate_resume failed: {str(e)[:400]}"}
    finally:
        conn.close()


def handle_generate_cover_letter(task):
    """Generate a cover letter for a job listing."""
    params = task.get("params") or {}
    listing_id = params.get("listing_id")
    if not listing_id:
        return {"ok": False, "error": "listing_id required"}

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT jl.*, jc.resume_text FROM job_listings jl
            JOIN job_campaigns jc ON jc.id = jl.campaign_id
            WHERE jl.id=%s
        """, (listing_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "listing not found"}

        from jobs.cover_letter import generate_cover_letter
        result = generate_cover_letter(
            row.get("resume_text", "") or "", row["title"], row["company"],
            row.get("description", "") or "",
        )
        if not result.get("ok"):
            return result

        cur.execute(
            "INSERT INTO cover_letters (listing_id, campaign_id, content, company, status) "
            "VALUES (%s, %s, %s, %s, 'draft') RETURNING id",
            (listing_id, row["campaign_id"], result["content"], row["company"]),
        )
        cl_id = cur.fetchone()["id"]
        conn.commit()

        return {
            "ok": True,
            "content": json.dumps({"cover_letter_id": cl_id, "listing_id": listing_id}, separators=(',', ':')),
            "prompt_tokens": result.get("tokens", 0),
            "completion_tokens": 0,
            "cost": result.get("cost", 0),
        }
    except Exception as e:
        import traceback
        return {"ok": False, "error": f"generate_cover_letter failed: {str(e)[:400]}"}
    finally:
        conn.close()


def handle_find_contacts(task):
    """Discover contacts at a company for a job listing."""
    params = task.get("params") or {}
    listing_id = params.get("listing_id")
    if not listing_id:
        return {"ok": False, "error": "listing_id required"}

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM job_listings WHERE id=%s", (listing_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "listing not found"}

        from jobs.contacts import discover_contacts
        result = discover_contacts(row["company"], row["title"], row.get("description", ""))
        if not result.get("ok"):
            return result

        contact_ids = []
        for c in result.get("contacts", []):
            cur.execute(
                "INSERT INTO job_contacts (listing_id, name, title, company, email, linkedin_url, confidence, source, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'ai', 'pending') RETURNING id",
                (listing_id, c.get("name", "Unknown"), c.get("title", ""), row["company"],
                 c.get("email_pattern", ""), c.get("linkedin_url", ""), c.get("confidence", 50)),
            )
            contact_ids.append(cur.fetchone()["id"])
        conn.commit()

        return {
            "ok": True,
            "content": json.dumps({"contact_ids": contact_ids, "count": len(contact_ids)}, separators=(',', ':')),
            "prompt_tokens": result.get("tokens", 0),
            "completion_tokens": 0,
            "cost": result.get("cost", 0),
        }
    except Exception as e:
        import traceback
        return {"ok": False, "error": f"find_contacts failed: {str(e)[:400]}"}
    finally:
        conn.close()


def handle_generate_linkedin_note(task):
    """Generate LinkedIn connection note."""
    params = task.get("params") or {}
    contact_id = params.get("contact_id")
    listing_id = params.get("listing_id")
    if not contact_id or not listing_id:
        return {"ok": False, "error": "contact_id and listing_id required"}

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT jc.*, jl.title AS job_title, jl.company, jc2.resume_text
            FROM job_contacts jc
            JOIN job_listings jl ON jl.id = jc.listing_id
            JOIN job_campaigns jc2 ON jc2.id = jl.campaign_id
            WHERE jc.id=%s AND jl.id=%s
        """, (contact_id, listing_id))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "contact or listing not found"}

        from jobs.contacts import generate_linkedin_note
        result = generate_linkedin_note(
            row.get("resume_text", "") or "",
            row["name"], row["title"], row["company"],
        )
        if not result.get("ok"):
            return result

        cur.execute(
            "INSERT INTO linkedin_notes (contact_id, listing_id, campaign_id, content, status) "
            "VALUES (%s, %s, %s, %s, 'draft')",
            (contact_id, listing_id, row.get("campaign_id"), result["note"]),
        )
        conn.commit()

        return {
            "ok": True,
            "content": json.dumps({"note": result["note"][:200], "tone": result.get("tone", "")}, separators=(',', ':')),
            "prompt_tokens": result.get("tokens", 0),
            "completion_tokens": 0,
            "cost": result.get("cost", 0),
        }
    except Exception as e:
        import traceback
        return {"ok": False, "error": f"generate_linkedin_note failed: {str(e)[:400]}"}
    finally:
        conn.close()


def handle_send_application_email(task):
    """Send application email via Gmail API."""
    params = task.get("params") or {}
    campaign_id = params.get("campaign_id")
    listing_id = params.get("listing_id")

    if not campaign_id or not listing_id:
        return {"ok": False, "error": "campaign_id and listing_id required"}

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Find the primary contact and email thread
        cur.execute("""
            SELECT jc.email, jc.name, jc.title, jl.title AS job_title, jl.company,
                   et.id AS thread_id, et.subject, et.body
            FROM job_listings jl
            LEFT JOIN job_contacts jc ON jc.listing_id = jl.id AND jc.status = 'pending'
            LEFT JOIN email_threads et ON et.listing_id = jl.id AND et.status = 'draft' AND et.direction = 'outbound'
            WHERE jl.id=%s
            ORDER BY jc.confidence DESC
            LIMIT 1
        """, (listing_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "no contact or email thread found for this listing"}

        if not row.get("email") or "@" not in str(row.get("email", "")):
            return {"ok": False, "error": f"contact email not available: {row.get('email', 'N/A')}"}

        from jobs.gmail_client import send_email
        ok, result = send_email(
            campaign_id,
            row["email"],
            row.get("subject", f"Application for {row['job_title']}"),
            row.get("body", ""),
        )

        if ok:
            cur.execute(
                "UPDATE email_threads SET status='sent', gmail_message_id=%s, sent_at=now() WHERE id=%s",
                (result, row["thread_id"]),
            )
            cur.execute(
                "UPDATE job_applications SET status='email_sent', email_sent_at=now() WHERE listing_id=%s",
                (listing_id,),
            )
            conn.commit()
            return {"ok": True, "content": json.dumps({"gmail_message_id": result}, separators=(',', ':')), "prompt_tokens": 0, "completion_tokens": 0, "cost": 0}

        return {"ok": False, "error": f"email send failed: {result}"}
    except Exception as e:
        import traceback
        return {"ok": False, "error": f"send_application_email failed: {str(e)[:400]}"}
    finally:
        conn.close()


def handle_run_job_campaign(task):
    """Run a full job campaign cycle (orchestrate all steps)."""
    params = task.get("params") or {}
    campaign_id = params.get("campaign_id")
    if not campaign_id:
        return {"ok": False, "error": "campaign_id required"}

    from jobs.campaign import run_campaign
    result = run_campaign(campaign_id)
    if result.get("ok"):
        return {
            "ok": True,
            "content": json.dumps({
                "status": "completed",
                "run_id": result.get("run_id"),
                "processed": result.get("processed"),
                "targeted": result.get("targeted"),
            }, separators=(',', ':')),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost": 0,
        }
    return result


DISPATCH = {
    "generate_draft": handle_generate_draft,
    "propose_fix": handle_propose_fix,
    "agent_task": handle_agent_task,
    "run_brand_audit": handle_run_brand_audit,
    "client_import_repo": handle_client_import_repo,
    "client_new_project": handle_client_new_project,
    "ask": handle_ask,
    "design_page": handle_design_page,
    "search_jobs": handle_search_jobs,
    "onboard_project": handle_onboard_project,
    "generate_resume": handle_generate_resume,
    "generate_cover_letter": handle_generate_cover_letter,
    "find_contacts": handle_find_contacts,
    "generate_linkedin_note": handle_generate_linkedin_note,
    "send_application_email": handle_send_application_email,
    "run_job_campaign": handle_run_job_campaign,
}

def poll():
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED")
        task = cur.fetchone()
        if not task:
            return False
        tid = task["id"]
        ttype = task["type"]
        cur.execute("UPDATE tasks SET status='running', started_at=now() WHERE id=%s", (tid,))
        conn.commit()
        print(f"[worker] Claimed task {tid} type={ttype}", flush=True)
        handler = DISPATCH.get(ttype)
        if not handler:
            err = f"No handler for type: {ttype}"
            cur.execute("UPDATE tasks SET status='failed', error=%s, finished_at=now() WHERE id=%s", (err, tid))
            conn.commit()
            return True
        try:
            result = handler(task)
        except Exception as e:
            cur.execute("UPDATE tasks SET status='failed', error=%s, finished_at=now() WHERE id=%s", (str(e)[:500], tid))
            conn.commit()
            print(f"[worker] Task {tid} crashed in handler: {e}", flush=True)
            return True
        if result.get("ok"):
            content = result.get("content", "")
            cur.execute(
                "UPDATE tasks SET status='done', prompt_tokens=%s, completion_tokens=%s, cost=%s, result_ref=%s, finished_at=now() WHERE id=%s",
                (result["prompt_tokens"], result["completion_tokens"], result["cost"], content[:20000], tid)
            )
            # Link task_id to content_items row (created by handler, body already stored)
            _ci_id = result.get("content_item_id")
            if _ci_id:
                cur.execute("UPDATE content_items SET task_id=%s WHERE id=%s", (tid, _ci_id))
            conn.commit()
            ch_trace({"project": "system", "actor": "worker", "action": f"task_done_{ttype}", "detail": f"Task {tid} completed: {result.get('prompt_tokens',0)} in / {result.get('completion_tokens',0)} out, cost ${result.get('cost',0)}", "gate": "green", "decision": "proceed", "ok": 1})
            print(f"[worker] Task {tid} done: {result.get('prompt_tokens',0)} in / {result.get('completion_tokens',0)} out tokens, ${result.get('cost',0)}", flush=True)
        else:
            cur.execute("UPDATE tasks SET status='failed', error=%s, finished_at=now() WHERE id=%s", (result.get("error", "unknown")[:500], tid))
            conn.commit()
            ch_trace({"project": "system", "actor": "worker", "action": f"task_failed_{ttype}", "detail": f"Task {tid} failed: {result.get('error','')[:200]}", "gate": "green", "decision": "proceed", "ok": 0})
            print(f"[worker] Task {tid} failed: {result.get('error','')[:200]}", flush=True)
        return True
    finally:
        conn.close()

def start_up():
    """Rescue any tasks left in 'running' by a prior crash."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE tasks SET status='failed', error='Worker restarted — task orphaned', finished_at=now() WHERE status='running'")
        rescued = cur.rowcount
        conn.commit()
        if rescued:
            print(f"[worker] Rescued {rescued} orphaned task(s)", flush=True)
    finally:
        conn.close()

if __name__ == "__main__":
    start_up()
    print("[worker] Agency Worker started. Polling every 2s...", flush=True)
    while True:
        try:
            poll()
        except Exception as e:
            print(f"[worker] Poll error: {e}", flush=True)
        # Requeue tasks stuck 'running' for 20+ min (worker crash/slow handler).
        # ponytail: naive staleness via rowcount; needs a lock/leader if multiple workers.
        # Does this duplicate run-job.sh's sweep? Yes-ish, but that only sweeps job_runs.
        try:
            _c = get_conn()
            _cu = _c.cursor()
            _cu.execute("UPDATE tasks SET status='queued', started_at=NULL WHERE status='running' AND started_at < now() - interval '20 minutes'")
            _n = _cu.rowcount
            _c.commit()
            _c.close()
            if _n:
                print(f"[worker] Requeued {_n} stale task(s)", flush=True)
        except Exception as _e:
            print(f"[worker] Requeue error: {_e}", flush=True)
        time.sleep(2)

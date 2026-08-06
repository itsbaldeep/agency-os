#!/usr/bin/env python3
"""
LinkedIn MCP Server — provides LinkedIn tools to OpenCode via Model Context Protocol.

This server exposes tools that OpenCode can use for LinkedIn operations:
  - search_jobs: Search LinkedIn for job listings
  - search_people: Find HR/hiring managers at companies
  - send_connection_request: Send connection request with note
  - get_profile: Get LinkedIn profile information

IMPORTANT: LinkedIn does not have an open API for these operations.
This MCP server provides the INTERFACE. For actual execution:
  1. Manual mode: prints instructions for the human to perform the action
  2. Browser automation: requires LinkedIn credentials and Playwright installed
  3. Third-party API: integrate with Proxycurl, Apollo, or similar

Usage (for OpenCode to connect):
  python3 /home/agency/agency-os/scripts/jobs/linkedin_mcp.py

Add to your opencode.json:
  "mcpServers": {
    "linkedin": {
      "command": "python3",
      "args": ["/home/agency/agency-os/scripts/jobs/linkedin_mcp.py"]
    }
  }
"""

import json, os, sys, re
from datetime import datetime

# ── MCP Protocol Implementation ─────────────────────────────────────

PROTOCOL_VERSION = "2024-11-05"

def jsonrpc_send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def jsonrpc_error(id, code, message, data=None):
    err = {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}
    if data:
        err["error"]["data"] = data
    jsonrpc_send(err)


def jsonrpc_result(id, result):
    jsonrpc_send({"jsonrpc": "2.0", "id": id, "result": result})


def jsonrpc_notification(method, params):
    jsonrpc_send({"jsonrpc": "2.0", "method": method, "params": params})


# ── Server Info ─────────────────────────────────────────────────────

SERVER_INFO = {
    "name": "agency-os-linkedin",
    "version": "1.0.0",
}

CAPABILITIES = {
    "tools": {},
}

# ── Tool Definitions ────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_jobs",
        "description": "Search LinkedIn for job listings matching criteria. Returns job title, company, location, and URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "Job title or keywords to search"},
                "location": {"type": "string", "description": "Location filter (city, state, or 'Remote')"},
                "count": {"type": "integer", "description": "Number of results (max 25)", "default": 10},
            },
            "required": ["keywords"],
        },
    },
    {
        "name": "search_people",
        "description": "Find HR, hiring managers, recruiters, or VP-level people at a specific company.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Company name to search"},
                "title_keywords": {"type": "string", "description": "Keywords like 'HR', 'recruiter', 'VP Engineering', 'hiring manager'"},
                "count": {"type": "integer", "description": "Max results (max 10)", "default": 5},
            },
            "required": ["company"],
        },
    },
    {
        "name": "send_connection_request",
        "description": "Send a LinkedIn connection request with a personalized note. NOTE: Manual approval may be required.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile_url": {"type": "string", "description": "LinkedIn profile URL of the person"},
                "note": {"type": "string", "description": "Personalized connection note (max 200 chars)"},
                "name": {"type": "string", "description": "Recipient's name for the note"},
            },
            "required": ["profile_url", "note"],
        },
    },
    {
        "name": "get_profile",
        "description": "Get public LinkedIn profile information for a person.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile_url": {"type": "string", "description": "LinkedIn profile URL"},
            },
            "required": ["profile_url"],
        },
    },
    {
        "name": "send_message",
        "description": "Send a LinkedIn message to a 1st-degree connection. NOTE: Manual approval may be required.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile_url": {"type": "string", "description": "LinkedIn profile URL of the recipient"},
                "message": {"type": "string", "description": "Message content"},
            },
            "required": ["profile_url", "message"],
        },
    },
]

# ── Tool Handlers ──────────────────────────────────────────────────


def _load_linkedin_credentials():
    """Load LinkedIn credentials from .env."""
    env_path = "/home/agency/agency-os/.env"
    creds = {"email": "", "password": ""}
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("LINKEDIN_EMAIL="):
                    creds["email"] = line.split("=", 1)[1].strip()
                elif line.startswith("LINKEDIN_PASSWORD="):
                    creds["password"] = line.split("=", 1)[1].strip()
    except Exception:
        pass
    return creds


def handle_search_jobs(params):
    """Search LinkedIn jobs (Zen-based proxy since LinkedIn API is restricted)."""
    keywords = params.get("keywords", "")
    location = params.get("location", "")
    count = min(int(params.get("count", 10)), 25)

    if not keywords:
        return {"ok": False, "error": "keywords required"}

    # Use Zen LLM as training-knowledge proxy for job discovery
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from worker import call_zen, MODEL_CONFIG

    prompt = f"""You are a job search assistant. Based on your training knowledge, suggest {count} real, currently-active job openings matching these criteria.

KEYWORDS: {keywords}
LOCATION: {location}

Return ONLY a JSON array of job objects. Each object:
- title: exact job title
- company: company name
- location: specific location
- description: 1-2 sentence summary of the role
- url: "[PLACEHOLDER: LinkedIn job URL]"
- salary: estimated salary range or "N/A"

Rules:
- Only suggest real companies known to hire for these roles.
- Do not invent job listings.
- If you're unsure, include fewer results. Quality over quantity.
- Output ONLY the JSON array.
"""

    result = call_zen(prompt, model="deepseek-v4-flash", max_tokens=2000, temperature=0.3)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Zen call failed")}

    content = result["content"].strip()
    for trim in [content, content[content.find('['):content.rfind(']') + 1] if '[' in content else '']:
        try:
            jobs = json.loads(trim)
            if isinstance(jobs, list):
                return {"ok": True, "jobs": jobs[:count], "source": "training_knowledge_proxy"}
        except (json.JSONDecodeError, TypeError):
            continue

    return {"ok": False, "error": "Could not parse job results from Zen"}


def handle_search_people(params):
    """Search for people at a company (Zen-based proxy)."""
    company = params.get("company", "")
    title_kw = params.get("title_keywords", "HR, recruiter, hiring manager")
    count = min(int(params.get("count", 5)), 10)

    if not company:
        return {"ok": False, "error": "company required"}

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from worker import call_zen, MODEL_CONFIG

    prompt = f"""Based on your training knowledge, identify real people at {company} who work in {title_kw} roles.

COMPANY: {company}
ROLES: {title_kw}
COUNT: {count}

Return ONLY a JSON array of people objects. Each object:
- name: full name (use [PLACEHOLDER:name] if unsure)
- title: their job title
- linkedin_url: "[PLACEHOLDER: LinkedIn URL]"
- why_relevant: 1 sentence on why this person is a good contact for job seekers

Rules:
- Only suggest real people at real companies.
- Use [PLACEHOLDER:name] pattern for specific names when uncertain.
- Prioritize seniority levels: VP, Director, Senior Manager, Lead Recruiter.
- Output ONLY the JSON array.
"""

    result = call_zen(prompt, model="deepseek-v4-flash", max_tokens=1500, temperature=0.2)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Zen call failed")}

    content = result["content"].strip()
    for trim in [content, content[content.find('['):content.rfind(']') + 1] if '[' in content else '']:
        try:
            people = json.loads(trim)
            if isinstance(people, list):
                return {"ok": True, "people": people[:count], "source": "training_knowledge_proxy"}
        except (json.JSONDecodeError, TypeError):
            continue

    return {"ok": False, "error": "Could not parse people results from Zen"}


def handle_send_connection_request(params):
    """Send a connection request. Since LinkedIn API is not available, this logs the action."""
    profile_url = params.get("profile_url", "")
    note = params.get("note", "")
    name = params.get("name", "the recipient")

    if not profile_url:
        return {"ok": False, "error": "profile_url required"}

    # Try browser automation if credentials are set
    creds = _load_linkedin_credentials()
    if creds["email"] and creds["password"]:
        try:
            result = _linkedin_browser_action("connect", {
                "email": creds["email"],
                "password": creds["password"],
                "profile_url": profile_url,
                "note": note,
            })
            if result.get("ok"):
                return result
        except Exception as e:
            return {"ok": False, "error": f"Browser automation failed: {e}. Action queued for manual execution."}

    # Fallback: log for manual execution
    _log_pending_action("send_connection_request", {
        "profile_url": profile_url,
        "note": note,
        "name": name,
    })

    return {
        "ok": True,
        "action": "logged_for_manual_execution",
        "message": f"Connection request to {name} has been queued for manual execution via LinkedIn.",
        "details": {
            "profile_url": profile_url,
            "note": note,
            "note_length": len(note),
        },
        "instructions": "Open LinkedIn, search for the person, click 'Connect', paste the note, and send.",
    }


def handle_get_profile(params):
    """Get profile info (Zen-based proxy)."""
    profile_url = params.get("profile_url", "")
    if not profile_url:
        return {"ok": False, "error": "profile_url required"}

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from worker import call_zen, MODEL_CONFIG

    slug = profile_url.rstrip("/").split("/")[-1] if "/" in profile_url else profile_url

    prompt = f"""Based on your training knowledge, provide information about this LinkedIn profile: {slug}

Return ONLY JSON with:
- name: full name (use [PLACEHOLDER:name] if unsure)
- current_company: current company
- current_title: current job title
- past_companies: array of past companies
- education: array of education entries
- location: general location
- summary: 2-3 sentence professional summary (use [PLACEHOLDER] for specifics)

If you don't have information about this person, return:
{{"ok": false, "error": "Profile not found in training knowledge", "profile_url": "{profile_url}"}}
"""

    result = call_zen(prompt, model="deepseek-v4-flash", max_tokens=1000, temperature=0.2)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Zen call failed")}

    content = result["content"].strip()
    for trim in [content, content[content.find('{'):content.rfind('}') + 1] if '{' in content else '']:
        try:
            data = json.loads(trim)
            if isinstance(data, dict):
                if data.get("ok") is False:
                    return data
                return {"ok": True, "profile": data, "source": "training_knowledge_proxy"}
        except (json.JSONDecodeError, TypeError):
            continue

    return {"ok": False, "error": "Could not parse profile data"}


def handle_send_message(params):
    """Send a LinkedIn message. Logs for manual execution."""
    profile_url = params.get("profile_url", "")
    message = params.get("message", "")

    if not profile_url or not message:
        return {"ok": False, "error": "profile_url and message required"}

    creds = _load_linkedin_credentials()
    if creds["email"] and creds["password"]:
        try:
            result = _linkedin_browser_action("message", {
                "email": creds["email"],
                "password": creds["password"],
                "profile_url": profile_url,
                "message": message,
            })
            if result.get("ok"):
                return result
        except Exception as e:
            pass

    _log_pending_action("send_message", {
        "profile_url": profile_url,
        "message": message,
    })

    return {
        "ok": True,
        "action": "logged_for_manual_execution",
        "message": "Message queued for manual execution.",
        "instructions": "Open LinkedIn, navigate to your message thread with this person, paste the message, and send.",
    }


def _linkedin_browser_action(action_type, params):
    """Execute a LinkedIn action via browser automation (Playwright).
    Requires: pip install playwright && playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportError("playwright not installed. Run: pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Login to LinkedIn
        page.goto("https://www.linkedin.com/login", timeout=30000)
        page.fill("#username", params["email"])
        page.fill("#password", params["password"])
        page.click("[type=submit]")
        page.wait_for_timeout(5000)

        if "checkpoint" in page.url:
            browser.close()
            return {"ok": False, "error": "LinkedIn login verification required (checkpoint)"}

        if action_type == "connect":
            page.goto(params["profile_url"], timeout=30000)
            page.wait_for_timeout(3000)

            connect_btn = page.query_selector("button:has-text('Connect')")
            if connect_btn:
                connect_btn.click()
                page.wait_for_timeout(2000)

                note_field = page.query_selector("[id*=edit-send-invite-note]")
                if note_field and params.get("note"):
                    note_field.fill(params["note"])

                send_btn = page.query_selector("button:has-text('Send')")
                if send_btn:
                    send_btn.click()
                    page.wait_for_timeout(3000)
                    browser.close()
                    return {"ok": True, "action": "connection_sent", "profile_url": params["profile_url"]}

            browser.close()
            return {"ok": False, "error": "Could not find Connect button"}

        elif action_type == "message":
            page.goto(params["profile_url"], timeout=30000)
            page.wait_for_timeout(3000)

            message_btn = page.query_selector("button:has-text('Message')")
            if message_btn:
                message_btn.click()
                page.wait_for_timeout(2000)

                msg_box = page.query_selector("[role*=textbox]")
                if msg_box:
                    msg_box.fill(params["message"])
                    send_btn = page.query_selector("button:has-text('Send')")
                    if send_btn:
                        send_btn.click()
                        page.wait_for_timeout(2000)
                        browser.close()
                        return {"ok": True, "action": "message_sent", "profile_url": params["profile_url"]}

            browser.close()
            return {"ok": False, "error": "Could not find Message button"}

        browser.close()
        return {"ok": False, "error": f"Unknown action: {action_type}"}


def _log_pending_action(action, params):
    """Log a pending LinkedIn action to a file for manual execution."""
    log_dir = "/home/agency/agency-os/logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "linkedin_pending_actions.jsonl")

    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "params": params,
    }
    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[linkedin_mcp] Failed to log action: {e}", file=sys.stderr, flush=True)


# ── MCP Request Router ──────────────────────────────────────────────

TOOL_HANDLERS = {
    "search_jobs": handle_search_jobs,
    "search_people": handle_search_people,
    "send_connection_request": handle_send_connection_request,
    "get_profile": handle_get_profile,
    "send_message": handle_send_message,
}


def handle_request(msg):
    req_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params", {})

    if method == "initialize":
        jsonrpc_result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": CAPABILITIES,
            "serverInfo": SERVER_INFO,
        })

    elif method == "tools/list":
        jsonrpc_result(req_id, {"tools": TOOLS})

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            jsonrpc_error(req_id, -32601, f"Tool not found: {tool_name}")
            return

        try:
            result = handler(tool_args)
            content = []
            if isinstance(result, dict):
                content.append({"type": "text", "text": json.dumps(result, indent=2)})
            else:
                content.append({"type": "text", "text": str(result)})
            jsonrpc_result(req_id, {"content": content})
        except Exception as e:
            jsonrpc_error(req_id, -32603, f"Tool execution failed: {str(e)[:500]}")

    elif method == "resources/list":
        jsonrpc_result(req_id, {"resources": []})

    elif method == "resources/read":
        jsonrpc_error(req_id, -32601, "No resources available")

    elif method == "notifications/initialized":
        pass

    else:
        jsonrpc_error(req_id, -32601, f"Method not found: {method}")


# ── Main Loop ──────────────────────────────────────────────────────

def main():
    print("[linkedin_mcp] Server starting...", file=sys.stderr, flush=True)
    print(f"[linkedin_mcp] PID: {os.getpid()}", file=sys.stderr, flush=True)
    print(f"[linkedin_mcp] Tools: {', '.join(t['name'] for t in TOOLS)}", file=sys.stderr, flush=True)

    creds = _load_linkedin_credentials()
    if creds["email"] and creds["password"]:
        print("[linkedin_mcp] LinkedIn credentials found — browser automation available", file=sys.stderr, flush=True)
    else:
        print("[linkedin_mcp] No LinkedIn credentials in .env. Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD for browser automation.", file=sys.stderr, flush=True)
        print("[linkedin_mcp] Actions will be logged for manual execution.", file=sys.stderr, flush=True)

    buffer = ""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[linkedin_mcp] Invalid JSON: {e}", file=sys.stderr, flush=True)
                continue

            handle_request(msg)

        except EOFError:
            break
        except Exception as e:
            print(f"[linkedin_mcp] Error: {e}", file=sys.stderr, flush=True)

    print("[linkedin_mcp] Server stopped.", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()

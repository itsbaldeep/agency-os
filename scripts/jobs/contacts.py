"""Contact discovery — finds hiring managers, HR, VP-level people at target companies."""

import json, os, sys, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from worker import call_zen, MODEL_CONFIG


def discover_contacts(company_name, job_title, job_description=None):
    """
    Discover potential contacts (HR, hiring manager, VP) at a target company.
    Uses Zen LLM's training knowledge as a proxy.
    Returns list of potential contacts.

    NOTE: This is a training-knowledge proxy. For production, integrate with
    LinkedIn Sales Navigator, Apollo.io, Prospector, or similar APIs.
    """
    prompt = f"""You are a recruiting intelligence researcher. Based on your training knowledge, identify likely hiring contacts at the following company for the role described.

COMPANY: {company_name}
JOB TITLE: {job_title}
{"JOB DESCRIPTION: " + job_description[:1000] if job_description else ""}

Return ONLY a JSON array of contact objects. Each contact object has:
- name: full name (use [PLACEHOLDER:name] if you're not sure)
- title: likely job title (e.g., "VP of Engineering", "Head of HR", "Hiring Manager")
- email_pattern: the likely email pattern (e.g., "firstname.lastname@company.com" or "firstname@company.com")
- linkedin_url: LinkedIn profile URL or "[PLACEHOLDER: LinkedIn URL]"
- confidence: integer 0-100 estimating confidence this is the right contact
- source: "training_knowledge"

Rules:
- For startups/small companies (<200 employees), the CEO or CTO may hire directly.
- For mid-size (200-5000), find the department head (VP/Director of Engineering/Product/Marketing) and HR manager.
- For large enterprises (5000+), find the VP/Director of the relevant department and a senior recruiter.
- Only include people who could reasonably be the hiring decision maker or influencer.
- Use [PLACEHOLDER:name] for specific names if you're uncertain.
- Minimum 2 contacts, maximum 5.
- Output ONLY the JSON array, no other text.
"""

    result = call_zen(prompt, model=MODEL_CONFIG["cheap"], max_tokens=1500, temperature=0.2)
    if not result["ok"]:
        return {"ok": False, "error": result.get("error", "Unknown error")}

    content = result["content"].strip()
    for trim in [content, content[content.find('['):content.rfind(']') + 1] if '[' in content else '']:
        try:
            data = json.loads(trim)
            if isinstance(data, list):
                return {
                    "ok": True,
                    "contacts": data,
                    "tokens": result.get("prompt_tokens", 0) + result.get("completion_tokens", 0),
                    "cost": result.get("cost", 0),
                }
        except (json.JSONDecodeError, TypeError):
            continue

    return {"ok": False, "error": "Could not parse contacts JSON from LLM response"}


def generate_linkedin_note(resume_text, contact_name, contact_title, company_name, template=None):
    """Generate a personalized LinkedIn connection note."""
    tpl = template or "Hi {name}, I'm a {title} passionate about {company}. I'd love to connect and learn more about opportunities."

    prompt = f"""You are writing a LinkedIn connection request note. Make it personal and effective.

CONTACT NAME: {contact_name}
CONTACT TITLE: {contact_title}
COMPANY: {company_name}

RESUME HIGHLIGHTS:
{resume_text[:1000]}

REQUIREMENTS:
- 150-200 characters max (LinkedIn limit for connection notes).
- Mention a specific reason for connecting (admire their work at X, interested in Y role, etc.).
- Be genuine and professional.
- No "I hope this message finds you well" — be direct.
- Include a very brief relevant credential from the resume.
- End with a soft call to action (eager to learn, appreciate insights, etc.).
- Output RAW JSON only, no prose, no code fences.

Return JSON with:
- note: the connection note text (under 200 chars)
- tone: the tone used (professional / warm / enthusiastic)
"""

    result = call_zen(prompt, model=MODEL_CONFIG["cheap"], max_tokens=500, temperature=0.3)
    if not result["ok"]:
        return {"ok": False, "error": result.get("error", "Unknown error")}

    content = result["content"].strip()
    for trim in [content, content[content.find('{'):content.rfind('}') + 1] if '{' in content else '']:
        try:
            data = json.loads(trim)
            if isinstance(data, dict) and data.get("note"):
                return {
                    "ok": True,
                    "note": data["note"][:300],
                    "tone": data.get("tone", "professional"),
                    "tokens": result.get("prompt_tokens", 0) + result.get("completion_tokens", 0),
                    "cost": result.get("cost", 0),
                }
        except (json.JSONDecodeError, TypeError):
            continue

    return {"ok": False, "error": "Could not parse note JSON from LLM response"}


def generate_outreach_email(resume_text, contact_name, contact_title, company_name, job_title, cover_letter_text=None, template=None):
    """Generate a professional outreach email to a hiring contact."""
    cl_section = f"\nCOVER LETTER:\n{cover_letter_text[:1000]}" if cover_letter_text else ""

    prompt = f"""You are writing a professional outreach email to a hiring contact at a target company.

CONTACT NAME: {contact_name}
CONTACT TITLE: {contact_title}
COMPANY: {company_name}
JOB TITLE: {job_title}
RESUME: {resume_text[:1500]}
{cl_section}

REQUIREMENTS:
- Professional, warm tone.
- Reference the contact's role and why you're reaching out to them specifically.
- Briefly state your interest and relevant qualifications (from resume).
- Include a call to action (phone call, coffee chat, interview availability).
- Keep it to 3-4 short paragraphs.
- No placeholder text — use specifics from the resume.
- Output RAW JSON only, no prose, no code fences.

Return JSON with:
- subject: email subject line (max 80 chars)
- body: full email body text
- call_to_action: what you're asking for (e.g., "15-minute call", "interview")
"""

    result = call_zen(prompt, model=MODEL_CONFIG["quality"], max_tokens=1500, temperature=0.3)
    if not result["ok"]:
        return {"ok": False, "error": result.get("error", "Unknown error")}

    content = result["content"].strip()
    for trim in [content, content[content.find('{'):content.rfind('}') + 1] if '{' in content else '']:
        try:
            data = json.loads(trim)
            if isinstance(data, dict) and data.get("subject") and data.get("body"):
                return {
                    "ok": True,
                    "subject": data["subject"],
                    "body": data["body"],
                    "call_to_action": data.get("call_to_action", ""),
                    "tokens": result.get("prompt_tokens", 0) + result.get("completion_tokens", 0),
                    "cost": result.get("cost", 0),
                }
        except (json.JSONDecodeError, TypeError):
            continue

    return {"ok": False, "error": "Could not parse email JSON from LLM response"}

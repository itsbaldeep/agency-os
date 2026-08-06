"""Cover letter generation — uses Zen LLM to draft personalized cover letters."""

import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from worker import call_zen, MODEL_CONFIG


def generate_cover_letter(resume_text, job_title, job_company, job_description, recipient_name=None, recipient_title=None):
    """
    Generate a personalized cover letter for a job application.
    Returns dict with content and metadata.
    """
    recipient_info = ""
    if recipient_name:
        recipient_info = f"\nRECIPIENT: {recipient_name}"
    if recipient_title:
        recipient_info += f"\nRECIPIENT TITLE: {recipient_title}"

    prompt = f"""You are a professional cover letter writer. Write a compelling, personalized cover letter.

JOB TITLE: {job_title}
JOB COMPANY: {job_company}
JOB DESCRIPTION: {job_description[:2000]}{recipient_info}

APPLICANT RESUME:
{resume_text[:2000]}

INSTRUCTIONS:
1. Write 3-4 paragraphs (250-400 words total).
2. First paragraph: Hook — specific reason you're excited about THIS company/role.
3. Second paragraph: Connect your relevant experience to their needs (use details from resume).
4. Third paragraph: Soft skills, culture fit, what you'd bring.
5. Closing: Call to action (request an interview).
6. Use [PLACEHOLDER:description] for any specific number/claim not in the resume.
7. Be specific — reference the company and role. No generic form letters.
8. Tone: professional, confident, not arrogant. Enthusiastic but measured.
9. Output RAW JSON only, no prose, no code fences.

Return JSON with:
- content: the full cover letter text (include salutation and closing)
- subject: a suggested email subject line for sending this cover letter
- key_points: array of 3-4 key selling points highlighted
"""

    result = call_zen(prompt, model=MODEL_CONFIG["quality"], max_tokens=2000, temperature=0.3)
    if not result["ok"]:
        return {"ok": False, "error": result.get("error", "Unknown error")}

    content = result["content"].strip()
    for trim in [content, content[content.find('{'):content.rfind('}') + 1] if '{' in content else '']:
        try:
            data = json.loads(trim)
            if isinstance(data, dict) and data.get("content"):
                return {
                    "ok": True,
                    "content": data["content"],
                    "subject": data.get("subject", f"Application for {job_title} position"),
                    "key_points": data.get("key_points", []),
                    "tokens": result.get("prompt_tokens", 0) + result.get("completion_tokens", 0),
                    "cost": result.get("cost", 0),
                }
        except (json.JSONDecodeError, TypeError):
            continue

    return {"ok": False, "error": "Could not parse cover letter JSON from LLM response"}

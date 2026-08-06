"""Resume tailoring — uses Zen LLM to tailor a resume for a specific job."""

import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from worker import call_zen, MODEL_CONFIG


def tailor_resume(original_resume, job_title, job_company, job_description, job_requirements):
    """
    Tailor the resume for a specific job posting.
    Returns dict with tailored_resume, changes_summary, ats_keywords.
    """
    prompt = f"""You are an expert resume writer and ATS optimization specialist. Tailor this resume for a specific job.

JOB TITLE: {job_title}
JOB COMPANY: {job_company}
JOB DESCRIPTION: {job_description[:2000]}
JOB REQUIREMENTS: {job_requirements[:1000] if job_requirements else 'N/A'}

ORIGINAL RESUME:
{original_resume[:3000]}

INSTRUCTIONS:
1. Reorder bullet points to emphasize experience most relevant to THIS job.
2. Use keywords from the job description naturally in experience bullet points.
3. Quantify achievements where possible (retain any original numbers; add [PLACEHOLDER:X] for new ones).
4. Keep the same overall structure (contact, summary, experience, education, certifications).
5. DO NOT fabricate experience, skills, or credentials.
6. Use [PLACEHOLDER:description] for any new numbers or claims not in the original resume.
7. Output RAW JSON only, no prose, no code fences.

Return JSON with:
- tailored_resume: the full tailored resume text
- changes_summary: a 2-3 sentence summary of what was changed and why
- ats_keywords: array of key ATS keywords from the job description that were incorporated
"""

    result = call_zen(prompt, model=MODEL_CONFIG["quality"], max_tokens=3000, temperature=0.2)
    if not result["ok"]:
        return {"ok": False, "error": result.get("error", "Unknown error")}

    content = result["content"].strip()
    for trim in [content, content[content.find('{'):content.rfind('}') + 1] if '{' in content else '']:
        try:
            data = json.loads(trim)
            if isinstance(data, dict) and data.get("tailored_resume"):
                return {
                    "ok": True,
                    "tailored_resume": data["tailored_resume"],
                    "changes_summary": data.get("changes_summary", ""),
                    "ats_keywords": data.get("ats_keywords", []),
                    "tokens": result.get("prompt_tokens", 0) + result.get("completion_tokens", 0),
                    "cost": result.get("cost", 0),
                }
        except (json.JSONDecodeError, TypeError):
            continue

    return {"ok": False, "error": "Could not parse tailored resume JSON from LLM response"}


def generate_resume_tailoring_report(original, tailored, changes_summary, ats_keywords):
    """Generate a human-readable summary of resume changes."""
    return f"""## Resume Tailoring Report

### Changes Made
{changes_summary}

### ATS Keywords Incorporated
{', '.join(ats_keywords) if ats_keywords else 'None specifically tracked'}

### Original Resume Length: {len(original)} chars
### Tailored Resume Length: {len(tailored)} chars
"""

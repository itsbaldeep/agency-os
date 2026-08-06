"""
Job campaign orchestration — runs a complete job search cycle for a campaign.
This is the main entry point called by the worker task `run_job_campaign`.

Flow for each job in the campaign:
  1. Discover/find job listings matching criteria
  2. Tailor resume
  3. Generate cover letter
  4. Discover contacts at the company
  5. Generate LinkedIn connection note
  6. Generate outreach email
  7. Send email via Gmail API
  8. (LinkedIn connection via MCP server — manual or scheduled)
  9. Schedule follow-up
"""

import json, os, sys, time
from datetime import datetime, timedelta

import psycopg2.extras

def _call_with_timeout(func, args=(), kwargs=None, timeout=30):
    """Call a function with a timeout. Returns result or None on timeout."""
    import threading
    kwargs = kwargs or {}
    result = []
    exception = []

    def runner():
        try:
            r = func(*args, **kwargs)
            result.append(r)
        except Exception as e:
            exception.append(e)

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None  # Timeout
    if exception:
        raise exception[0]
    return result[0] if result else None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from worker import get_conn, ch_trace, call_zen, MODEL_CONFIG

from . import resume as resume_mod
from . import cover_letter as cl_mod
from . import contacts as contacts_mod
from .gmail_client import send_email as gmail_send


def run_campaign(campaign_id, db_conn=None):
    """Execute one full run of a job campaign (X jobs per Y hours)."""
    own_conn = False
    if db_conn is None:
        db_conn = get_conn()
        own_conn = True

    try:
        cur = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT * FROM job_campaigns WHERE id=%s", (campaign_id,))
        campaign = cur.fetchone()
        if not campaign:
            return {"ok": False, "error": f"Campaign {campaign_id} not found"}

        name = campaign["name"]
        target = campaign["target_jobs_per_run"] or 10
        resume_text = campaign.get("resume_text", "")
        job_titles = campaign.get("job_titles") or []
        locations = campaign.get("locations") or []
        company_include = campaign.get("company_include") or []
        company_exclude = campaign.get("company_exclude") or []
        keywords_include = campaign.get("keywords_include") or []
        keywords_exclude = campaign.get("keywords_exclude") or []

        if not resume_text:
            return {"ok": False, "error": "No resume_text set for campaign"}
        if not job_titles:
            return {"ok": False, "error": "No job_titles set for campaign"}

        # Create run history record
        cur.execute(
            "INSERT INTO job_run_history (campaign_id, status, jobs_targeted) VALUES (%s, 'running', %s) RETURNING id",
            (campaign_id, target),
        )
        run_id = cur.fetchone()["id"]
        db_conn.commit()

        # Step 1: Find job listings
        listings = _find_job_listings(cur, campaign, job_titles, locations, company_include, company_exclude, keywords_include, keywords_exclude, target)
        if not listings:
            cur.execute("UPDATE job_run_history SET status='completed', completed_at=now(), jobs_processed=0 WHERE id=%s", (run_id,))
            db_conn.commit()
            return {"ok": True, "note": "No new listings found", "run_id": run_id, "processed": 0}

        processed = 0
        errors = []

        for listing_id in listings:
            try:
                result = _process_listing(db_conn, cur, campaign, listing_id, resume_text)
                if result.get("ok"):
                    processed += 1
                else:
                    errors.append(f"Listing {listing_id}: {result.get('error','?')}")
            except Exception as e:
                db_conn.rollback()
                errors.append(f"Listing {listing_id}: {str(e)[:200]}")

            try:
                cur.execute(
                    "UPDATE job_run_history SET jobs_processed=%s WHERE id=%s",
                    (processed, run_id),
                )
                db_conn.commit()
            except Exception:
                db_conn.rollback()

        cur.execute(
            "UPDATE job_run_history SET status='completed', jobs_processed=%s, errors=%s, completed_at=now() WHERE id=%s",
            (processed, json.dumps(errors) if errors else None, run_id),
        )
        db_conn.commit()

        ch_trace({
            "project": f"campaign-{campaign_id}",
            "actor": "worker",
            "action": "campaign_run_completed",
            "detail": f"Campaign '{name}': {processed}/{target} jobs processed. Errors: {len(errors)}",
            "gate": "green", "decision": "proceed", "ok": 1 if not errors else 0,
        })

        return {"ok": True, "run_id": run_id, "processed": processed, "targeted": target, "errors": errors}

    except Exception as e:
        import traceback
        return {"ok": False, "error": f"Campaign failed: {str(e)[:400]} -- {traceback.format_exc()[:200]}"}
    finally:
        if own_conn and db_conn:
            db_conn.close()


def _find_job_listings(cur, campaign, job_titles, locations, company_include, company_exclude, keywords_include, keywords_exclude, target):
    """
    Find job listings matching campaign criteria.
    For the initial version, this creates placeholder listings that the user
    can fill in, or uses the Zen LLM to suggest well-known companies.
    In production, integrate with job board APIs (LinkedIn, Indeed, etc).
    """
    title_patterns = " | ".join(job_titles)
    loc_str = " | ".join(locations) if locations else "remote/any"

    prompt = f"""Given a job search campaign, suggest {target} realistic current job openings at well-known companies that match these criteria.

JOB TITLES: {title_patterns}
LOCATIONS: {loc_str}
{"PREFERRED COMPANIES: " + ", ".join(company_include) if company_include else ""}
{"EXCLUDED COMPANIES: " + ", ".join(company_exclude) if company_exclude else ""}
{"REQUIRED KEYWORDS: " + ", ".join(keywords_include) if keywords_include else ""}

Return ONLY a JSON array of objects. Each object:
- title: exact job title
- company: company name
- location: job location
- description: 2-3 sentence description of the role
- url: company careers page URL or "[PLACEHOLDER: URL]"
- salary_range: estimated range or "N/A"

Rules:
- Suggest real, active companies (no made-up startups).
- Suggest a variety of companies (not all the same industry).
- If specific companies are preferred, prioritize those.
- Include companies that are known to hire for these roles.
- Output ONLY the JSON array, no other text.
"""

    result = call_zen(prompt, model=MODEL_CONFIG["cheap"], max_tokens=2000, temperature=0.4)
    if not result["ok"]:
        print(f"[campaign] Zen listing generation failed: {result.get('error','')}", flush=True)
        return []

    content = result["content"].strip()
    suggested = []
    for trim in [content, content[content.find('['):content.rfind(']') + 1] if '[' in content else '']:
        try:
            data = json.loads(trim)
            if isinstance(data, list):
                suggested = data
                break
        except (json.JSONDecodeError, TypeError):
            continue

    if not suggested:
        print("[campaign] Could not parse listings from Zen", flush=True)
        return []

    listing_ids = []
    for s in suggested[:target]:
        cur.execute(
            """INSERT INTO job_listings (campaign_id, title, company, location, description, url, salary_range, source, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'ai_suggested', 'discovered') RETURNING id""",
            (campaign["id"], s.get("title", "Unknown"), s.get("company", "Unknown"),
             s.get("location", "Remote"), s.get("description", ""),
             s.get("url", ""), s.get("salary_range", "N/A")),
        )
        listing_ids.append(cur.fetchone()["id"])

    return listing_ids


def _process_listing(db_conn, cur, campaign, listing_id, resume_text):
    """Process a single job listing through the entire pipeline."""
    cur.execute("SELECT * FROM job_listings WHERE id=%s", (listing_id,))
    listing = cur.fetchone()
    if not listing:
        return {"ok": False, "error": "Listing not found"}

    job_title = listing["title"]
    job_company = listing["company"]
    job_desc = listing.get("description") or ""
    campaign_id = campaign["id"]

    print(f"[campaign] Processing {job_title} @ {job_company}...", flush=True)

    print(f"[campaign] Step 2: Tailoring resume for {job_title} @ {job_company}...", flush=True)
    resume_result = resume_mod.tailor_resume(resume_text, job_title, job_company, job_desc, listing.get("requirements"))
    if not resume_result.get("ok"):
        return {"ok": False, "error": f"Resume tailoring failed: {resume_result.get('error', '')}"}

    cur.execute(
        "INSERT INTO resume_versions (listing_id, campaign_id, original_resume, tailored_resume, changes, ats_keywords, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'draft') RETURNING id",
        (listing_id, campaign_id, resume_text, resume_result["tailored_resume"],
         resume_result.get("changes_summary", ""), resume_result.get("ats_keywords", [])),
    )
    resume_id = cur.fetchone()["id"]
    db_conn.commit()
    print(f"[campaign] Resume tailored, ID={resume_id}", flush=True)

    print(f"[campaign] Step 3: Generating cover letter...", flush=True)
    cl_result = cl_mod.generate_cover_letter(resume_text, job_title, job_company, job_desc)
    if not cl_result.get("ok"):
        print(f"[campaign] Cover letter failed for {job_title}: {cl_result.get('error','')}", flush=True)
        cl_text = "[Cover letter generation failed]"
        cl_subject = f"Application for {job_title} position"
    else:
        cl_text = cl_result["content"]
        cl_subject = cl_result.get("subject", f"Application for {job_title}")

    cur.execute(
        "INSERT INTO cover_letters (listing_id, campaign_id, content, company, status) "
        "VALUES (%s, %s, %s, %s, 'draft') RETURNING id",
        (listing_id, campaign_id, cl_text, job_company),
    )
    cl_id = cur.fetchone()["id"]
    db_conn.commit()
    print(f"[campaign] Cover letter generated, ID={cl_id}", flush=True)

    print(f"[campaign] Step 4: Discovering contacts at {job_company}...", flush=True)
    contacts_result = contacts_mod.discover_contacts(job_company, job_title, job_desc)
    primary_contact = None
    if contacts_result.get("ok") and contacts_result.get("contacts"):
        for c in contacts_result["contacts"][:3]:
            cur.execute(
                "INSERT INTO job_contacts (listing_id, name, title, company, email, linkedin_url, confidence, source, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'ai', 'pending') RETURNING id",
                (listing_id, c.get("name", "Unknown"), c.get("title", ""), job_company,
                 c.get("email_pattern", ""), c.get("linkedin_url", ""), c.get("confidence", 50)),
            )
            cid = cur.fetchone()["id"]
            if primary_contact is None:
                primary_contact = cid
        db_conn.commit()

    print(f"[campaign] Step 5: Generating LinkedIn note...", flush=True)
    if primary_contact:
        cur.execute("SELECT * FROM job_contacts WHERE id=%s", (primary_contact,))
        contact = cur.fetchone()
        if contact:
            note_result = contacts_mod.generate_linkedin_note(resume_text, contact["name"], contact["title"], job_company)
            if note_result.get("ok"):
                cur.execute(
                    "INSERT INTO linkedin_notes (contact_id, listing_id, campaign_id, content, status) "
                    "VALUES (%s, %s, %s, %s, 'draft')",
                    (primary_contact, listing_id, campaign_id, note_result["note"]),
                )

    print(f"[campaign] Step 6: Generating outreach email...", flush=True)
    if primary_contact:
        cur.execute("SELECT * FROM job_contacts WHERE id=%s", (primary_contact,))
        contact = cur.fetchone()
        if contact:
            email_result = contacts_mod.generate_outreach_email(resume_text, contact["name"], contact["title"], job_company, job_title, cl_text)
            if email_result.get("ok"):
                cur.execute(
                    "INSERT INTO email_threads (contact_id, listing_id, campaign_id, subject, body, direction, status) "
                    "VALUES (%s, %s, %s, %s, %s, 'outbound', 'draft') RETURNING id",
                    (primary_contact, listing_id, campaign_id, email_result["subject"], email_result["body"]),
                )
                email_thread_id = cur.fetchone()["id"]
                db_conn.commit()

                # Step 7: Send email via Gmail API
                email_pattern = contact.get("email", "")
                if email_pattern and "@" in email_pattern:
                    try:
                        send_result = _call_with_timeout(
                            gmail_send,
                            args=(campaign_id, email_pattern, email_result["subject"], email_result["body"]),
                            timeout=15,
                        )
                        if send_result is None:
                            print(f"[campaign] Email send timed out for {email_pattern}", flush=True)
                        else:
                            send_ok, send_msg = send_result
                            if send_ok:
                                cur.execute(
                                    "UPDATE email_threads SET status='sent', gmail_message_id=%s, sent_at=now() WHERE id=%s",
                                    (send_msg, email_thread_id),
                                )
                                cur.execute(
                                    "UPDATE job_applications SET status='email_sent', email_sent_at=now() WHERE listing_id=%s AND campaign_id=%s",
                                    (listing_id, campaign_id),
                                )
                            else:
                                print(f"[campaign] Email send failed for {email_pattern}: {send_msg}", flush=True)
                    except Exception as e:
                        print(f"[campaign] Email send error for {email_pattern}: {e}", flush=True)
                db_conn.commit()
            else:
                print(f"[campaign] Email generation failed: {email_result.get('error','')}", flush=True)

    # Create/update application record
    cur.execute(
        """INSERT INTO job_applications (listing_id, campaign_id, resume_id, cover_letter_id, contact_id, status)
           VALUES (%s, %s, %s, %s, %s, 'preparing')
           ON CONFLICT (listing_id, campaign_id) DO UPDATE SET
             resume_id=EXCLUDED.resume_id, cover_letter_id=EXCLUDED.cover_letter_id,
             contact_id=EXCLUDED.contact_id, updated_at=now()""",
        (listing_id, campaign_id, resume_id, cl_id, primary_contact),
    )
    db_conn.commit()

    return {"ok": True, "listing_id": listing_id, "resume_id": resume_id, "cover_letter_id": cl_id}

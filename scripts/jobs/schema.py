"""Database schema for job search automation. Run once via `python3 -m jobs.schema`."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS job_campaigns (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'draft',
    target_jobs_per_run INTEGER DEFAULT 10,
    run_interval_hours INTEGER DEFAULT 24,
    resume_text TEXT,
    job_titles TEXT[] DEFAULT '{}',
    locations TEXT[] DEFAULT '{}',
    company_include TEXT[] DEFAULT '{}',
    company_exclude TEXT[] DEFAULT '{}',
    keywords_include TEXT[] DEFAULT '{}',
    keywords_exclude TEXT[] DEFAULT '{}',
    min_salary INTEGER,
    max_applications_per_company INTEGER DEFAULT 1,
    linkedin_note_template TEXT,
    cover_letter_template TEXT,
    email_template TEXT,
    follow_up_days INTEGER DEFAULT 5,
    max_follow_ups INTEGER DEFAULT 2,
    gmail_oauth_state TEXT,
    gmail_token TEXT,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_listings (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER REFERENCES job_campaigns(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    description TEXT,
    url TEXT,
    salary_range TEXT,
    source TEXT DEFAULT 'manual',
    posted_date DATE,
    requirements TEXT,
    score INTEGER DEFAULT 0,
    status TEXT DEFAULT 'discovered',
    notes TEXT,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_contacts (
    id SERIAL PRIMARY KEY,
    listing_id INTEGER REFERENCES job_listings(id) ON DELETE CASCADE,
    name TEXT,
    title TEXT,
    company TEXT,
    email TEXT,
    linkedin_url TEXT,
    phone TEXT,
    source TEXT DEFAULT 'manual',
    confidence INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    notes TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS resume_versions (
    id SERIAL PRIMARY KEY,
    listing_id INTEGER REFERENCES job_listings(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES job_campaigns(id) ON DELETE CASCADE,
    original_resume TEXT,
    tailored_resume TEXT,
    changes TEXT,
    ats_keywords TEXT[] DEFAULT '{}',
    status TEXT DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cover_letters (
    id SERIAL PRIMARY KEY,
    listing_id INTEGER REFERENCES job_listings(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES job_campaigns(id) ON DELETE CASCADE,
    content TEXT,
    recipient_name TEXT,
    recipient_title TEXT,
    company TEXT,
    status TEXT DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS linkedin_notes (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER REFERENCES job_contacts(id) ON DELETE CASCADE,
    listing_id INTEGER REFERENCES job_listings(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES job_campaigns(id) ON DELETE CASCADE,
    content TEXT,
    status TEXT DEFAULT 'draft',
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_threads (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER REFERENCES job_contacts(id) ON DELETE CASCADE,
    listing_id INTEGER REFERENCES job_listings(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES job_campaigns(id) ON DELETE CASCADE,
    subject TEXT,
    body TEXT,
    gmail_message_id TEXT,
    direction TEXT DEFAULT 'outbound',
    status TEXT DEFAULT 'draft',
    sent_at TIMESTAMP,
    opened_at TIMESTAMP,
    replied_at TIMESTAMP,
    follow_up_number INTEGER DEFAULT 0,
    is_follow_up BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_applications (
    id SERIAL PRIMARY KEY,
    listing_id INTEGER REFERENCES job_listings(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES job_campaigns(id) ON DELETE CASCADE,
    resume_id INTEGER REFERENCES resume_versions(id),
    cover_letter_id INTEGER REFERENCES cover_letters(id),
    contact_id INTEGER REFERENCES job_contacts(id),
    status TEXT DEFAULT 'preparing',
    UNIQUE(listing_id, campaign_id),
    applied_at TIMESTAMP,
    linkedin_sent_at TIMESTAMP,
    email_sent_at TIMESTAMP,
    interview_date TIMESTAMP,
    offer_details TEXT,
    rejection_reason TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_run_history (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER REFERENCES job_campaigns(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'running',
    jobs_targeted INTEGER DEFAULT 0,
    jobs_processed INTEGER DEFAULT 0,
    applications_created INTEGER DEFAULT 0,
    emails_sent INTEGER DEFAULT 0,
    linkedin_notes_sent INTEGER DEFAULT 0,
    errors TEXT,
    started_at TIMESTAMP DEFAULT now(),
    completed_at TIMESTAMP
);
"""

INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_job_listings_campaign ON job_listings(campaign_id);
CREATE INDEX IF NOT EXISTS idx_job_listings_status ON job_listings(status);
CREATE INDEX IF NOT EXISTS idx_job_contacts_listing ON job_contacts(listing_id);
CREATE INDEX IF NOT EXISTS idx_job_applications_campaign ON job_applications(campaign_id);
CREATE INDEX IF NOT EXISTS idx_job_applications_listing ON job_applications(listing_id);
CREATE INDEX IF NOT EXISTS idx_email_threads_campaign ON email_threads(campaign_id);
CREATE INDEX IF NOT EXISTS idx_resume_versions_listing ON resume_versions(listing_id);
"""


def run(conn):
    cur = conn.cursor()
    cur.execute(SCHEMA_SQL)
    cur.execute(INDEXES_SQL)
    conn.commit()
    print("[jobs/schema] Tables created/verified.")


if __name__ == "__main__":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from worker import get_conn
    conn = get_conn()
    try:
        run(conn)
    finally:
        conn.close()

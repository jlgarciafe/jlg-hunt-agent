import uuid
from datetime import date
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
import logging

logger = logging.getLogger(__name__)

def get_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def get_existing_job_ids() -> set:
    """Return all job IDs already in the database (for deduplication)."""
    try:
        client = get_client()
        result = client.table("jobs").select("id").execute()
        return {row["id"] for row in result.data}
    except Exception as e:
        logger.error(f"Failed to fetch existing job IDs: {e}")
        return set()

def get_seen_urls() -> set:
    """Return all URLs already tracked (secondary dedup by URL)."""
    try:
        client = get_client()
        result = client.table("jobs").select("url").execute()
        return {row["url"] for row in result.data if row.get("url")}
    except Exception as e:
        logger.error(f"Failed to fetch seen URLs: {e}")
        return set()

def save_job(job: dict) -> bool:
    """Insert a new job into Supabase. Returns True on success."""
    try:
        client = get_client()
        record = {
            "id":                 job.get("id", str(uuid.uuid4())),
            "title":              job.get("title", ""),
            "company":            job.get("company", ""),
            "sector":             job.get("sector", "Technology"),
            "geography":          job.get("geography", ""),
            "score":              job.get("score", 0),
            "stage":              "recommended",
            "date_found":         str(date.today()),
            "source":             job.get("source", ""),
            "cv_version":         job.get("cvVersion", "Corporate / Listed Co."),
            "url":                job.get("url", ""),
            "description":        job.get("description", "")[:5000],
            "outreach_draft":     job.get("outreachDraft", ""),
            "scoring_breakdown":  job.get("scoringBreakdown", {}),
            "scoring_rationale":  job.get("scoringRationale", ""),
            "notes":              "",
        }
        client.table("jobs").insert(record).execute()
        logger.info(f"Saved: {job['title']} at {job['company']} (score {job['score']})")
        return True
    except Exception as e:
        logger.error(f"Failed to save job {job.get('title')}: {e}")
        return False

def get_all_jobs() -> list:
    """Fetch all jobs ordered by score descending."""
    try:
        client = get_client()
        result = client.table("jobs").select("*").order("score", desc=True).execute()
        return result.data
    except Exception as e:
        logger.error(f"Failed to fetch jobs: {e}")
        return []

def update_job_stage(job_id: str, stage: str) -> bool:
    """Update the pipeline stage of a job."""
    try:
        client = get_client()
        client.table("jobs").update({"stage": stage}).eq("id", job_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to update stage for {job_id}: {e}")
        return False

def update_job_notes(job_id: str, notes: str) -> bool:
    """Update notes for a job."""
    try:
        client = get_client()
        client.table("jobs").update({"notes": notes}).eq("id", job_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to update notes for {job_id}: {e}")
        return False


# ── Supabase schema (run once in Supabase SQL editor) ────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    company             TEXT NOT NULL,
    sector              TEXT,
    geography           TEXT,
    score               INTEGER DEFAULT 0,
    stage               TEXT DEFAULT 'recommended',
    date_found          DATE,
    source              TEXT,
    cv_version          TEXT,
    url                 TEXT,
    description         TEXT,
    outreach_draft      TEXT,
    scoring_breakdown   JSONB,
    scoring_rationale   TEXT,
    notes               TEXT DEFAULT '',
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_stage ON jobs(stage);
CREATE INDEX IF NOT EXISTS idx_jobs_date  ON jobs(date_found DESC);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER IF NOT EXISTS jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Enable Row Level Security (allow anon reads for dashboard)
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;

CREATE POLICY IF NOT EXISTS "Allow anon read"
    ON jobs FOR SELECT TO anon USING (true);

CREATE POLICY IF NOT EXISTS "Allow service role all"
    ON jobs FOR ALL TO service_role USING (true);
"""

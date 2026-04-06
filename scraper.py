import requests
import hashlib
import logging
import time
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from config import (
    ADZUNA_APP_ID, ADZUNA_APP_KEY, ADZUNA_COUNTRIES,
    SEARCH_QUERIES, MAX_JOB_AGE_DAYS, RESULTS_PER_SOURCE,
    TARGET_SECTORS
)

logger = logging.getLogger(__name__)
ua = UserAgent()

HEADERS = {
    "User-Agent": ua.random,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_job_id(title: str, company: str, url: str = "") -> str:
    """Deterministic ID so the same job isn't duplicated across runs."""
    raw = f"{title.lower().strip()}-{company.lower().strip()}-{url}"
    return hashlib.md5(raw.encode()).hexdigest()

def infer_sector(title: str, description: str) -> str:
    text = (title + " " + description).lower()
    if any(k in text for k in ["telecom", "telecommunications", "5g", "wireless", "network operator"]):
        return "Telecom"
    if any(k in text for k in ["data center", "data centre", "colocation", "colo"]):
        return "Data Center"
    if any(k in text for k in ["artificial intelligence", " ai ", "machine learning", "llm"]):
        return "AI / Machine Learning"
    if any(k in text for k in ["energy", "utilities", "power grid", "renewable", "oil and gas"]):
        return "Energy"
    if any(k in text for k in ["critical infrastructure", "scada", "industrial control"]):
        return "Critical Infrastructure"
    if any(k in text for k in ["software", "saas", "cloud", "technology", "digital"]):
        return "Technology"
    return "Technology"

def is_executive_title(title: str) -> bool:
    title_lower = title.lower()
    executive_keywords = [
        "chief executive", "ceo", "chief operating", "coo",
        "executive vice president", "evp",
        "senior vice president", "svp",
        "president", "managing director", "general manager",
        "chief transformation", "chief digital", "chief technology",
        "chief information",
    ]
    return any(kw in title_lower for kw in executive_keywords)

def is_relevant_sector(title: str, description: str) -> bool:
    text = (title + " " + description).lower()
    return any(sector in text for sector in TARGET_SECTORS)


# ── Adzuna API ────────────────────────────────────────────────────────────────

def fetch_adzuna(query: str, country: str) -> list:
    """Fetch jobs from Adzuna API for a given query and country."""
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        logger.warning("Adzuna credentials not set — skipping Adzuna")
        return []

    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    params = {
        "app_id":           ADZUNA_APP_ID,
        "app_key":          ADZUNA_APP_KEY,
        "results_per_page": RESULTS_PER_SOURCE,
        "what":             query,
        "max_days_old":     MAX_JOB_AGE_DAYS,
        "content-type":     "application/json",
        "sort_by":          "date",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        jobs = []

        for item in data.get("results", []):
            title       = item.get("title", "")
            company     = item.get("company", {}).get("display_name", "Unknown")
            description = item.get("description", "")
            location    = item.get("location", {}).get("display_name", "")
            job_url     = item.get("redirect_url", "")

            if not is_executive_title(title):
                continue
            if not is_relevant_sector(title, description):
                continue

            jobs.append({
                "id":          make_job_id(title, company, job_url),
                "title":       title,
                "company":     company,
                "geography":   location,
                "description": description,
                "url":         job_url,
                "source":      f"Adzuna ({country.upper()})",
                "sector":      infer_sector(title, description),
            })

        logger.info(f"Adzuna [{country}] '{query}': {len(jobs)} executive matches")
        return jobs

    except Exception as e:
        logger.error(f"Adzuna error [{country}] '{query}': {e}")
        return []


# ── Google Jobs (structured data scraping) ────────────────────────────────────

def fetch_google_jobs(query: str) -> list:
    """
    Scrape Google Jobs search results for executive roles.
    Google embeds job postings as JSON-LD structured data.
    """
    search_url = f"https://www.google.com/search?q={requests.utils.quote(query + ' executive job site:linkedin.com OR site:indeed.com')}&ibp=htl;jobs"

    try:
        headers = {**HEADERS, "User-Agent": ua.random}
        resp = requests.get(search_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        jobs = []

        # Parse job postings from structured data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "JobPosting":
                            jobs.append(_parse_jsonld_job(item))
                elif data.get("@type") == "JobPosting":
                    jobs.append(_parse_jsonld_job(data))
            except Exception:
                continue

        return [j for j in jobs if j and is_executive_title(j.get("title", ""))]

    except Exception as e:
        logger.error(f"Google Jobs error for '{query}': {e}")
        return []

def _parse_jsonld_job(item: dict) -> dict:
    title     = item.get("title", "")
    company   = item.get("hiringOrganization", {}).get("name", "")
    location  = item.get("jobLocation", {})
    if isinstance(location, list):
        location = location[0] if location else {}
    address   = location.get("address", {})
    geography = f"{address.get('addressLocality', '')} {address.get('addressCountry', '')}".strip()
    desc      = BeautifulSoup(item.get("description", ""), "lxml").get_text()[:2000]
    url       = item.get("url", "") or item.get("sameAs", "")

    return {
        "id":          make_job_id(title, company, url),
        "title":       title,
        "company":     company,
        "geography":   geography or "Global",
        "description": desc,
        "url":         url,
        "source":      "Google Jobs",
        "sector":      infer_sector(title, desc),
    }


# ── Executive job boards ──────────────────────────────────────────────────────

def fetch_the_muse() -> list:
    """
    The Muse has a free public API — good for senior tech/global roles.
    https://www.themuse.com/api/public/jobs
    """
    jobs = []
    try:
        url    = "https://www.themuse.com/api/public/jobs"
        params = {"category": "Executive", "page": 0, "descending": True}
        resp   = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data   = resp.json()

        for item in data.get("results", []):
            title   = item.get("name", "")
            company = item.get("company", {}).get("name", "")
            desc    = BeautifulSoup(item.get("contents", ""), "lxml").get_text()[:2000]
            locations = item.get("locations", [])
            geo     = ", ".join(l.get("name", "") for l in locations) or "Global"
            job_url = item.get("refs", {}).get("landing_page", "")

            if not is_executive_title(title):
                continue

            jobs.append({
                "id":          make_job_id(title, company, job_url),
                "title":       title,
                "company":     company,
                "geography":   geo,
                "description": desc,
                "url":         job_url,
                "source":      "The Muse",
                "sector":      infer_sector(title, desc),
            })

        logger.info(f"The Muse: {len(jobs)} executive matches")
    except Exception as e:
        logger.error(f"The Muse error: {e}")

    return jobs


def fetch_remotive() -> list:
    """
    Remotive free API — good for remote executive roles.
    """
    jobs = []
    try:
        url  = "https://remotive.com/api/remote-jobs"
        params = {"category": "management-finance", "limit": 100}
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("jobs", []):
            title   = item.get("title", "")
            company = item.get("company_name", "")
            desc    = BeautifulSoup(item.get("description", ""), "lxml").get_text()[:2000]
            job_url = item.get("url", "")

            if not is_executive_title(title):
                continue
            if not is_relevant_sector(title, desc):
                continue

            jobs.append({
                "id":          make_job_id(title, company, job_url),
                "title":       title,
                "company":     company,
                "geography":   "Remote / Global",
                "description": desc,
                "url":         job_url,
                "source":      "Remotive",
                "sector":      infer_sector(title, desc),
            })

        logger.info(f"Remotive: {len(jobs)} executive matches")
    except Exception as e:
        logger.error(f"Remotive error: {e}")

    return jobs


# ── Master fetch function ─────────────────────────────────────────────────────

def fetch_all_jobs() -> list:
    """
    Run all scrapers and return deduplicated list of raw job dicts.
    Deduplication at this stage is by job ID only — Supabase check happens in agent.py.
    """
    all_jobs = []
    seen_ids = set()

    def add_jobs(new_jobs: list):
        for job in new_jobs:
            jid = job.get("id")
            if jid and jid not in seen_ids:
                seen_ids.add(jid)
                all_jobs.append(job)

    logger.info("Starting Adzuna searches...")
    for query in SEARCH_QUERIES[:8]:           # limit to 8 queries to stay in free tier
        for country in ADZUNA_COUNTRIES[:4]:   # top 4 countries
            add_jobs(fetch_adzuna(query, country))
            time.sleep(0.5)                    # polite rate limit

    logger.info("Fetching from The Muse...")
    add_jobs(fetch_the_muse())

    logger.info("Fetching from Remotive...")
    add_jobs(fetch_remotive())

    logger.info(f"Total raw jobs fetched (pre-scoring dedup): {len(all_jobs)}")
    return all_jobs

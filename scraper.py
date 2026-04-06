"""
JLG Executive Job Hunt — Scraper v3
Sources:
  1. Adzuna API      — no salary filter, title-filtered only
  2. JSearch         — LinkedIn + Indeed + Glassdoor aggregator
  3. Himalayas API   — replaces LinkedIn scrape (free, no key, reliable)
  4. Reed.co.uk      — free API, reliable UK + international
  5. Remotive        — free API, global remote exec roles
  6. The Muse        — free API, exec category
  7. Jobicy          — free API, global exec roles
  8. Exec search RSS — Korn Ferry, Spencer Stuart public feeds
"""
import hashlib
import logging
import os
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin

from config import (
    ADZUNA_APP_ID, ADZUNA_APP_KEY, ADZUNA_COUNTRIES, ADZUNA_QUERIES,
    MAX_JOB_AGE_DAYS, RAPIDAPI_KEY, JSEARCH_QUERIES,
    REED_QUERIES, REMOTIVE_CATEGORIES, TARGET_SECTORS, EXEC_TITLES,
    TITLE_BLACKLIST, MIN_TITLE_LENGTH, MAX_TITLE_LENGTH,
    DESCRIPTION_DISQUALIFIERS, SCALE_SIGNALS,
)

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
]

def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
    }


# ── Core validation ───────────────────────────────────────────────────────────

def job_id(title: str, company: str, url: str = "") -> str:
    raw = f"{title.lower().strip()}|{company.lower().strip()}|{url}"
    return hashlib.md5(raw.encode()).hexdigest()

def is_valid_title(title: str) -> bool:
    if not title:
        return False
    t = title.strip()
    if len(t) < MIN_TITLE_LENGTH or len(t) > MAX_TITLE_LENGTH:
        return False
    tl = t.lower()
    if any(bad in tl for bad in TITLE_BLACKLIST):
        return False
    if not any(kw in tl for kw in EXEC_TITLES):
        return False
    return True

def is_relevant(title: str, description: str) -> bool:
    text = (title + " " + description).lower()
    return any(s in text for s in TARGET_SECTORS)

def passes_scale_filter(title: str, description: str) -> bool:
    """Return False for obvious SMB / low-scale postings to skip Claude scoring.
    If any positive scale signal is present, always passes regardless of disqualifiers.
    """
    text = (title + " " + description).lower()
    # Positive signals override everything — large company indicators let it through
    if any(sig in text for sig in SCALE_SIGNALS):
        return True
    # Disqualify if any SMB red-flag is present
    if any(dq in text for dq in DESCRIPTION_DISQUALIFIERS):
        return False
    # No strong signal either way — let it through (Claude decides on companyType)
    return True

def infer_sector(title: str, desc: str) -> str:
    t = (title + " " + desc).lower()
    if any(k in t for k in ["telecom","telecommunications","5g","wireless","network operator","carrier"]):
        return "Telecom"
    if any(k in t for k in ["data center","data centre","colocation","colo","hyperscaler"]):
        return "Data Center"
    if any(k in t for k in ["artificial intelligence"," ai ","machine learning","llm","generative ai"]):
        return "AI / Machine Learning"
    if any(k in t for k in ["energy","utilities","power grid","renewable","oil","nuclear","grid"]):
        return "Energy"
    if any(k in t for k in ["critical infrastructure","scada","defense","defence","nato"]):
        return "Critical Infrastructure"
    return "Technology"

def safe_get(url, timeout=20, extra_headers=None, params=None):
    h = get_headers()
    if extra_headers:
        h.update(extra_headers)
    try:
        r = requests.get(url, headers=h, timeout=timeout, params=params)
        if r.status_code == 200:
            return r
        logger.debug(f"HTTP {r.status_code}: {url[:80]}")
        return None
    except Exception as e:
        logger.debug(f"GET failed {url[:80]}: {e}")
        return None

def clean_text(html: str) -> str:
    return BeautifulSoup(html or "", "lxml").get_text(separator=" ", strip=True)[:3000]

def make_job(title, company, geography, description, url, source):
    if not is_valid_title(title):
        return None
    if not passes_scale_filter(title, description or ""):
        logger.debug(f"Scale filter rejected: {title} @ {company}")
        return None
    return {
        "id":          job_id(title, company, url),
        "title":       title.strip(),
        "company":     (company or "Confidential").strip(),
        "geography":   geography or "Global",
        "description": (description or f"{title} at {company}.")[:3000],
        "url":         url or "",
        "source":      source,
        "sector":      infer_sector(title, description or ""),
    }


# ── 1. Adzuna API (no salary filter — most exec roles don't list salary) ──────

def fetch_adzuna() -> list:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        logger.warning("Adzuna credentials not set")
        return []
    jobs = []
    for query in ADZUNA_QUERIES:
        for country in ADZUNA_COUNTRIES:
            url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
            params = {
                "app_id": ADZUNA_APP_ID,
                "app_key": ADZUNA_APP_KEY,
                "results_per_page": 20,
                "what": query,
                "max_days_old": MAX_JOB_AGE_DAYS,
                "content-type": "application/json",
                "sort_by": "date",
                "full_time": 1,
                "permanent": 1,
            }
            try:
                r = requests.get(url, params=params, timeout=15)
                r.raise_for_status()
                for item in r.json().get("results", []):
                    title   = item.get("title", "")
                    company = item.get("company", {}).get("display_name", "")
                    desc    = item.get("description", "")
                    loc     = item.get("location", {}).get("display_name", "")
                    href    = item.get("redirect_url", "")
                    j = make_job(title, company, loc, desc, href, f"Adzuna ({country.upper()})")
                    if j:
                        jobs.append(j)
            except Exception as e:
                logger.debug(f"Adzuna [{country}] '{query}': {e}")
            time.sleep(0.2)
    logger.info(f"Adzuna: {len(jobs)} validated matches")
    return jobs


# ── 2. JSearch via RapidAPI (aggregates LinkedIn + Indeed + Glassdoor) ────────

def fetch_jsearch() -> list:
    if not RAPIDAPI_KEY:
        logger.warning("RAPIDAPI_KEY not set — skipping JSearch")
        return []
    jobs = []
    for query in JSEARCH_QUERIES:
        try:
            r = requests.get(
                "https://jsearch.p.rapidapi.com/search",
                headers={
                    "X-RapidAPI-Key":  RAPIDAPI_KEY,
                    "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
                },
                params={
                    "query":      query,
                    "page":       "1",
                    "num_pages":  "2",
                    "date_posted":"month",
                    "employment_types": "FULLTIME",
                },
                timeout=20,
            )
            if r.status_code == 403:
                logger.warning("JSearch: 403 — check RAPIDAPI_KEY is valid and subscribed")
                break
            r.raise_for_status()
            data = r.json().get("data", [])
            logger.debug(f"JSearch '{query}': {len(data)} raw results")
            for item in data:
                title   = item.get("job_title", "")
                company = item.get("employer_name", "")
                desc    = clean_text(item.get("job_description", ""))
                city    = item.get("job_city", "")
                country = item.get("job_country", "")
                geo     = f"{city}, {country}".strip(", ") or "Global"
                href    = item.get("job_apply_link","") or item.get("job_google_link","")
                pub     = item.get("job_publisher","LinkedIn/Indeed")
                j = make_job(title, company, geo, desc, href, f"JSearch ({pub})")
                if j:
                    jobs.append(j)
            time.sleep(0.5)
        except Exception as e:
            logger.debug(f"JSearch '{query}': {e}")
    logger.info(f"JSearch: {len(jobs)} validated matches")
    return jobs


# ── 3. Himalayas API (free, no key — quality global tech/exec roles) ──────────
# Replaces the LinkedIn HTML scraper which is consistently blocked by bot detection.
# Himalayas aggregates exec roles across tech, telecom, AI, and infrastructure.

HIMALAYAS_QUERIES = [
    "CEO", "Chief Executive Officer", "Chief Operating Officer",
    "Executive Vice President", "Senior Vice President", "Managing Director",
    "President", "Chief Digital Officer", "Chief Transformation Officer",
]

def fetch_himalayas() -> list:
    jobs = []
    seen = set()
    for query in HIMALAYAS_QUERIES:
        try:
            r = requests.get(
                "https://himalayas.app/jobs/api",
                params={"q": query, "limit": 50},
                timeout=15,
            )
            if r.status_code != 200:
                logger.debug(f"Himalayas '{query}': HTTP {r.status_code}")
                continue
            for item in r.json().get("jobs", []):
                title   = item.get("title", "")
                company = item.get("company", {}).get("name", "") if isinstance(item.get("company"), dict) else item.get("company", "")
                desc    = clean_text(item.get("description", ""))
                geo     = item.get("location", "") or "Remote / Global"
                href    = item.get("applyUrl", "") or item.get("url", "")
                key     = f"{title.lower()}|{company.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                j = make_job(title, company, geo, desc, href, "Himalayas")
                if j and is_relevant(title, desc):
                    jobs.append(j)
        except Exception as e:
            logger.debug(f"Himalayas '{query}': {e}")
        time.sleep(0.3)
    logger.info(f"Himalayas: {len(jobs)} validated matches")
    return jobs


# ── 4. Reed.co.uk API (free, reliable, UK + international exec roles) ─────────

def fetch_reed() -> list:
    jobs = []
    for query in REED_QUERIES:
        try:
            r = requests.get(
                "https://www.reed.co.uk/api/1.0/search",
                auth=(os.getenv("REED_API_KEY", ""), ""),
                params={
                    "keywords":        query,
                    "resultsToTake":   50,
                    "fullTime":        True,
                    "minimumSalary":   100000,
                },
                timeout=15,
            )
            if r.status_code == 200:
                for item in r.json().get("results", []):
                    title   = item.get("jobTitle","")
                    company = item.get("employerName","")
                    loc     = item.get("locationName","")
                    desc    = item.get("jobDescription","")
                    href    = item.get("jobUrl","")
                    j = make_job(title, company, loc, desc, href, "Reed.co.uk")
                    if j:
                        jobs.append(j)
        except Exception as e:
            logger.debug(f"Reed '{query}': {e}")
        time.sleep(0.5)
    logger.info(f"Reed: {len(jobs)} validated matches")
    return jobs


# ── 5. Remotive (free API — global remote exec roles) ─────────────────────────

def fetch_remotive() -> list:
    jobs = []
    for category in REMOTIVE_CATEGORIES:
        try:
            r = requests.get(
                "https://remotive.com/api/remote-jobs",
                params={"category": category, "limit": 100},
                timeout=15,
            )
            r.raise_for_status()
            for item in r.json().get("jobs", []):
                title   = item.get("title","")
                company = item.get("company_name","")
                desc    = clean_text(item.get("description",""))
                href    = item.get("url","")
                j = make_job(title, company, "Remote / Global", desc, href, "Remotive")
                if j and is_relevant(title, desc):
                    jobs.append(j)
        except Exception as e:
            logger.debug(f"Remotive {category}: {e}")
        time.sleep(0.3)
    logger.info(f"Remotive: {len(jobs)} validated matches")
    return jobs


# ── 6. The Muse (free API — exec category) ────────────────────────────────────

def fetch_the_muse() -> list:
    jobs = []
    try:
        r = requests.get(
            "https://www.themuse.com/api/public/jobs",
            params={"category": "Executive", "page": 0, "descending": True},
            timeout=15,
        )
        r.raise_for_status()
        for item in r.json().get("results", []):
            title   = item.get("name","")
            company = item.get("company",{}).get("name","")
            desc    = clean_text(item.get("contents",""))
            locs    = item.get("locations",[])
            geo     = ", ".join(l.get("name","") for l in locs) or "Global"
            href    = item.get("refs",{}).get("landing_page","")
            j = make_job(title, company, geo, desc, href, "The Muse")
            if j and is_relevant(title, desc):
                jobs.append(j)
    except Exception as e:
        logger.debug(f"The Muse: {e}")
    logger.info(f"The Muse: {len(jobs)} validated matches")
    return jobs


# ── 7. Jobicy (free API — global remote senior roles) ─────────────────────────

def fetch_jobicy() -> list:
    jobs = []
    try:
        r = requests.get(
            "https://jobicy.com/api/v2/remote-jobs",
            params={"count": 50, "geo": "worldwide", "industry": "management"},
            timeout=15,
        )
        r.raise_for_status()
        for item in r.json().get("jobs", []):
            title   = item.get("jobTitle","")
            company = item.get("companyName","")
            desc    = clean_text(item.get("jobDescription",""))
            geo     = item.get("jobGeo","Global")
            href    = item.get("url","")
            j = make_job(title, company, geo, desc, href, "Jobicy")
            if j and is_relevant(title, desc):
                jobs.append(j)
    except Exception as e:
        logger.debug(f"Jobicy: {e}")
    logger.info(f"Jobicy: {len(jobs)} validated matches")
    return jobs


# ── 8. Exec search firm public pages (Korn Ferry) ─────────────────────────────

def fetch_korn_ferry() -> list:
    jobs = []
    urls = [
        "https://jobs.kornferry.com/search?q=chief+executive+officer",
        "https://jobs.kornferry.com/search?q=chief+operating+officer",
        "https://jobs.kornferry.com/search?q=executive+vice+president",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select("li.job-item, div.job-result, article[class*=job]")[:20]:
            a = card.select_one("a[href]")
            if not a:
                continue
            title = a.get_text(strip=True)
            href  = urljoin(url, a["href"])
            co_el = card.select_one(".company, .employer, [class*=company]")
            company = co_el.get_text(strip=True) if co_el else "Korn Ferry Client"
            j = make_job(title, company, "Global",
                        f"{title}. Executive search mandate via Korn Ferry.", href, "Korn Ferry")
            if j:
                jobs.append(j)
        time.sleep(1)
    logger.info(f"Korn Ferry: {len(jobs)} validated matches")
    return jobs


# ── Master fetch ──────────────────────────────────────────────────────────────

def fetch_all_jobs() -> tuple[list, list]:
    """Fetch from all sources. Returns (jobs, source_errors).
    source_errors is a list of strings describing any source that returned 0 results
    or raised an unexpected exception — used for Telegram health alerts.
    """
    all_jobs      = []
    seen_ids      = set()
    source_errors = []

    def add(source_name: str, new_jobs: list):
        count_before = len(all_jobs)
        for j in new_jobs:
            jid = j.get("id")
            if jid and jid not in seen_ids:
                seen_ids.add(jid)
                all_jobs.append(j)
        added = len(all_jobs) - count_before
        if added == 0:
            source_errors.append(f"{source_name} — 0 results (API down or credentials invalid?)")
            logger.warning(f"{source_name}: returned 0 validated jobs")
        return added

    logger.info("── Adzuna (no salary filter) ───────────────────")
    add("Adzuna", fetch_adzuna())

    logger.info("── JSearch (LinkedIn/Indeed/Glassdoor) ─────────")
    add("JSearch", fetch_jsearch())

    logger.info("── Himalayas API (replaces LinkedIn scrape) ────")
    add("Himalayas", fetch_himalayas())

    logger.info("── Reed.co.uk API ──────────────────────────────")
    add("Reed.co.uk", fetch_reed())

    logger.info("── Remotive API ────────────────────────────────")
    add("Remotive", fetch_remotive())

    logger.info("── The Muse API ────────────────────────────────")
    add("The Muse", fetch_the_muse())

    logger.info("── Jobicy API ──────────────────────────────────")
    add("Jobicy", fetch_jobicy())

    logger.info("── Korn Ferry ──────────────────────────────────")
    add("Korn Ferry", fetch_korn_ferry())

    logger.info(f"Total raw jobs (pre-scoring dedup): {len(all_jobs)}")
    if source_errors:
        logger.warning(f"Sources with issues: {source_errors}")
    return all_jobs, source_errors

"""
JLG Executive Job Hunt — Scraper v3
Sources:
  1. Adzuna API      — no salary filter, title-filtered only
  2. JSearch         — LinkedIn + Indeed + Glassdoor aggregator
  3. Himalayas       — free API, no key required (replaces LinkedIn scraper)
  4. Reed.co.uk      — free API, reliable UK + international
  5. Remotive        — free API, global remote exec roles
  6. The Muse        — free API, exec category
  7. Jobicy          — free API, global exec roles
  8. Korn Ferry      — public search pages
  9. Odgers Berndtson
 10. Heidrick & Struggles (Workday JSON API)
 11. Russell Reynolds Associates
 12. Egon Zehnder
 13. Boyden Global
 14. DHR Global
 15. Stanton Chase
 16. ZRG Partners
 17. Transearch
 18. Pedersen & Partners
 19. Caldwell
 20. Teneo
 21. Barton Partnership
"""
import hashlib
import logging
import os
import re
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
    DESCRIPTION_DISQUALIFIERS, SCALE_SIGNALS, JOOBLE_API_KEY, CAREERJET_API_KEY,
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

def _kw_in_title(kw: str, tl: str) -> bool:
    """Match exec keyword in lowercased title.
    Short acronyms (≤4 chars: ceo, coo, evp, svp) use word-boundary matching
    to avoid false positives like 'coos bay' matching 'coo' or 'svp' in 'rsvp'.
    """
    if len(kw) <= 4:
        return bool(re.search(r'(?<![a-z])' + re.escape(kw) + r'(?![a-z])', tl))
    return kw in tl


def is_valid_title(title: str) -> bool:
    if not title:
        return False
    t = title.strip()
    if len(t) < MIN_TITLE_LENGTH or len(t) > MAX_TITLE_LENGTH:
        return False
    tl = t.lower()
    if any(bad in tl for bad in TITLE_BLACKLIST):
        return False
    if not any(_kw_in_title(kw, tl) for kw in EXEC_TITLES):
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
                if r.status_code != 200:
                    logger.warning(f"Adzuna [{country}] '{query[:30]}': HTTP {r.status_code}")
                    time.sleep(0.2)
                    continue
                results = r.json().get("results", [])
                if results:
                    logger.info(f"Adzuna [{country.upper()}] '{query[:30]}': {len(results)} raw")
                for item in results:
                    title   = item.get("title", "")
                    company = item.get("company", {}).get("display_name", "")
                    desc    = item.get("description", "")
                    loc     = item.get("location", {}).get("display_name", "")
                    href    = item.get("redirect_url", "")
                    j = make_job(title, company, loc, desc, href, f"Adzuna ({country.upper()})")
                    if j:
                        jobs.append(j)
            except Exception as e:
                logger.warning(f"Adzuna [{country}] '{query[:30]}': {e}")
            time.sleep(0.2)
    logger.info(f"Adzuna: {len(jobs)} validated matches")
    return jobs


# ── 2. JSearch via RapidAPI (aggregates LinkedIn + Indeed + Glassdoor) ────────

def fetch_jsearch() -> list:
    if not RAPIDAPI_KEY:
        logger.warning("RAPIDAPI_KEY not set — skipping JSearch")
        return []
    jobs = []
    _HEADERS = {
        "X-RapidAPI-Key":  RAPIDAPI_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    for query in JSEARCH_QUERIES:
        try:
            r = requests.get(
                "https://jsearch.p.rapidapi.com/search",
                headers=_HEADERS,
                params={
                    "query":            query,
                    "page":             "1",
                    "num_pages":        "3",
                    "date_posted":      "month",
                    "employment_types": "FULLTIME",
                },
                timeout=20,
            )
            if r.status_code in (401, 403):
                logger.warning(f"JSearch: HTTP {r.status_code} — RAPIDAPI_KEY invalid or not subscribed")
                break
            if r.status_code == 429:
                logger.warning("JSearch: 429 rate limit hit — reduce JSEARCH_QUERIES or num_pages")
                break
            r.raise_for_status()
            data = r.json().get("data", [])
            logger.info(f"JSearch '{query[:40]}': {len(data)} raw results")
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
            time.sleep(1)
        except Exception as e:
            logger.warning(f"JSearch '{query[:40]}': {e}")
    logger.info(f"JSearch: {len(jobs)} validated matches")
    return jobs


# ── 2b. Active Jobs DB via RapidAPI (Fantastic.Jobs — 175k career sites) ──────

ACTIVE_JOBS_QUERIES = [
    "Chief Executive Officer",
    "Chief Operating Officer",
    "Executive Vice President technology",
    "Senior Vice President global",
    "Managing Director technology",
    "Chief Digital Officer",
    "Chief Transformation Officer",
    "President global technology",
]  # 8 queries × 30 days = 240/month — stays within 250 free-tier limit

def fetch_active_jobs_db() -> list:
    """Active Jobs DB — aggregates 175k career sites & ATS, hourly refresh.
    Subscribe at: rapidapi.com/fantastic-jobs/api/active-jobs-db
    Same RAPIDAPI_KEY, no new secret needed.
    """
    if not RAPIDAPI_KEY:
        logger.warning("RAPIDAPI_KEY not set — skipping Active Jobs DB")
        return []
    jobs = []
    seen = set()
    _HEADERS = {
        "X-RapidAPI-Key":  RAPIDAPI_KEY,
        "X-RapidAPI-Host": "active-jobs-db.p.rapidapi.com",
    }
    for query in ACTIVE_JOBS_QUERIES:
        # Retry loop: on 429 sleep and retry once; on auth fail abort entirely
        for attempt in range(3):
            try:
                r = requests.get(
                    "https://active-jobs-db.p.rapidapi.com/active-ats-7d",
                    headers=_HEADERS,
                    params={
                        "title_filter": f'"{query}"',
                        "limit":        50,
                        "offset":       0,
                    },
                    timeout=20,
                )
            except Exception as e:
                logger.warning(f"ActiveJobsDB '{query[:40]}': {e}")
                break

            if r.status_code in (401, 403):
                logger.warning(f"ActiveJobsDB: HTTP {r.status_code} — not subscribed on RapidAPI?")
                return jobs  # auth failure — no point retrying any query

            if r.status_code == 429:
                wait = 65 if attempt == 0 else 120
                logger.warning(f"ActiveJobsDB: 429 (attempt {attempt+1}/3) — sleeping {wait}s")
                time.sleep(wait)
                continue  # retry same query after cooldown

            if r.status_code != 200:
                logger.warning(f"ActiveJobsDB '{query[:40]}': HTTP {r.status_code} — {r.text[:120]}")
                break

            raw = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
            logger.info(f"ActiveJobsDB '{query[:40]}': {len(raw)} raw results")
            for item in raw:
                title   = item.get("title", "")
                company = item.get("organization", "") or item.get("company", "")
                locs    = item.get("locations_derived") or []
                raw_geo = locs[0] if locs else None
                geo     = raw_geo if raw_geo and raw_geo.lower() != "none" else "Global"
                desc    = clean_text(item.get("text_description", "") or item.get("description", ""))
                href    = item.get("url", "")
                key     = f"{title.lower()}|{company.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                j = make_job(title, company, geo, desc, href, "ActiveJobsDB")
                if j:
                    jobs.append(j)
            break  # success — exit retry loop

        time.sleep(5)  # 5s between queries — free tier has per-minute rate limits
    logger.info(f"ActiveJobsDB: {len(jobs)} validated matches")
    return jobs


# ── 2c. LinkedIn Job Search API via RapidAPI (Fantastic.Jobs — 8M+ roles) ─────

LINKEDIN_API_QUERIES = [
    "Chief Executive Officer",
    "Chief Operating Officer",
    "Executive Vice President",
    "Managing Director technology",
    "Senior Vice President operations",
    "Chief Digital Officer",
    "President global technology",
]

# Candidate (host, endpoint) pairs for LinkedIn Job Search APIs by Fantastic Jobs.
# RapidAPI returns 404 {"message":"Endpoint does not exist"} for wrong paths, so we
# probe in order and lock onto the first pair that returns 200.
# Probe log shows: linkedin-job-search-api → /active-ats-7d 404, /active-ats 404
#                  linkedin-jobs-api2       → /active-ats-7d 403 (not subscribed)
# Extended list covers more possible path patterns from this provider.
_LINKEDIN_CANDIDATES = [
    ("linkedin-job-search-api.p.rapidapi.com", "/active-ats-7d"),
    ("linkedin-job-search-api.p.rapidapi.com", "/active-ats"),
    ("linkedin-job-search-api.p.rapidapi.com", "/jobs"),
    ("linkedin-job-search-api.p.rapidapi.com", "/search"),
    ("linkedin-job-search-api.p.rapidapi.com", "/v1/active-ats-7d"),
    ("linkedin-job-search-api.p.rapidapi.com", "/v2/active-ats-7d"),
    ("linkedin-job-search-api.p.rapidapi.com", "/linkedin/active-ats-7d"),
    ("linkedin-job-search-api.p.rapidapi.com", "/api/active-ats-7d"),
    ("linkedin-jobs-api2.p.rapidapi.com",      "/active-ats-7d"),
    ("linkedin-jobs-api2.p.rapidapi.com",      "/active-ats"),
    ("linkedin-jobs-api2.p.rapidapi.com",      "/jobs"),
]

def _probe_linkedin_endpoint(rapidapi_key: str) -> tuple[str, str] | None:
    """Try each (host, endpoint) candidate and return the first one that returns 200.
    Logs response body on 404 to help diagnose what endpoints actually exist.
    On 401/403, stops trying the same host (auth/subscription issue for that API).
    """
    blocked_hosts: set[str] = set()
    for host, endpoint in _LINKEDIN_CANDIDATES:
        if host in blocked_hosts:
            continue
        try:
            r = requests.get(
                f"https://{host}{endpoint}",
                headers={"X-RapidAPI-Key": rapidapi_key, "X-RapidAPI-Host": host},
                params={"title_filter": '"Chief Executive Officer"', "limit": 1, "offset": 0},
                timeout=15,
            )
            body_hint = r.text[:200].replace("\n", " ")
            logger.info(f"LinkedInAPI probe: {host}{endpoint} → {r.status_code}  {body_hint}")
            if r.status_code == 200:
                return host, endpoint
            if r.status_code in (401, 403):
                logger.warning(f"LinkedInAPI: {r.status_code} on {host} — not subscribed to this API")
                blocked_hosts.add(host)  # skip all endpoints on this host
        except Exception as e:
            logger.debug(f"LinkedInAPI probe failed {host}{endpoint}: {e}")
    logger.warning("LinkedInAPI: no working endpoint found — check RapidAPI subscription")
    return None


def fetch_linkedin_rapidapi() -> list:
    """LinkedIn Job Search API — AI-enriched LinkedIn jobs via Fantastic Jobs on RapidAPI.
    Auto-probes endpoints since the correct path varies by API version subscribed.
    """
    if not RAPIDAPI_KEY:
        logger.warning("RAPIDAPI_KEY not set — skipping LinkedIn Job Search API")
        return []

    working = _probe_linkedin_endpoint(RAPIDAPI_KEY)
    if not working:
        return []
    host, endpoint = working
    logger.info(f"LinkedInAPI: using {host}{endpoint}")

    jobs = []
    seen = set()
    _HEADERS = {"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": host}

    for query in LINKEDIN_API_QUERIES:
        try:
            r = requests.get(
                f"https://{host}{endpoint}",
                headers=_HEADERS,
                params={"title_filter": f'"{query}"', "limit": 50, "offset": 0},
                timeout=20,
            )
            if r.status_code in (401, 403):
                logger.warning(f"LinkedInAPI: HTTP {r.status_code} — subscription expired?")
                break
            if r.status_code == 429:
                logger.warning("LinkedInAPI: 429 rate limit hit")
                break
            if r.status_code != 200:
                logger.warning(f"LinkedInAPI '{query[:40]}': HTTP {r.status_code} — {r.text[:120]}")
                continue
            raw = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
            logger.info(f"LinkedInAPI '{query[:40]}': {len(raw)} raw results")
            for item in raw:
                title   = item.get("title", "")
                company = item.get("organization", "") or item.get("company", "")
                locs    = item.get("locations_derived") or []
                raw_geo = locs[0] if locs else None
                geo     = raw_geo if raw_geo and raw_geo.lower() != "none" else "Global"
                desc    = clean_text(item.get("text_description", "") or item.get("description", ""))
                href    = item.get("url", "")
                key     = f"{title.lower()}|{company.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                j = make_job(title, company, geo, desc, href, "LinkedIn (RapidAPI)")
                if j:
                    jobs.append(j)
        except Exception as e:
            logger.warning(f"LinkedInAPI '{query[:40]}': {e}")
        time.sleep(1)
    logger.info(f"LinkedInAPI: {len(jobs)} validated matches")
    return jobs


# ── 3. Himalayas API (free, no key — quality global tech/exec roles) ──────────
# Replaces the LinkedIn HTML scraper which is consistently blocked by bot detection.

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
                logger.warning(f"Himalayas '{query}': HTTP {r.status_code}")
                continue
            raw = r.json().get("jobs", [])
            logger.info(f"Himalayas '{query}': {len(raw)} raw results")
            for item in raw:
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
                if j:
                    jobs.append(j)
        except Exception as e:
            logger.warning(f"Himalayas '{query}': {e}")
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
            raw = r.json().get("jobs", [])
            logger.info(f"Remotive '{category}': {len(raw)} raw results")
            for item in raw:
                title   = item.get("title","")
                company = item.get("company_name","")
                desc    = clean_text(item.get("description",""))
                href    = item.get("url","")
                j = make_job(title, company, "Remote / Global", desc, href, "Remotive")
                if j:
                    jobs.append(j)
        except Exception as e:
            logger.warning(f"Remotive '{category}': {e}")
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
        raw = r.json().get("results", [])
        logger.info(f"The Muse: {len(raw)} raw results")
        for item in raw:
            title   = item.get("name","")
            company = item.get("company",{}).get("name","")
            desc    = clean_text(item.get("contents",""))
            locs    = item.get("locations",[])
            geo     = ", ".join(l.get("name","") for l in locs) or "Global"
            href    = item.get("refs",{}).get("landing_page","")
            j = make_job(title, company, geo, desc, href, "The Muse")
            if j:
                jobs.append(j)
    except Exception as e:
        logger.warning(f"The Muse: {e}")
    logger.info(f"The Muse: {len(jobs)} validated matches")
    return jobs


# ── 7. Jobicy (free API — global remote senior roles) ─────────────────────────

def fetch_jobicy() -> list:
    jobs = []
    try:
        r = requests.get(
            "https://jobicy.com/api/v2/remote-jobs",
            params={"count": 50, "industry": "management"},
            timeout=15,
        )
        r.raise_for_status()
        raw = r.json().get("jobs", [])
        logger.info(f"Jobicy: {len(raw)} raw results")
        for item in raw:
            title   = item.get("jobTitle","")
            company = item.get("companyName","")
            desc    = clean_text(item.get("jobDescription",""))
            geo     = item.get("jobGeo","Global")
            href    = item.get("url","")
            j = make_job(title, company, geo, desc, href, "Jobicy")
            if j:
                jobs.append(j)
    except Exception as e:
        logger.warning(f"Jobicy: {e}")
    logger.info(f"Jobicy: {len(jobs)} validated matches")
    return jobs


# ── 8–21. Exec search firm scrapers — REMOVED ────────────────────────────────
# Korn Ferry, Odgers Berndtson, Heidrick & Struggles, Russell Reynolds,
# Egon Zehnder, Boyden, DHR Global, Stanton Chase, ZRG Partners, Transearch,
# Pedersen & Partners, Caldwell, Teneo, Barton Partnership all render with
# JavaScript (React/Angular). BeautifulSoup sees empty HTML; all return 0.
# They also waste ~3 minutes of the 30-min job timeout.
# TODO: replace with API-based sources (LinkedIn Jobs API, Indeed API, etc.)

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


# ── 9. Odgers Berndtson ───────────────────────────────────────────────────────

def fetch_odgers_berndtson() -> list:
    jobs = []
    urls = [
        "https://www.odgersberndtson.com/en-gb/searches",
        "https://www.odgersberndtson.com/en/searches",
        "https://www.odgersberndtson.com/en-us/searches",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(
            "article, [class*='search-result'], [class*='vacancy'], "
            "[class*='position'], [class*='search-card'], .card"
        )[:25]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='role']")
            loc_el   = card.select_one("[class*='location'], [class*='sector'], [class*='region']")
            if not a or not title_el:
                continue
            title = title_el.get_text(strip=True)
            geo   = loc_el.get_text(strip=True) if loc_el else "Global"
            href  = urljoin(url, a["href"])
            desc  = card.get_text(separator=" ", strip=True)[:600]
            j = make_job(title, "Odgers Berndtson Client", geo, desc, href, "Odgers Berndtson")
            if j:
                jobs.append(j)
        if jobs:
            break
        time.sleep(2)
    logger.info(f"Odgers Berndtson: {len(jobs)} validated matches")
    return jobs


# ── 10. Heidrick & Struggles (Workday JSON API) ───────────────────────────────

def fetch_heidrick() -> list:
    """Uses the Workday undocumented JSON API — returns structured data cleanly."""
    jobs = []
    try:
        r = requests.post(
            "https://heidrick.wd1.myworkdayjobs.com/wday/cxs/heidrickandstruggles"
            "/heidrickandstruggles/jobs",
            json={"limit": 20, "offset": 0, "searchText": ""},
            headers={
                "Content-Type": "application/json",
                "User-Agent":   random.choice(USER_AGENTS),
                "Accept":       "application/json",
            },
            timeout=20,
        )
        if r.status_code == 200:
            for item in r.json().get("jobPostings", []):
                title = item.get("title", "")
                geo   = item.get("locationsText", "Global")
                path  = item.get("externalPath", "")
                href  = (
                    f"https://heidrick.wd1.myworkdayjobs.com/heidrickandstruggles{path}"
                    if path else ""
                )
                desc  = (
                    f"{title}. Executive search mandate via Heidrick & Struggles. "
                    f"Location: {geo}. Global technology, telecom, digital transformation."
                )
                j = make_job(title, "Heidrick & Struggles Client", geo, desc, href,
                             "Heidrick & Struggles")
                if j:
                    jobs.append(j)
        else:
            logger.debug(f"Heidrick Workday API: HTTP {r.status_code}")
    except Exception as e:
        logger.debug(f"Heidrick: {e}")
    logger.info(f"Heidrick & Struggles: {len(jobs)} validated matches")
    return jobs


# ── 11. Russell Reynolds Associates ───────────────────────────────────────────

def fetch_russell_reynolds() -> list:
    jobs = []
    urls = [
        "https://www.russellreynolds.com/en/opportunities",
        "https://www.russellreynolds.com/en/expertise/searches",
        "https://russellreynolds.com/opportunities",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(
            "[class*='opportunity'], [class*='position'], [class*='search'], "
            "article, .card, [class*='listing']"
        )[:25]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='role']")
            loc_el   = card.select_one("[class*='location'], [class*='region'], [class*='geo']")
            if not a or not title_el:
                continue
            title = title_el.get_text(strip=True)
            geo   = loc_el.get_text(strip=True) if loc_el else "Global"
            href  = urljoin(url, a["href"])
            desc  = card.get_text(separator=" ", strip=True)[:600]
            j = make_job(title, "Russell Reynolds Client", geo, desc, href,
                         "Russell Reynolds")
            if j:
                jobs.append(j)
        if jobs:
            break
        time.sleep(2)
    logger.info(f"Russell Reynolds: {len(jobs)} validated matches")
    return jobs


# ── 12. Egon Zehnder ──────────────────────────────────────────────────────────

def fetch_egon_zehnder() -> list:
    jobs = []
    urls = [
        "https://www.egonzehnder.com/opportunities",
        "https://www.egonzehnder.com/what-we-do/executive-search/current-searches",
        "https://egonzehnder.com/open-positions",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(
            "[class*='opportunity'], [class*='position'], [class*='search'], "
            "article, .card, li[class*='item']"
        )[:25]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='role']")
            loc_el   = card.select_one("[class*='location'], [class*='region'], [class*='country']")
            if not a or not title_el:
                continue
            title = title_el.get_text(strip=True)
            geo   = loc_el.get_text(strip=True) if loc_el else "Global"
            href  = urljoin(url, a["href"])
            desc  = card.get_text(separator=" ", strip=True)[:600]
            j = make_job(title, "Egon Zehnder Client", geo, desc, href, "Egon Zehnder")
            if j:
                jobs.append(j)
        if jobs:
            break
        time.sleep(2)
    logger.info(f"Egon Zehnder: {len(jobs)} validated matches")
    return jobs


# ── 13. Boyden Global ─────────────────────────────────────────────────────────

def fetch_boyden() -> list:
    jobs = []
    urls = [
        "https://boyden.com/en/searches",
        "https://www.boyden.com/en/current-searches",
        "https://boyden.com/en/open-positions",
        "https://www.boyden.com/en/searches",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(
            "[class*='search'], [class*='position'], [class*='opportunity'], "
            "article, .card, [class*='listing']"
        )[:25]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='role']")
            loc_el   = card.select_one("[class*='location'], [class*='region'], [class*='country']")
            if not a or not title_el:
                continue
            title = title_el.get_text(strip=True)
            geo   = loc_el.get_text(strip=True) if loc_el else "Global"
            href  = urljoin(url, a["href"])
            desc  = card.get_text(separator=" ", strip=True)[:600]
            j = make_job(title, "Boyden Client", geo, desc, href, "Boyden Global")
            if j:
                jobs.append(j)
        if jobs:
            break
        time.sleep(2)
    logger.info(f"Boyden Global: {len(jobs)} validated matches")
    return jobs


# ── 14. DHR Global ────────────────────────────────────────────────────────────

def fetch_dhr() -> list:
    jobs = []
    urls = [
        "https://dhrglobal.com/open-searches",
        "https://www.dhrglobal.com/searches",
        "https://dhrglobal.com/opportunities",
        "https://www.dhrglobal.com/open-positions",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(
            "[class*='search'], [class*='position'], [class*='job'], "
            "article, .card, [class*='listing']"
        )[:25]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='role']")
            loc_el   = card.select_one("[class*='location'], [class*='region']")
            if not a or not title_el:
                continue
            title = title_el.get_text(strip=True)
            geo   = loc_el.get_text(strip=True) if loc_el else "Global"
            href  = urljoin(url, a["href"])
            desc  = card.get_text(separator=" ", strip=True)[:600]
            j = make_job(title, "DHR Global Client", geo, desc, href, "DHR Global")
            if j:
                jobs.append(j)
        if jobs:
            break
        time.sleep(2)
    logger.info(f"DHR Global: {len(jobs)} validated matches")
    return jobs


# ── 15. Stanton Chase ─────────────────────────────────────────────────────────

def fetch_stanton_chase() -> list:
    jobs = []
    urls = [
        "https://stantonchase.com/open-positions",
        "https://www.stantonchase.com/current-searches",
        "https://stantonchase.com/opportunities",
        "https://www.stantonchase.com/executive-positions",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(
            "[class*='position'], [class*='search'], [class*='job'], "
            "article, .card, [class*='vacancy']"
        )[:25]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='role']")
            loc_el   = card.select_one("[class*='location'], [class*='region'], [class*='country']")
            if not a or not title_el:
                continue
            title = title_el.get_text(strip=True)
            geo   = loc_el.get_text(strip=True) if loc_el else "Global"
            href  = urljoin(url, a["href"])
            desc  = card.get_text(separator=" ", strip=True)[:600]
            j = make_job(title, "Stanton Chase Client", geo, desc, href, "Stanton Chase")
            if j:
                jobs.append(j)
        if jobs:
            break
        time.sleep(2)
    logger.info(f"Stanton Chase: {len(jobs)} validated matches")
    return jobs


# ── 16. ZRG Partners ──────────────────────────────────────────────────────────

def fetch_zrg() -> list:
    """ZRG has a dedicated /jobboard page built on Webflow."""
    jobs = []
    try:
        r = safe_get("https://zrgpartners.com/jobboard")
        if not r:
            logger.info("ZRG Partners: 0 validated matches")
            return []
        soup = BeautifulSoup(r.text, "lxml")
        # Webflow sites use .w-dyn-item for CMS collection items
        for card in soup.select(
            ".w-dyn-item, [class*='job'], [class*='position'], [class*='search'], article"
        )[:30]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='heading'], [class*='role']")
            loc_el   = card.select_one("[class*='location'], [class*='city'], [class*='region']")
            if not a or not title_el:
                continue
            title = title_el.get_text(strip=True)
            geo   = loc_el.get_text(strip=True) if loc_el else "Global"
            href  = urljoin("https://zrgpartners.com", a["href"])
            desc  = card.get_text(separator=" ", strip=True)[:600]
            j = make_job(title, "ZRG Partners Client", geo, desc, href, "ZRG Partners")
            if j:
                jobs.append(j)
    except Exception as e:
        logger.debug(f"ZRG Partners: {e}")
    logger.info(f"ZRG Partners: {len(jobs)} validated matches")
    return jobs


# ── 17. Transearch ────────────────────────────────────────────────────────────

def fetch_transearch() -> list:
    jobs = []
    urls = [
        "https://www.transearch.com/en/opportunities",
        "https://transearch.com/opportunities",
        "https://www.transearch.com/en/current-searches",
        "https://www.transearch.com/searches",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(
            "[class*='opportunity'], [class*='search'], [class*='position'], "
            "article, .card, [class*='vacancy']"
        )[:25]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='role']")
            loc_el   = card.select_one("[class*='location'], [class*='region'], [class*='country']")
            if not a or not title_el:
                continue
            title = title_el.get_text(strip=True)
            geo   = loc_el.get_text(strip=True) if loc_el else "Global"
            href  = urljoin(url, a["href"])
            desc  = card.get_text(separator=" ", strip=True)[:600]
            j = make_job(title, "Transearch Client", geo, desc, href, "Transearch")
            if j:
                jobs.append(j)
        if jobs:
            break
        time.sleep(2)
    logger.info(f"Transearch: {len(jobs)} validated matches")
    return jobs


# ── 18. Pedersen & Partners ───────────────────────────────────────────────────

def fetch_pedersen() -> list:
    jobs = []
    urls = [
        "https://www.pedersenandpartners.com/opportunities",
        "https://www.pedersenandpartners.com/en/open-positions",
        "https://www.pedersenandpartners.com/content/current-searches",
        "https://pedersenandpartners.com/searches",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(
            "[class*='opportunity'], [class*='search'], [class*='position'], "
            "article, .card, li[class*='item'], [class*='vacancy']"
        )[:25]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='role']")
            loc_el   = card.select_one("[class*='location'], [class*='region'], [class*='country']")
            if not a or not title_el:
                continue
            title = title_el.get_text(strip=True)
            geo   = loc_el.get_text(strip=True) if loc_el else "Global"
            href  = urljoin(url, a["href"])
            desc  = card.get_text(separator=" ", strip=True)[:600]
            j = make_job(title, "Pedersen & Partners Client", geo, desc, href,
                         "Pedersen & Partners")
            if j:
                jobs.append(j)
        if jobs:
            break
        time.sleep(2)
    logger.info(f"Pedersen & Partners: {len(jobs)} validated matches")
    return jobs


# ── 19. Caldwell ──────────────────────────────────────────────────────────────

def fetch_caldwell() -> list:
    jobs = []
    urls = [
        "https://www.caldwell.com/executive-job-opportunities/",
        "https://www.caldwell.com/searches/",
        "https://caldwell.com/open-searches/",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(
            "[class*='opportunity'], [class*='search'], [class*='position'], "
            "[class*='job'], article, .card, [class*='listing']"
        )[:25]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='role']")
            loc_el   = card.select_one("[class*='location'], [class*='region']")
            if not a or not title_el:
                continue
            title = title_el.get_text(strip=True)
            geo   = loc_el.get_text(strip=True) if loc_el else "Global"
            href  = urljoin(url, a["href"])
            desc  = card.get_text(separator=" ", strip=True)[:600]
            j = make_job(title, "Caldwell Client", geo, desc, href, "Caldwell")
            if j:
                jobs.append(j)
        if jobs:
            break
        time.sleep(2)
    logger.info(f"Caldwell: {len(jobs)} validated matches")
    return jobs


# ── 20. Teneo ─────────────────────────────────────────────────────────────────

def fetch_teneo() -> list:
    jobs = []
    urls = [
        "https://www.teneo.com/careers/",
        "https://teneo.com/open-positions/",
        "https://www.teneo.com/executive-search/",
        "https://www.teneo.com/our-work/executive-search/",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(
            "[class*='position'], [class*='job'], [class*='search'], "
            "[class*='vacancy'], article, .card"
        )[:25]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='role']")
            loc_el   = card.select_one("[class*='location'], [class*='region']")
            if not a or not title_el:
                continue
            title = title_el.get_text(strip=True)
            geo   = loc_el.get_text(strip=True) if loc_el else "Global"
            href  = urljoin(url, a["href"])
            desc  = card.get_text(separator=" ", strip=True)[:600]
            j = make_job(title, "Teneo Client", geo, desc, href, "Teneo")
            if j:
                jobs.append(j)
        if jobs:
            break
        time.sleep(2)
    logger.info(f"Teneo: {len(jobs)} validated matches")
    return jobs


# ── 21. Barton Partnership ────────────────────────────────────────────────────

def fetch_barton_partnership() -> list:
    jobs = []
    urls = [
        "https://www.bartonpartnership.com/opportunities/",
        "https://bartonpartnership.com/jobs/",
        "https://www.bartonpartnership.com/open-positions/",
        "https://bartonpartnership.com/current-searches/",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(
            "[class*='opportunity'], [class*='position'], [class*='job'], "
            "article, .card, [class*='vacancy'], [class*='search']"
        )[:25]:
            a = card.select_one("a[href]")
            title_el = card.select_one("h2, h3, h4, [class*='title'], [class*='role']")
            loc_el   = card.select_one("[class*='location'], [class*='region']")
            if not a or not title_el:
                continue
            title = title_el.get_text(strip=True)
            geo   = loc_el.get_text(strip=True) if loc_el else "Global"
            href  = urljoin(url, a["href"])
            desc  = card.get_text(separator=" ", strip=True)[:600]
            j = make_job(title, "Barton Partnership Client", geo, desc, href,
                         "Barton Partnership")
            if j:
                jobs.append(j)
        if jobs:
            break
        time.sleep(2)
    logger.info(f"Barton Partnership: {len(jobs)} validated matches")
    return jobs


# ── Jooble API (free, global aggregator — POST-based) ────────────────────────

JOOBLE_QUERIES = [
    "Chief Executive Officer",
    "Chief Operating Officer global",
    "Executive Vice President technology",
    "Senior Vice President global operations",
    "Managing Director technology EMEA",
    "Chief Digital Officer",
    "Chief Transformation Officer",
    "CEO telecom",
    "COO data center",
    "President global technology",
]

def fetch_jooble() -> list:
    if not JOOBLE_API_KEY:
        logger.warning("JOOBLE_API_KEY not set — skipping Jooble")
        return []
    jobs = []
    seen = set()
    for query in JOOBLE_QUERIES:
        try:
            r = requests.post(
                f"https://jooble.org/api/{JOOBLE_API_KEY}",
                json={"keywords": query, "page": 1, "resultonpage": 20},
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            if r.status_code != 200:
                logger.warning(f"Jooble '{query[:40]}': HTTP {r.status_code}")
                continue
            raw = r.json().get("jobs", [])
            logger.info(f"Jooble '{query[:40]}': {len(raw)} raw results")
            for item in raw:
                title   = item.get("title", "")
                company = item.get("company", "")
                geo     = item.get("location", "") or "Global"
                desc    = clean_text(item.get("snippet", ""))
                href    = item.get("link", "")
                key     = f"{title.lower()}|{company.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                j = make_job(title, company, geo, desc, href, "Jooble")
                if j:
                    jobs.append(j)
        except Exception as e:
            logger.warning(f"Jooble '{query[:40]}': {e}")
        time.sleep(0.5)
    logger.info(f"Jooble: {len(jobs)} validated matches")
    return jobs


# ── CareerJet API (free, global aggregator — GET-based) ──────────────────────

CAREERJET_QUERIES = [
    "Chief Executive Officer",
    "Chief Operating Officer",
    "Executive Vice President technology",
    "Senior Vice President operations",
    "Managing Director technology",
    "Chief Digital Officer",
    "Chief Transformation Officer",
    "CEO telecom",
    "COO global technology",
    "President technology",
]

def fetch_careerjet() -> list:
    if not CAREERJET_API_KEY:
        logger.warning("CAREERJET_API_KEY not set — skipping CareerJet")
        return []
    jobs = []
    seen = set()
    for query in CAREERJET_QUERIES:
        try:
            r = requests.get(
                "https://search.api.careerjet.net/v4/query",
                auth=(CAREERJET_API_KEY, ""),
                params={
                    "keywords":      query,
                    "user_ip":       "1.2.3.4",
                    "user_agent":    "Mozilla/5.0",
                    "page_size":     20,
                    "sort":          "date",
                    "contract_type": "p",
                    "work_hours":    "f",
                },
                timeout=15,
            )
            if r.status_code != 200:
                logger.warning(f"CareerJet '{query[:40]}': HTTP {r.status_code} — {r.text[:120]}")
                continue
            raw = r.json().get("jobs", [])
            logger.info(f"CareerJet '{query[:40]}': {len(raw)} raw results")
            for item in raw:
                title   = item.get("title", "")
                company = item.get("company", "")
                geo     = item.get("locations", "") or "Global"
                desc    = clean_text(item.get("description", ""))
                href    = item.get("url", "")
                key     = f"{title.lower()}|{company.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                j = make_job(title, company, geo, desc, href, "CareerJet")
                if j:
                    jobs.append(j)
        except Exception as e:
            logger.warning(f"CareerJet '{query[:40]}': {e}")
        time.sleep(0.5)
    logger.info(f"CareerJet: {len(jobs)} validated matches")
    return jobs


# ── Exec Search Firms — JSON APIs (no JS rendering needed) ───────────────────
#
# These firms have discoverable backend APIs. Each is different:
#   Heidrick & Struggles  → Workday public career site API (no auth)
#   Spencer Stuart        → Workday public career site API (no auth)
#   Egon Zehnder          → Workable public API (no auth)
#   Teneo                 → Greenhouse public job board API (no auth)
#   ZRG Partners          → Rippling public ATS API (no auth)


def _workday_fetch(instance: str, company: str, site: str, source_label: str) -> list:
    """Reusable Workday public career site JSON fetcher (no authentication needed).
    Works for any firm that hosts their career page on myworkdayjobs.com.
    """
    jobs = []
    base_url = f"https://{instance}.myworkdayjobs.com"
    api_url  = f"{base_url}/wday/cxs/{company}/{site}/jobs"
    offset   = 0
    limit    = 20
    while True:
        try:
            r = requests.post(
                api_url,
                json={"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""},
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            if r.status_code != 200:
                logger.warning(f"{source_label} Workday: HTTP {r.status_code} — {r.text[:120]}")
                break
            data     = r.json()
            postings = data.get("jobPostings", [])
            total    = data.get("total", 0)
            logger.info(f"{source_label} Workday: offset={offset}, got {len(postings)}/{total}")
            for item in postings:
                title = item.get("title", "")
                geo   = item.get("locationsText", "Global")
                path  = item.get("externalPath", "")
                href  = f"{base_url}{path}" if path else ""
                j = make_job(title, f"{source_label} Client", geo, "", href, source_label)
                if j:
                    jobs.append(j)
            offset += limit
            if offset >= total or not postings:
                break
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"{source_label} Workday: {e}")
            break
    return jobs


def fetch_heidrick() -> list:
    jobs = _workday_fetch(
        instance="heidrick.wd1",
        company="heidrick",
        site="heidrickandstruggles",
        source_label="Heidrick & Struggles",
    )
    logger.info(f"Heidrick & Struggles: {len(jobs)} validated matches")
    return jobs


def fetch_spencer_stuart() -> list:
    jobs = _workday_fetch(
        instance="spencerstuart.wd5",
        company="spencerstuart",
        site="Spencer_Stuart_External_Careers",
        source_label="Spencer Stuart",
    )
    logger.info(f"Spencer Stuart: {len(jobs)} validated matches")
    return jobs


def fetch_egon_zehnder() -> list:
    """Egon Zehnder client executive searches via Workable public API."""
    jobs = []
    seen = set()
    try:
        r = requests.post(
            "https://apply.workable.com/api/v3/accounts/ezrecruiting/jobs",
            json={"query": "", "location": [], "workplace": [], "department": []},
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code == 404:
            logger.warning("Egon Zehnder Workable: 404 — subdomain may have changed")
            return []
        if r.status_code != 200:
            logger.warning(f"Egon Zehnder Workable: HTTP {r.status_code} — {r.text[:120]}")
            return []
        results = r.json().get("results", [])
        logger.info(f"Egon Zehnder Workable: {len(results)} raw results")
        for item in results:
            title   = item.get("title", "")
            loc     = item.get("location", {})
            geo     = ", ".join(filter(None, [loc.get("city", ""), loc.get("country", "")])) or "Global"
            href    = item.get("url", "")
            dept    = item.get("department", "")
            desc    = f"{title} — {dept}".strip(" —")
            key     = f"{title.lower()}|egon zehnder"
            if key in seen:
                continue
            seen.add(key)
            j = make_job(title, "Egon Zehnder Client", geo, desc, href, "Egon Zehnder")
            if j:
                jobs.append(j)
    except Exception as e:
        logger.warning(f"Egon Zehnder Workable: {e}")
    logger.info(f"Egon Zehnder: {len(jobs)} validated matches")
    return jobs


def fetch_teneo() -> list:
    """Teneo open positions via Greenhouse public job board API."""
    jobs = []
    try:
        r = requests.get(
            "https://boards-api.greenhouse.io/v1/boards/teneo/jobs",
            params={"content": "true"},
            timeout=20,
        )
        if r.status_code == 404:
            logger.warning("Teneo Greenhouse: 404 — board token may have changed")
            return []
        if r.status_code != 200:
            logger.warning(f"Teneo Greenhouse: HTTP {r.status_code} — {r.text[:120]}")
            return []
        items = r.json().get("jobs", [])
        logger.info(f"Teneo Greenhouse: {len(items)} raw results")
        for item in items:
            title = item.get("title", "")
            geo   = item.get("location", {}).get("name", "Global")
            href  = item.get("absolute_url", "")
            desc  = clean_text(item.get("content", ""))
            j = make_job(title, "Teneo", geo, desc, href, "Teneo")
            if j:
                jobs.append(j)
    except Exception as e:
        logger.warning(f"Teneo Greenhouse: {e}")
    logger.info(f"Teneo: {len(jobs)} validated matches")
    return jobs


def fetch_zrg_partners() -> list:
    """ZRG Partners executive searches via Rippling public ATS API."""
    jobs = []
    try:
        r = requests.get(
            "https://api.rippling.com/platform/api/ats/v1/board/zrg-partners-careers/jobs",
            timeout=20,
        )
        if r.status_code == 404:
            logger.warning("ZRG Partners Rippling: 404 — board slug may have changed")
            return []
        if r.status_code != 200:
            logger.warning(f"ZRG Partners Rippling: HTTP {r.status_code} — {r.text[:120]}")
            return []
        items = r.json() if isinstance(r.json(), list) else r.json().get("jobs", [])
        logger.info(f"ZRG Partners Rippling: {len(items)} raw results")
        for item in items:
            title = item.get("title", "") or item.get("name", "")
            geo   = item.get("location", "") or item.get("locationName", "Global")
            href  = item.get("jobUrl", "") or item.get("url", "")
            desc  = clean_text(item.get("description", ""))
            j = make_job(title, "ZRG Partners Client", geo, desc, href, "ZRG Partners")
            if j:
                jobs.append(j)
    except Exception as e:
        logger.warning(f"ZRG Partners Rippling: {e}")
    logger.info(f"ZRG Partners: {len(jobs)} validated matches")
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

    logger.info("── Active Jobs DB (175k career sites) ──────────")
    add("ActiveJobsDB", fetch_active_jobs_db())

    logger.info("── LinkedIn Job Search API (RapidAPI) ──────────")
    add("LinkedInAPI", fetch_linkedin_rapidapi())

    # Himalayas, Remotive, The Muse dropped — startup/remote boards,
    # titles never match C-suite exec criteria (CEO/COO at $3B+ scale)

    logger.info("── Reed.co.uk API ──────────────────────────────")
    add("Reed.co.uk", fetch_reed())

    logger.info("── Jobicy API ──────────────────────────────────")
    add("Jobicy", fetch_jobicy())

    logger.info("── Jooble API ──────────────────────────────────")
    add("Jooble", fetch_jooble())

    # CareerJet removed — blocks GitHub Actions IPs with HTTP 403
    # Heidrick & Struggles removed — Workday page lists internal H&S hiring, not client searches
    # Spencer Stuart removed — same issue as Heidrick

    logger.info("── Egon Zehnder (Workable) ──────────────────────")
    add("Egon Zehnder", fetch_egon_zehnder())

    logger.info("── Teneo (Greenhouse) ───────────────────────────")
    add("Teneo", fetch_teneo())

    logger.info("── ZRG Partners (Rippling) ──────────────────────")
    add("ZRG Partners", fetch_zrg_partners())

    logger.info(f"Total raw jobs (pre-scoring dedup): {len(all_jobs)}")
    if source_errors:
        logger.warning(f"Sources with issues: {source_errors}")
    return all_jobs, source_errors

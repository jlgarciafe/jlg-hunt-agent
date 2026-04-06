"""
JLG Executive Job Hunt — Scraper v3
Sources:
  1. Adzuna API      — no salary filter, title-filtered only
  2. JSearch         — LinkedIn + Indeed + Glassdoor aggregator
  3. LinkedIn        — direct scrape
  4. Reed.co.uk      — free API, reliable UK + international
  5. Remotive        — free API, global remote exec roles
  6. The Muse        — free API, exec category
  7. Jobicy          — free API, global exec roles
  8. Exec search RSS — Korn Ferry, Spencer Stuart public feeds
"""
import hashlib
import logging
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin

from config import (
    ADZUNA_APP_ID, ADZUNA_APP_KEY, ADZUNA_COUNTRIES, ADZUNA_QUERIES,
    MAX_JOB_AGE_DAYS, RAPIDAPI_KEY, JSEARCH_QUERIES,
    LINKEDIN_QUERIES, LINKEDIN_LOCATIONS, REED_QUERIES,
    REMOTIVE_CATEGORIES, TARGET_SECTORS, EXEC_TITLES,
    TITLE_BLACKLIST, MIN_TITLE_LENGTH, MAX_TITLE_LENGTH,
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


# ── 3. LinkedIn Jobs (direct scrape with rotation) ────────────────────────────

def fetch_linkedin() -> list:
    jobs = []
    for query in LINKEDIN_QUERIES[:4]:
        for location in LINKEDIN_LOCATIONS[:3]:
            url = (
                "https://www.linkedin.com/jobs/search/"
                f"?keywords={quote(query)}&location={quote(location)}"
                "&f_TPR=r1209600&f_JT=F&sortBy=DD"
            )
            r = safe_get(url, extra_headers={"Referer": "https://www.linkedin.com/"})
            if not r:
                time.sleep(3)
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for card in soup.select("div.job-search-card, li.jobs-search__results-list > li")[:15]:
                title_el   = card.select_one("h3")
                company_el = card.select_one("h4")
                geo_el     = card.select_one(".job-search-card__location")
                a_el       = card.select_one("a[href]")
                title   = title_el.get_text(strip=True) if title_el else ""
                company = company_el.get_text(strip=True) if company_el else ""
                geo     = geo_el.get_text(strip=True) if geo_el else location
                href    = a_el.get("href","") if a_el else ""
                j = make_job(title, company, geo, f"{title} at {company}. {geo}.", href, "LinkedIn")
                if j:
                    jobs.append(j)
            time.sleep(random.uniform(3, 5))
    logger.info(f"LinkedIn: {len(jobs)} validated matches")
    return jobs


# ── 4. Reed.co.uk API (free, reliable, UK + international exec roles) ─────────

def fetch_reed() -> list:
    jobs = []
    for query in REED_QUERIES:
        try:
            r = requests.get(
                "https://www.reed.co.uk/api/1.0/search",
                auth=("", ""),   # Reed API uses empty string as password with API key as user
                params={
                    "keywords":        query,
                    "resultsToTake":   50,
                    "fullTime":        True,
                    "minimumSalary":   100000,
                },
                timeout=15,
            )
            # Reed requires registration but returns data without key for limited use
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


# ── 8. Exec search firm public pages (Korn Ferry, Spencer Stuart) ─────────────

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

def fetch_all_jobs() -> list:
    all_jobs = []
    seen_ids = set()

    def add(new_jobs: list):
        for j in new_jobs:
            jid = j.get("id")
            if jid and jid not in seen_ids:
                seen_ids.add(jid)
                all_jobs.append(j)

    logger.info("── Adzuna (no salary filter) ───────────────────")
    add(fetch_adzuna())

    logger.info("── JSearch (LinkedIn/Indeed/Glassdoor) ─────────")
    add(fetch_jsearch())

    logger.info("── LinkedIn (direct scrape) ────────────────────")
    add(fetch_linkedin())

    logger.info("── Reed.co.uk API ──────────────────────────────")
    add(fetch_reed())

    logger.info("── Remotive API ────────────────────────────────")
    add(fetch_remotive())

    logger.info("── The Muse API ────────────────────────────────")
    add(fetch_the_muse())

    logger.info("── Jobicy API ──────────────────────────────────")
    add(fetch_jobicy())

    logger.info("── Korn Ferry ──────────────────────────────────")
    add(fetch_korn_ferry())

    logger.info(f"Total raw jobs (pre-scoring dedup): {len(all_jobs)}")
    return all_jobs

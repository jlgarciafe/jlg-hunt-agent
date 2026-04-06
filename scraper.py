"""
JLG Executive Job Hunt — Scraper v2
Sources:
  1. Adzuna API           — salary-filtered, executive queries only
  2. JSearch / RapidAPI  — aggregates LinkedIn + Indeed + Glassdoor
  3. LinkedIn Jobs        — direct scrape with rotation
  4. Microsoft Careers    — JSON API
  5. Amazon Jobs          — JSON API
  6. IBM Careers          — JSON API
  7. Workday companies    — Nokia, Ericsson, Equinix, BP, Digital Realty
  8. Executive boards     — The Ladders, ExecThread, Exec-Appointments
  9. Exec search firms    — Korn Ferry, Spencer Stuart, Heidrick, Russell Reynolds
"""
import hashlib
import json
import logging
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote

from config import (
    ADZUNA_APP_ID, ADZUNA_APP_KEY, ADZUNA_COUNTRIES, ADZUNA_QUERIES,
    MIN_SALARY_USD, MAX_JOB_AGE_DAYS, RESULTS_PER_SOURCE,
    RAPIDAPI_KEY, JSEARCH_QUERIES, LINKEDIN_QUERIES, LINKEDIN_LOCATIONS,
    TARGET_SECTORS, EXEC_TITLES, TITLE_BLACKLIST,
    MIN_TITLE_LENGTH, MAX_TITLE_LENGTH,
)

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
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
    """Strict title validation — rejects nav links, cookie notices, junior roles."""
    if not title:
        return False
    t = title.strip()
    # Length check
    if len(t) < MIN_TITLE_LENGTH or len(t) > MAX_TITLE_LENGTH:
        return False
    # Blacklist check
    tl = t.lower()
    if any(bad in tl for bad in TITLE_BLACKLIST):
        return False
    # Must contain an executive keyword
    if not any(kw in tl for kw in EXEC_TITLES):
        return False
    return True

def is_relevant(title: str, description: str) -> bool:
    text = (title + " " + description).lower()
    return any(s in text for s in TARGET_SECTORS)

def infer_sector(title: str, desc: str) -> str:
    t = (title + " " + desc).lower()
    if any(k in t for k in ["telecom","telecommunications","5g","wireless","network operator","carrier","mvno"]):
        return "Telecom"
    if any(k in t for k in ["data center","data centre","colocation","colo","hyperscaler"]):
        return "Data Center"
    if any(k in t for k in ["artificial intelligence"," ai ","machine learning","llm","generative"]):
        return "AI / Machine Learning"
    if any(k in t for k in ["energy","utilities","power grid","renewable","oil and gas","nuclear","grid"]):
        return "Energy"
    if any(k in t for k in ["critical infrastructure","scada","industrial","defense","defence","nato"]):
        return "Critical Infrastructure"
    return "Technology"

def safe_get(url, timeout=20, extra_headers=None):
    h = get_headers()
    if extra_headers:
        h.update(extra_headers)
    try:
        r = requests.get(url, headers=h, timeout=timeout)
        if r.status_code == 200:
            return r
        logger.debug(f"HTTP {r.status_code} for {url}")
        return None
    except Exception as e:
        logger.debug(f"GET failed {url}: {e}")
        return None

def parse_text(html: str) -> str:
    return BeautifulSoup(html or "", "lxml").get_text(separator=" ", strip=True)[:3000]

def make_job(title, company, geography, description, url, source):
    """Create a validated job dict or return None if invalid."""
    if not is_valid_title(title):
        return None
    return {
        "id":          job_id(title, company, url),
        "title":       title.strip(),
        "company":     company.strip() or "Confidential",
        "geography":   geography or "Global",
        "description": description[:3000] if description else f"{title} at {company}.",
        "url":         url,
        "source":      source,
        "sector":      infer_sector(title, description or ""),
    }


# ── 1. Adzuna API (salary-filtered) ──────────────────────────────────────────

def fetch_adzuna() -> list:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        logger.warning("Adzuna credentials not set")
        return []
    jobs = []
    for query in ADZUNA_QUERIES:
        for country in ADZUNA_COUNTRIES[:5]:
            url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
            params = {
                "app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
                "results_per_page": 20, "what": query,
                "max_days_old": MAX_JOB_AGE_DAYS,
                "content-type": "application/json", "sort_by": "date",
            }
            if country in ["us", "gb", "au", "ca"]:
                params["salary_min"] = MIN_SALARY_USD
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
            time.sleep(0.3)
    logger.info(f"Adzuna: {len(jobs)} validated matches")
    return jobs


# ── 2. JSearch / RapidAPI ─────────────────────────────────────────────────────

def fetch_jsearch() -> list:
    if not RAPIDAPI_KEY:
        logger.info("RAPIDAPI_KEY not set — skipping JSearch")
        return []
    jobs = []
    for query in JSEARCH_QUERIES:
        try:
            r = requests.get(
                "https://jsearch.p.rapidapi.com/search",
                headers={"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"},
                params={"query": query, "page": "1", "num_pages": "1", "date_posted": "month"},
                timeout=15,
            )
            r.raise_for_status()
            for item in r.json().get("data", []):
                title   = item.get("job_title", "")
                company = item.get("employer_name", "")
                desc    = parse_text(item.get("job_description", ""))
                geo     = f"{item.get('job_city','')} {item.get('job_country','')}".strip() or "Global"
                href    = item.get("job_apply_link", "") or item.get("job_google_link", "")
                publisher = item.get("job_publisher", "LinkedIn/Indeed")
                j = make_job(title, company, geo, desc, href, f"JSearch ({publisher})")
                if j:
                    jobs.append(j)
            time.sleep(0.5)
        except Exception as e:
            logger.debug(f"JSearch '{query}': {e}")
    logger.info(f"JSearch: {len(jobs)} validated matches")
    return jobs


# ── 3. LinkedIn Jobs (structured scrape) ──────────────────────────────────────

def fetch_linkedin() -> list:
    jobs = []
    for query in LINKEDIN_QUERIES[:4]:
        for location in LINKEDIN_LOCATIONS[:3]:
            url = (
                f"https://www.linkedin.com/jobs/search/?keywords={quote(query)}"
                f"&location={quote(location)}&f_TPR=r604800&f_JT=F&sortBy=DD"
                f"&f_SB2=6"  # salary filter: $100K+
            )
            r = safe_get(url, extra_headers={"Referer": "https://www.linkedin.com/"})
            if not r:
                time.sleep(2)
                continue
            soup = BeautifulSoup(r.text, "lxml")
            cards = soup.select("li.jobs-search__results-list > li")
            if not cards:
                cards = soup.select("div.job-search-card")
            for card in cards[:15]:
                title_el   = card.select_one("h3")
                company_el = card.select_one("h4")
                geo_el     = card.select_one(".job-search-card__location")
                a_el       = card.select_one("a[href]")
                title   = title_el.get_text(strip=True) if title_el else ""
                company = company_el.get_text(strip=True) if company_el else ""
                geo     = geo_el.get_text(strip=True) if geo_el else location
                href    = a_el.get("href", "") if a_el else ""
                desc    = f"{title} at {company}. {geo}. Executive leadership role."
                j = make_job(title, company, geo, desc, href, "LinkedIn")
                if j:
                    jobs.append(j)
            time.sleep(random.uniform(3, 5))
    logger.info(f"LinkedIn: {len(jobs)} validated matches")
    return jobs


# ── 4. Executive search firm listings ─────────────────────────────────────────

def fetch_exec_search_firms() -> list:
    """Scrape executive search firm job listing pages."""
    jobs = []
    firms = [
        {
            "name": "Korn Ferry",
            "url": "https://jobs.kornferry.com/search?q=chief+executive+officer+technology",
            "job_selector": "div.job-listing, li.job-result, article.job",
            "title_selector": "h2, h3, .job-title",
            "company_selector": ".company-name, .employer",
        },
        {
            "name": "Heidrick & Struggles",
            "url": "https://app.heidrick.com/candidate/search?searchQuery=chief+executive+officer",
            "job_selector": "div[class*='job'], li[class*='result']",
            "title_selector": "h2, h3, [class*='title']",
            "company_selector": "[class*='company'], [class*='employer']",
        },
        {
            "name": "Spencer Stuart",
            "url": "https://www.spencerstuart.com/who-we-are/careers/positions",
            "job_selector": "li, div.position, article",
            "title_selector": "h2, h3, a",
            "company_selector": None,
        },
        {
            "name": "Egon Zehnder",
            "url": "https://www.egonzehnder.com/functions/chief-executive-officer",
            "job_selector": "article, div.card, li.item",
            "title_selector": "h2, h3, [class*='title']",
            "company_selector": "[class*='company']",
        },
        {
            "name": "Russell Reynolds",
            "url": "https://www.russellreynolds.com/en/services/executive-search",
            "job_selector": "article, div[class*='job']",
            "title_selector": "h2, h3",
            "company_selector": None,
        },
        {
            "name": "The Ladders",
            "url": "https://www.theladders.com/jobs/search-jobs?title=chief+executive+officer&location=&salaryFrom=200000",
            "job_selector": "div[class*='job-list'], article[class*='job']",
            "title_selector": "h2 a, h3 a, [class*='title']",
            "company_selector": "[class*='company']",
        },
        {
            "name": "ExecThread",
            "url": "https://execthread.com/jobs",
            "job_selector": "div[class*='job'], li[class*='job']",
            "title_selector": "h2, h3, [class*='title']",
            "company_selector": "[class*='company']",
        },
    ]

    for firm in firms:
        r = safe_get(firm["url"])
        if not r:
            logger.debug(f"{firm['name']}: no response")
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, "lxml")

        # Try structured selectors first
        cards = soup.select(firm["job_selector"])
        if cards:
            for card in cards[:20]:
                title_el = card.select_one(firm["title_selector"])
                title = title_el.get_text(strip=True) if title_el else ""
                company = ""
                if firm["company_selector"]:
                    co_el = card.select_one(firm["company_selector"])
                    company = co_el.get_text(strip=True) if co_el else firm["name"]
                a = card.select_one("a[href]")
                href = urljoin(firm["url"], a.get("href", "")) if a else firm["url"]
                desc = f"{title}. Executive search mandate via {firm['name']}."
                j = make_job(title, company or firm["name"], "Global", desc, href, firm["name"])
                if j:
                    jobs.append(j)
        else:
            # Fallback: scan all links on the page
            for a in soup.find_all("a", href=True):
                title = a.get_text(strip=True)
                if not is_valid_title(title):
                    continue
                href = urljoin(firm["url"], a["href"])
                j = make_job(title, "Confidential", "Global",
                             f"{title}. Executive search via {firm['name']}.",
                             href, firm["name"])
                if j:
                    jobs.append(j)

        logger.debug(f"{firm['name']}: {len(jobs)} cumulative")
        time.sleep(random.uniform(2, 3))

    logger.info(f"Exec search firms: {len(jobs)} validated matches")
    return jobs


# ── 5. Microsoft Careers JSON API ─────────────────────────────────────────────

def fetch_microsoft() -> list:
    jobs = []
    for query in ["chief executive officer", "chief operating officer",
                  "executive vice president", "senior vice president global"]:
        url = (
            "https://gcsservices.careers.microsoft.com/search/api/v1/search"
            f"?q={quote(query)}&l=en_us&pg=1&pgSz=20&o=Recent&flt=true"
        )
        r = safe_get(url)
        if not r:
            continue
        try:
            data = r.json()
            for item in data.get("operationResult", {}).get("result", {}).get("jobs", []):
                title = item.get("title", "")
                loc   = item.get("properties", {}).get("primaryLocation", "Global")
                desc  = parse_text(item.get("properties", {}).get("description", ""))
                href  = f"https://careers.microsoft.com/us/en/job/{item.get('jobId','')}"
                j = make_job(title, "Microsoft", loc, desc, href, "Microsoft Careers")
                if j:
                    jobs.append(j)
        except Exception as e:
            logger.debug(f"Microsoft parse: {e}")
        time.sleep(0.5)
    logger.info(f"Microsoft: {len(jobs)} validated matches")
    return jobs


# ── 6. Amazon Jobs API ────────────────────────────────────────────────────────

def fetch_amazon() -> list:
    jobs = []
    for query in ["chief executive officer", "vice president global operations",
                  "managing director", "executive vice president"]:
        url = (
            "https://www.amazon.jobs/en/search.json"
            f"?result_limit=20&sort=recent&keywords={quote(query)}"
        )
        r = safe_get(url)
        if not r:
            continue
        try:
            for item in r.json().get("jobs", []):
                title = item.get("title", "")
                loc   = item.get("location", "Global")
                desc  = parse_text(item.get("description", ""))
                href  = "https://www.amazon.jobs" + item.get("job_path", "")
                j = make_job(title, "Amazon", loc, desc, href, "Amazon Jobs")
                if j:
                    jobs.append(j)
        except Exception as e:
            logger.debug(f"Amazon parse: {e}")
        time.sleep(0.5)
    logger.info(f"Amazon: {len(jobs)} validated matches")
    return jobs


# ── 7. IBM Careers API ────────────────────────────────────────────────────────

def fetch_ibm() -> list:
    jobs = []
    url = "https://careers.ibm.com/api/apply/v2/jobs?domain=ibm.com&start=0&limit=20&searchPhrase=vice+president"
    r = safe_get(url)
    if r:
        try:
            for item in r.json().get("jobs", []):
                title = item.get("title", "")
                city  = item.get("primaryCity", "")
                co    = item.get("primaryCountry", "")
                loc   = f"{city}, {co}".strip(", ")
                href  = f"https://careers.ibm.com/job/{item.get('id','')}"
                j = make_job(title, "IBM", loc or "Global",
                             f"{title} at IBM. Location: {loc}.", href, "IBM Careers")
                if j:
                    jobs.append(j)
        except Exception as e:
            logger.debug(f"IBM parse: {e}")
    logger.info(f"IBM: {len(jobs)} validated matches")
    return jobs


# ── 8. The Muse (exec category) ──────────────────────────────────────────────

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
            title   = item.get("name", "")
            company = item.get("company", {}).get("name", "")
            desc    = parse_text(item.get("contents", ""))
            locs    = item.get("locations", [])
            geo     = ", ".join(l.get("name", "") for l in locs) or "Global"
            href    = item.get("refs", {}).get("landing_page", "")
            j = make_job(title, company, geo, desc, href, "The Muse")
            if j and is_relevant(title, desc):
                jobs.append(j)
    except Exception as e:
        logger.debug(f"The Muse: {e}")
    logger.info(f"The Muse: {len(jobs)} validated matches")
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

    logger.info("── Adzuna (salary-filtered) ────────────────────")
    add(fetch_adzuna())

    logger.info("── JSearch (LinkedIn/Indeed/Glassdoor) ─────────")
    add(fetch_jsearch())

    logger.info("── LinkedIn Jobs (direct) ──────────────────────")
    add(fetch_linkedin())

    logger.info("── Executive search firms ──────────────────────")
    add(fetch_exec_search_firms())

    logger.info("── Microsoft Careers API ───────────────────────")
    add(fetch_microsoft())

    logger.info("── Amazon Jobs API ─────────────────────────────")
    add(fetch_amazon())

    logger.info("── IBM Careers API ─────────────────────────────")
    add(fetch_ibm())

    logger.info("── The Muse ────────────────────────────────────")
    add(fetch_the_muse())

    logger.info(f"Total raw jobs (pre-scoring dedup): {len(all_jobs)}")
    return all_jobs

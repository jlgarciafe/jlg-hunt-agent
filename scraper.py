"""
JLG Executive Job Hunt — Scraper
Sources:
  1. Adzuna API           — broad coverage with salary filter
  2. JSearch / RapidAPI  — aggregates LinkedIn + Indeed + Glassdoor (free tier)
  3. LinkedIn Jobs        — direct scraping with rotation
  4. Microsoft Careers    — JSON API
  5. IBM Careers          — JSON API
  6. Amazon Jobs          — JSON API
  7. Workday companies    — Nokia, Ericsson, Vodafone, Equinix, BP, Digital Realty
  8. Executive boards     — The Ladders, ExecThread, Exec-Appointments
  9. The Muse & Remotive  — supplementary
"""
import hashlib
import json
import logging
import time
import random
import requests
from bs4 import BeautifulSoup

from config import (
    ADZUNA_APP_ID, ADZUNA_APP_KEY, ADZUNA_COUNTRIES, ADZUNA_QUERIES,
    ADZUNA_MIN_SALARY, MAX_JOB_AGE_DAYS, RESULTS_PER_SOURCE,
    RAPIDAPI_KEY, JSEARCH_QUERIES, LINKEDIN_QUERIES, LINKEDIN_LOCATIONS,
    TARGET_COMPANIES, EXEC_BOARDS, TARGET_SECTORS, EXEC_TITLES,
)

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

def headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

# ── Helpers ───────────────────────────────────────────────────────────────────

def job_id(title: str, company: str, url: str = "") -> str:
    raw = f"{title.lower().strip()}|{company.lower().strip()}|{url}"
    return hashlib.md5(raw.encode()).hexdigest()

def is_exec_title(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in EXEC_TITLES)

def is_relevant(title: str, description: str) -> bool:
    text = (title + " " + description).lower()
    return any(s in text for s in TARGET_SECTORS)

def infer_sector(title: str, desc: str) -> str:
    t = (title + " " + desc).lower()
    if any(k in t for k in ["telecom","telecommunications","5g","wireless","network operator","carrier"]):
        return "Telecom"
    if any(k in t for k in ["data center","data centre","colocation","colo"]):
        return "Data Center"
    if any(k in t for k in ["artificial intelligence"," ai ","machine learning","llm","genai"]):
        return "AI / Machine Learning"
    if any(k in t for k in ["energy","utilities","power grid","renewable","oil and gas","grid","nuclear"]):
        return "Energy"
    if any(k in t for k in ["critical infrastructure","scada","industrial control","defense","defence"]):
        return "Critical Infrastructure"
    if any(k in t for k in ["cybersecurity","cyber security","information security"]):
        return "Technology"
    return "Technology"

def safe_get(url, timeout=15, extra_headers=None):
    h = headers()
    if extra_headers:
        h.update(extra_headers)
    try:
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        logger.debug(f"GET failed {url}: {e}")
        return None

def parse_text(html: str) -> str:
    return BeautifulSoup(html or "", "lxml").get_text(separator=" ")[:2000]


# ── 1. Adzuna API ─────────────────────────────────────────────────────────────

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
            # Add salary filter for US/UK
            if country in ["us", "gb"]:
                params["salary_min"] = ADZUNA_MIN_SALARY
            try:
                r = requests.get(url, params=params, timeout=15)
                r.raise_for_status()
                for item in r.json().get("results", []):
                    title   = item.get("title", "")
                    company = item.get("company", {}).get("display_name", "Unknown")
                    if not is_exec_title(title):
                        continue
                    desc = item.get("description", "")
                    loc  = item.get("location", {}).get("display_name", "")
                    href = item.get("redirect_url", "")
                    jobs.append({
                        "id": job_id(title, company, href),
                        "title": title, "company": company,
                        "geography": loc, "description": desc,
                        "url": href, "source": f"Adzuna ({country.upper()})",
                        "sector": infer_sector(title, desc),
                    })
            except Exception as e:
                logger.debug(f"Adzuna [{country}] '{query}': {e}")
            time.sleep(0.3)
    logger.info(f"Adzuna: {len(jobs)} executive matches")
    return jobs


# ── 2. JSearch (RapidAPI) — aggregates LinkedIn + Indeed + Glassdoor ──────────

def fetch_jsearch() -> list:
    if not RAPIDAPI_KEY:
        logger.info("RAPIDAPI_KEY not set — skipping JSearch (sign up free at rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)")
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
                if not is_exec_title(title):
                    continue
                desc = parse_text(item.get("job_description", ""))
                if not is_relevant(title, desc):
                    continue
                geo  = f"{item.get('job_city','')} {item.get('job_country','')}".strip() or "Global"
                href = item.get("job_apply_link", "") or item.get("job_google_link", "")
                jobs.append({
                    "id": job_id(title, company, href),
                    "title": title, "company": company,
                    "geography": geo, "description": desc,
                    "url": href, "source": f"JSearch ({item.get('job_publisher','LinkedIn/Indeed')})",
                    "sector": infer_sector(title, desc),
                })
            time.sleep(0.5)
        except Exception as e:
            logger.debug(f"JSearch '{query}': {e}")
    logger.info(f"JSearch: {len(jobs)} executive matches")
    return jobs


# ── 3. LinkedIn Jobs (direct scrape) ─────────────────────────────────────────

def fetch_linkedin() -> list:
    jobs = []
    for query in LINKEDIN_QUERIES[:5]:
        for location in LINKEDIN_LOCATIONS[:3]:
            url = (
                f"https://www.linkedin.com/jobs/search/?keywords={requests.utils.quote(query)}"
                f"&location={requests.utils.quote(location)}&f_TPR=r604800&f_JT=F"
                f"&sortBy=DD"
            )
            r = safe_get(url, extra_headers={"Referer": "https://www.linkedin.com/"})
            if not r:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for card in soup.select("li.jobs-search__results-list > li, div.job-search-card")[:10]:
                title   = (card.select_one("h3.base-search-card__title, h3") or {}).get_text(strip=True) if hasattr(card.select_one("h3"), 'get_text') else ""
                title   = card.select_one("h3") and card.select_one("h3").get_text(strip=True) or ""
                company = card.select_one("h4") and card.select_one("h4").get_text(strip=True) or ""
                geo     = card.select_one(".job-search-card__location") and card.select_one(".job-search-card__location").get_text(strip=True) or location
                href    = card.select_one("a") and card.select_one("a").get("href", "") or ""
                if not title or not is_exec_title(title):
                    continue
                jobs.append({
                    "id": job_id(title, company, href),
                    "title": title, "company": company,
                    "geography": geo, "description": f"{title} at {company}. Location: {geo}.",
                    "url": href, "source": "LinkedIn",
                    "sector": infer_sector(title, ""),
                })
            time.sleep(random.uniform(2, 4))  # polite delay to avoid blocks
    logger.info(f"LinkedIn: {len(jobs)} executive matches")
    return jobs


# ── 4. Microsoft Careers API ──────────────────────────────────────────────────

def fetch_microsoft() -> list:
    jobs = []
    for query in ["chief executive officer", "chief operating officer", "executive vice president", "senior vice president"]:
        url = (
            f"https://gcsservices.careers.microsoft.com/search/api/v1/search"
            f"?q={requests.utils.quote(query)}&l=en_us&pg=1&pgSz=20&o=Recent&flt=true"
        )
        r = safe_get(url)
        if not r:
            continue
        try:
            for item in r.json().get("operationResult", {}).get("result", {}).get("jobs", []):
                title   = item.get("title", "")
                if not is_exec_title(title):
                    continue
                loc  = item.get("properties", {}).get("primaryLocation", "Global")
                desc = item.get("properties", {}).get("description", "")[:2000]
                href = f"https://careers.microsoft.com/us/en/job/{item.get('jobId','')}"
                jobs.append({
                    "id": job_id(title, "Microsoft", href),
                    "title": title, "company": "Microsoft",
                    "geography": loc, "description": parse_text(desc),
                    "url": href, "source": "Microsoft Careers",
                    "sector": "Technology",
                })
        except Exception as e:
            logger.debug(f"Microsoft parse: {e}")
        time.sleep(0.5)
    logger.info(f"Microsoft: {len(jobs)} executive matches")
    return jobs


# ── 5. Amazon Jobs API ────────────────────────────────────────────────────────

def fetch_amazon() -> list:
    jobs = []
    for query in ["chief executive officer", "vice president global", "managing director"]:
        url = (
            f"https://www.amazon.jobs/en/search.json"
            f"?result_limit=20&sort=recent&keywords={requests.utils.quote(query)}"
        )
        r = safe_get(url)
        if not r:
            continue
        try:
            for item in r.json().get("jobs", []):
                title   = item.get("title", "")
                if not is_exec_title(title):
                    continue
                loc  = item.get("location", "Global")
                desc = parse_text(item.get("description", ""))
                href = "https://www.amazon.jobs" + item.get("job_path", "")
                jobs.append({
                    "id": job_id(title, "Amazon", href),
                    "title": title, "company": "Amazon",
                    "geography": loc, "description": desc,
                    "url": href, "source": "Amazon Jobs",
                    "sector": "Technology",
                })
        except Exception as e:
            logger.debug(f"Amazon parse: {e}")
        time.sleep(0.5)
    logger.info(f"Amazon: {len(jobs)} executive matches")
    return jobs


# ── 6. Workday company scraper ────────────────────────────────────────────────

def fetch_workday(company_name: str, workday_url: str) -> list:
    """Generic Workday job board scraper."""
    jobs = []
    r = safe_get(workday_url)
    if not r:
        return jobs
    try:
        soup = BeautifulSoup(r.text, "lxml")
        for item in soup.select("li[class*='job'], div[class*='job-card'], article"):
            title = item.get_text(strip=True)[:100]
            if not is_exec_title(title):
                continue
            href = ""
            a = item.select_one("a")
            if a:
                href = a.get("href", "")
                title = a.get_text(strip=True)[:100]
            if not is_exec_title(title):
                continue
            jobs.append({
                "id": job_id(title, company_name, href),
                "title": title, "company": company_name,
                "geography": "Global", "description": f"{title} position at {company_name}.",
                "url": href, "source": f"{company_name} Careers",
                "sector": infer_sector(title, ""),
            })
    except Exception as e:
        logger.debug(f"Workday {company_name}: {e}")
    return jobs


# ── 7. Target company career pages ────────────────────────────────────────────

def fetch_company_careers() -> list:
    jobs = []
    for co in TARGET_COMPANIES:
        name = co["name"]
        url  = co["careers_url"]
        ctype = co.get("type", "generic")
        try:
            if ctype == "microsoft":
                jobs.extend(fetch_microsoft())
                continue
            if ctype == "amazon":
                jobs.extend(fetch_amazon())
                continue
            if ctype == "ibm":
                r = safe_get(url)
                if r:
                    for item in r.json().get("jobs", []):
                        title = item.get("title", "")
                        if not is_exec_title(title):
                            continue
                        loc  = item.get("primaryCity", "") + ", " + item.get("primaryCountry", "")
                        href = f"https://careers.ibm.com/job/{item.get('id','')}"
                        jobs.append({
                            "id": job_id(title, "IBM", href),
                            "title": title, "company": "IBM",
                            "geography": loc, "description": f"{title} at IBM. {loc}",
                            "url": href, "source": "IBM Careers",
                            "sector": "Technology",
                        })
                continue
            if ctype == "workday":
                jobs.extend(fetch_workday(name, url))
                continue
            # Generic scrape
            r = safe_get(url)
            if not r:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all("a", href=True):
                title = a.get_text(strip=True)[:120]
                if not title or not is_exec_title(title):
                    continue
                href = a["href"]
                if not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
                jobs.append({
                    "id": job_id(title, name, href),
                    "title": title, "company": name,
                    "geography": "Global", "description": f"{title} at {name}.",
                    "url": href, "source": f"{name} Careers",
                    "sector": infer_sector(title, ""),
                })
        except Exception as e:
            logger.debug(f"Company careers {name}: {e}")
        time.sleep(random.uniform(1, 2))
    logger.info(f"Company career pages: {len(jobs)} executive matches")
    return jobs


# ── 8. Executive job boards ───────────────────────────────────────────────────

def fetch_exec_boards() -> list:
    jobs = []
    for board in EXEC_BOARDS:
        name = board["name"]
        url  = board["url"]
        r = safe_get(url)
        if not r:
            continue
        try:
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all("a", href=True):
                title = a.get_text(strip=True)[:120]
                if not title or len(title) < 10:
                    continue
                if not is_exec_title(title):
                    continue
                href = a["href"]
                if not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
                jobs.append({
                    "id": job_id(title, name, href),
                    "title": title, "company": "Confidential",
                    "geography": "Global", "description": f"{title}. Source: {name}.",
                    "url": href, "source": name,
                    "sector": infer_sector(title, ""),
                })
        except Exception as e:
            logger.debug(f"Exec board {name}: {e}")
        time.sleep(random.uniform(1, 2))
    logger.info(f"Executive boards: {len(jobs)} matches")
    return jobs


# ── 9. The Muse & Remotive (supplementary) ───────────────────────────────────

def fetch_the_muse() -> list:
    jobs = []
    try:
        r = requests.get("https://www.themuse.com/api/public/jobs",
                         params={"category": "Executive", "page": 0, "descending": True}, timeout=15)
        r.raise_for_status()
        for item in r.json().get("results", []):
            title   = item.get("name", "")
            company = item.get("company", {}).get("name", "")
            if not is_exec_title(title):
                continue
            desc    = parse_text(item.get("contents", ""))
            locs    = item.get("locations", [])
            geo     = ", ".join(l.get("name", "") for l in locs) or "Global"
            href    = item.get("refs", {}).get("landing_page", "")
            jobs.append({
                "id": job_id(title, company, href),
                "title": title, "company": company,
                "geography": geo, "description": desc,
                "url": href, "source": "The Muse",
                "sector": infer_sector(title, desc),
            })
    except Exception as e:
        logger.debug(f"The Muse: {e}")
    logger.info(f"The Muse: {len(jobs)} matches")
    return jobs


def fetch_remotive() -> list:
    jobs = []
    try:
        r = requests.get("https://remotive.com/api/remote-jobs",
                         params={"category": "management-finance", "limit": 100}, timeout=15)
        r.raise_for_status()
        for item in r.json().get("jobs", []):
            title   = item.get("title", "")
            company = item.get("company_name", "")
            if not is_exec_title(title):
                continue
            desc = parse_text(item.get("description", ""))
            if not is_relevant(title, desc):
                continue
            href = item.get("url", "")
            jobs.append({
                "id": job_id(title, company, href),
                "title": title, "company": company,
                "geography": "Remote / Global", "description": desc,
                "url": href, "source": "Remotive",
                "sector": infer_sector(title, desc),
            })
    except Exception as e:
        logger.debug(f"Remotive: {e}")
    logger.info(f"Remotive: {len(jobs)} matches")
    return jobs


# ── Master fetch ──────────────────────────────────────────────────────────────

def fetch_all_jobs() -> list:
    all_jobs = []
    seen_ids = set()

    def add(new_jobs):
        for j in new_jobs:
            jid = j.get("id")
            if jid and jid not in seen_ids:
                seen_ids.add(jid)
                all_jobs.append(j)

    logger.info("── Adzuna API ──────────────────────────────────")
    add(fetch_adzuna())

    logger.info("── JSearch (LinkedIn/Indeed aggregator) ────────")
    add(fetch_jsearch())

    logger.info("── LinkedIn Jobs (direct) ──────────────────────")
    add(fetch_linkedin())

    logger.info("── Company career pages ────────────────────────")
    add(fetch_company_careers())

    logger.info("── Executive job boards ────────────────────────")
    add(fetch_exec_boards())

    logger.info("── The Muse + Remotive ─────────────────────────")
    add(fetch_the_muse())
    add(fetch_remotive())

    logger.info(f"Total raw jobs fetched (pre-scoring dedup): {len(all_jobs)}")
    return all_jobs

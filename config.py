import os
from dotenv import load_dotenv

load_dotenv()

# ── Anthropic ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY")
SCORING_MODEL       = "claude-haiku-4-5-20251001"
OUTREACH_MODEL      = "claude-sonnet-4-6"

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL        = os.getenv("SUPABASE_URL")
SUPABASE_KEY        = os.getenv("SUPABASE_KEY")
SUPABASE_ANON_KEY   = os.getenv("SUPABASE_ANON_KEY")

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")

# ── Adzuna ────────────────────────────────────────────────────────────────────
ADZUNA_APP_ID       = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY      = os.getenv("ADZUNA_APP_KEY")

# ── RapidAPI / JSearch (free tier: 200 req/month — sign up at rapidapi.com) ──
RAPIDAPI_KEY        = os.getenv("RAPIDAPI_KEY", "")

# ── Scoring thresholds ────────────────────────────────────────────────────────
SCORE_ALERT_THRESHOLD    = 70
SCORE_PRIORITY_THRESHOLD = 85
SCORE_ARCHIVE_THRESHOLD  = 50

# ── Search parameters ─────────────────────────────────────────────────────────
MAX_JOB_AGE_DAYS    = 14    # cast wider net — 2 weeks
RESULTS_PER_SOURCE  = 50

# ── Adzuna: countries and salary filter ───────────────────────────────────────
ADZUNA_COUNTRIES = ["gb", "us", "de", "fr", "nl", "au", "sg", "ca"]
ADZUNA_MIN_SALARY = 150000   # USD equivalent — filters out junior roles

# ── Adzuna: focused executive queries ────────────────────────────────────────
ADZUNA_QUERIES = [
    "Chief Executive Officer technology",
    "Chief Executive Officer telecom",
    "Chief Executive Officer data center",
    "Chief Executive Officer energy",
    "Chief Operating Officer technology global",
    "Chief Operating Officer telecom global",
    "Executive Vice President technology",
    "Executive Vice President operations global",
    "Senior Vice President technology global",
    "Senior Vice President critical infrastructure",
    "President global technology operations",
    "Managing Director technology EMEA",
    "CEO digital transformation global",
    "COO managed services global",
    "Chief Transformation Officer technology",
]

# ── JSearch queries (aggregates LinkedIn + Indeed + Glassdoor) ────────────────
JSEARCH_QUERIES = [
    "CEO technology company global",
    "Chief Executive Officer telecom",
    "Chief Operating Officer technology",
    "EVP global operations technology",
    "SVP critical infrastructure",
    "President data center company",
    "CEO AI company global",
    "Managing Director technology EMEA",
]

# ── LinkedIn Jobs RSS / scrape queries ───────────────────────────────────────
LINKEDIN_QUERIES = [
    "Chief Executive Officer",
    "Chief Operating Officer",
    "Executive Vice President Technology",
    "SVP Global Operations",
    "President Global Technology",
]
LINKEDIN_LOCATIONS = ["Worldwide", "Europe", "United States", "United Kingdom", "Spain"]

# ── Target companies for direct career page scraping ─────────────────────────
TARGET_COMPANIES = [
    # Technology
    {"name": "Microsoft",     "careers_url": "https://gcsservices.careers.microsoft.com/search/api/v1/search?q=chief+executive+officer&l=en_us&pg=1&pgSz=20&o=Recent&flt=true", "type": "microsoft"},
    {"name": "IBM",           "careers_url": "https://careers.ibm.com/api/apply/v2/jobs?domain=ibm.com&start=0&limit=20&searchPhrase=chief+operating+officer&country=", "type": "ibm"},
    {"name": "Amazon",        "careers_url": "https://www.amazon.jobs/en/search.json?result_limit=20&sort=recent&keywords=chief+executive+officer", "type": "amazon"},
    {"name": "Cisco",         "careers_url": "https://jobs.cisco.com/jobs/SearchJobs/chief%20executive%20officer?21178=%5B169482%5D&21178_format=6020&listFilterMode=1&projectOffset=0", "type": "generic"},
    {"name": "SAP",           "careers_url": "https://jobs.sap.com/search/?createNewAlert=false&q=chief+operating+officer&locationsId=&optionsFacetsDD_department=&optionsFacetsDD_customfield3=&optionsFacetsDD_country=", "type": "generic"},
    {"name": "Accenture",     "careers_url": "https://www.accenture.com/api/accenture/careers/search?keywords=chief+executive+officer&start=0&end=20", "type": "generic"},
    {"name": "Dell",          "careers_url": "https://jobs.dell.com/api/apply/v2/jobs?domain=dell.com&start=0&limit=20&searchPhrase=vice+president", "type": "generic"},
    # Telecom
    {"name": "Vodafone",      "careers_url": "https://careers.vodafone.com/search/?q=chief+executive+officer&startrow=0", "type": "generic"},
    {"name": "Deutsche Telekom", "careers_url": "https://www.telekom.com/en/careers/job-offers?areasOfWork=Management+%26+Consulting&q=vice+president", "type": "generic"},
    {"name": "Telefonica",    "careers_url": "https://www.telefonica.com/en/careers/job-offers/?q=chief+officer", "type": "generic"},
    {"name": "Nokia",         "careers_url": "https://careers.nokia.com/jobs/search?page=1&query=vice+president", "type": "generic"},
    {"name": "Ericsson",      "careers_url": "https://jobs.ericsson.com/careers?query=vice+president+global", "type": "generic"},
    {"name": "Orange",        "careers_url": "https://careers.orange.com/en/jobs?q=director+general", "type": "generic"},
    # Data Centers
    {"name": "Equinix",       "careers_url": "https://equinix.wd1.myworkdayjobs.com/External/jobs?q=vice+president", "type": "workday"},
    {"name": "Digital Realty","careers_url": "https://digitalrealty.wd5.myworkdayjobs.com/External/jobs?q=vice+president", "type": "workday"},
    # Energy
    {"name": "Shell",         "careers_url": "https://www.shell.com/careers/search-and-apply.html?q=chief+officer", "type": "generic"},
    {"name": "BP",            "careers_url": "https://bp.wd3.myworkdayjobs.com/bpCareers/jobs?q=vice+president", "type": "workday"},
    {"name": "Iberdrola",     "careers_url": "https://jobs.iberdrola.com/en-US/search?q=director&location=", "type": "generic"},
    {"name": "TotalEnergies", "careers_url": "https://careers.totalenergies.com/en/our-job-offers?q=vice+president", "type": "generic"},
]

# ── Executive job boards to scrape ───────────────────────────────────────────
EXEC_BOARDS = [
    {
        "name": "The Ladders",
        "url":  "https://www.theladders.com/jobs/search-jobs?title=chief+executive+officer&location=",
        "type": "theladders",
    },
    {
        "name": "ExecThread",
        "url":  "https://execthread.com/jobs",
        "type": "execthread",
    },
    {
        "name": "Exec-Appointments",
        "url":  "https://www.exec-appointments.com/jobs/search/?keywords=chief+executive+officer&location=",
        "type": "generic",
    },
    {
        "name": "Harvey Nash",
        "url":  "https://www.harveynash.com/jobs?q=chief+executive+officer",
        "type": "generic",
    },
]

# ── Sector keywords for classification ───────────────────────────────────────
TARGET_SECTORS = [
    "telecom", "telecommunications", "5g", "wireless", "network operator",
    "technology", "software", "saas", "cloud", "digital",
    "data center", "data centre", "colocation", "colo", "infrastructure",
    "artificial intelligence", " ai ", "machine learning", "automation",
    "energy", "utilities", "power", "renewable", "oil and gas", "grid",
    "critical infrastructure", "scada", "defense", "defence",
    "managed services", "outsourcing", "digital transformation",
    "cybersecurity", "security",
]

# ── Title keywords that signal executive level ────────────────────────────────
EXEC_TITLES = [
    "chief executive", "ceo", "chief operating", "coo",
    "executive vice president", "evp", " evp ",
    "senior vice president", "svp", " svp ",
    "president", "managing director", "general manager",
    "chief transformation", "chief digital", "chief technology",
    "chief information", "chief revenue", "chief commercial",
    "group ceo", "group coo", "regional president",
    "country manager", "head of business",
]

# ── Tighter thresholds ────────────────────────────────────────────────────────
SCORE_ALERT_THRESHOLD    = 80   # raised from 70 — only genuinely strong matches
SCORE_PRIORITY_THRESHOLD = 90   # raised from 85
SCORE_ARCHIVE_THRESHOLD  = 60   # raised from 50 — stricter save filter

# ── Hard blacklist — reject any title containing these strings ────────────────
TITLE_BLACKLIST = [
    "cookie", "privacy", "terms", "login", "sign in", "sign up",
    "newsletter", "subscribe", "legal", "disclaimer", "sitemap",
    "accessibility", "contact us", "about us", "home", "back to",
    "search results", "loading", "javascript", "404", "error",
    "warehouse", "coordinator", "associate", "analyst", "intern",
    "junior", "entry level", "assistant", "administrator",
    "specialist", "technician", "engineer", "developer", "consultant",
]

# ── Minimum title quality ─────────────────────────────────────────────────────
MIN_TITLE_LENGTH = 15    # "CEO" alone isn't a title — needs company context
MAX_TITLE_LENGTH = 120

# ── Compensation filters (where APIs support it) ──────────────────────────────
MIN_SALARY_USD   = 200000   # $200K minimum — C-suite / SVP floor

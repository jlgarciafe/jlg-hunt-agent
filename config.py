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

# ── RapidAPI / JSearch ────────────────────────────────────────────────────────
RAPIDAPI_KEY        = os.getenv("RAPIDAPI_KEY", "")

# ── Scoring thresholds ────────────────────────────────────────────────────────
SCORE_ALERT_THRESHOLD    = 80
SCORE_PRIORITY_THRESHOLD = 90
SCORE_ARCHIVE_THRESHOLD  = 60

# ── Search parameters ─────────────────────────────────────────────────────────
MAX_JOB_AGE_DAYS    = 14

# ── Adzuna: NO salary filter — most exec roles don't advertise salary ─────────
# Rely on title filtering and scoring instead
ADZUNA_COUNTRIES = ["gb", "us", "de", "fr", "nl", "au", "sg", "ca"]

ADZUNA_QUERIES = [
    "Chief Executive Officer technology",
    "Chief Executive Officer telecom",
    "Chief Executive Officer data center",
    "Chief Executive Officer energy",
    "Chief Executive Officer digital transformation",
    "Chief Operating Officer global technology",
    "Chief Operating Officer telecom",
    "Executive Vice President technology global",
    "Executive Vice President operations",
    "Senior Vice President technology global",
    "Senior Vice President critical infrastructure",
    "President global technology",
    "Managing Director technology EMEA",
    "CEO digital transformation",
    "COO managed services global",
    "Chief Transformation Officer",
    "Chief Digital Officer global",
    "Group Chief Executive technology",
    "Regional President technology",
    "Head of Global Operations technology",
]

# ── JSearch queries (LinkedIn + Indeed + Glassdoor aggregator) ────────────────
JSEARCH_QUERIES = [
    "CEO technology company $5B",
    "Chief Executive Officer telecommunications global",
    "Chief Operating Officer technology global",
    "Executive Vice President global operations technology",
    "SVP critical infrastructure global",
    "President data center company",
    "CEO AI company global",
    "Managing Director technology EMEA global",
    "Chief Executive Officer energy company",
    "COO digital transformation global",
    "Group CEO technology listed company",
    "Chief Executive Officer managed services",
]

# ── LinkedIn direct queries ───────────────────────────────────────────────────
LINKEDIN_QUERIES = [
    "Chief Executive Officer",
    "Chief Operating Officer global",
    "Executive Vice President Technology",
    "SVP Global Operations",
    "President Global Technology",
    "Managing Director EMEA Technology",
]
LINKEDIN_LOCATIONS = ["Worldwide", "Europe", "United States", "United Kingdom"]

# ── Reed.co.uk API (free, reliable UK + international exec roles) ─────────────
REED_QUERIES = [
    "chief executive officer",
    "chief operating officer",
    "executive vice president",
    "managing director technology",
]

# ── Remotive API queries ──────────────────────────────────────────────────────
REMOTIVE_CATEGORIES = ["management-finance", "business"]

# ── Title blacklist — reject any title containing these strings ───────────────
TITLE_BLACKLIST = [
    "cookie", "privacy", "terms", "login", "sign in", "sign up",
    "newsletter", "subscribe", "legal", "disclaimer", "sitemap",
    "accessibility", "contact us", "about us", "home", "back to",
    "search results", "loading", "javascript", "404", "error",
    "warehouse", "coordinator", "associate", "analyst", "intern",
    "junior", "entry level", "assistant", "administrator",
    "specialist", "technician", "developer", "consultant",
    "recruiter", "talent", "hr ", "human resources",
    "graduate", "apprentice", "trainee",
]

# ── Executive title keywords ──────────────────────────────────────────────────
EXEC_TITLES = [
    "chief executive", "ceo", "chief operating", "coo",
    "executive vice president", "evp",
    "senior vice president", "svp",
    "president", "managing director", "general manager",
    "chief transformation", "chief digital", "chief technology",
    "chief information", "chief revenue", "chief commercial",
    "group ceo", "group coo", "regional president",
    "head of global", "group president",
]

# ── Sector keywords ───────────────────────────────────────────────────────────
TARGET_SECTORS = [
    "telecom", "telecommunications", "5g", "wireless", "network operator",
    "technology", "software", "saas", "cloud", "digital",
    "data center", "data centre", "colocation", "colo", "infrastructure",
    "artificial intelligence", " ai ", "machine learning", "automation",
    "energy", "utilities", "power", "renewable", "oil and gas", "grid",
    "critical infrastructure", "scada", "defense", "defence",
    "managed services", "outsourcing", "digital transformation",
    "cybersecurity", "security", "fintech", "media",
]

# ── Title length constraints ──────────────────────────────────────────────────
MIN_TITLE_LENGTH = 10
MAX_TITLE_LENGTH = 120

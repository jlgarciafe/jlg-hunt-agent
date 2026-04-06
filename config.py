import os
from dotenv import load_dotenv

load_dotenv()

# ── Anthropic ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY")
SCORING_MODEL       = "claude-haiku-4-5-20251001"   # fast + cheap for daily scoring
OUTREACH_MODEL      = "claude-sonnet-4-6"           # better quality for outreach drafts

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL        = os.getenv("SUPABASE_URL")
SUPABASE_KEY        = os.getenv("SUPABASE_KEY")          # service role key (server-side)
SUPABASE_ANON_KEY   = os.getenv("SUPABASE_ANON_KEY")     # anon key (dashboard read)

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")      # your personal chat ID

# ── Adzuna ────────────────────────────────────────────────────────────────────
ADZUNA_APP_ID       = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY      = os.getenv("ADZUNA_APP_KEY")

# ── Scoring thresholds ────────────────────────────────────────────────────────
SCORE_ALERT_THRESHOLD    = 70   # Telegram ping
SCORE_PRIORITY_THRESHOLD = 85   # Priority flag in dashboard
SCORE_ARCHIVE_THRESHOLD  = 50   # Below this: auto-archive, never shown

# ── Search parameters ─────────────────────────────────────────────────────────
MAX_JOB_AGE_DAYS    = 7         # Only fetch roles posted in last 7 days
RESULTS_PER_SOURCE  = 50        # Max results per search query

# ── Adzuna countries to search ────────────────────────────────────────────────
ADZUNA_COUNTRIES = ["gb", "us", "de", "fr", "nl", "au", "ca", "sg"]

# ── Search queries ────────────────────────────────────────────────────────────
SEARCH_QUERIES = [
    "chief executive officer telecom",
    "chief executive officer technology",
    "chief executive officer data center",
    "chief executive officer energy",
    "chief executive officer AI",
    "chief operating officer telecom",
    "chief operating officer technology",
    "chief operating officer global",
    "executive vice president telecom",
    "executive vice president technology",
    "executive vice president operations",
    "senior vice president technology global",
    "senior vice president critical infrastructure",
    "managing director global technology",
    "president global operations technology",
    "CEO digital transformation",
    "COO managed services global",
]

# ── Target sectors (for sector scoring) ──────────────────────────────────────
TARGET_SECTORS = [
    "telecom", "telecommunications", "technology", "tech",
    "data center", "data centre", "cloud", "AI", "artificial intelligence",
    "energy", "utilities", "critical infrastructure", "cybersecurity",
    "digital transformation", "managed services", "SaaS",
]

# ── Minimum company keywords (to filter small companies) ─────────────────────
COMPANY_SIZE_KEYWORDS = [
    "global", "international", "worldwide", "multinational",
    "listed", "public company", "fortune", "ftse",
]

# ── Executive search firm URLs to scrape ─────────────────────────────────────
EXEC_SEARCH_SOURCES = [
    {
        "name": "Korn Ferry",
        "url": "https://jobs.kornferry.com/search?q=chief+executive+officer+technology&l=&remote=",
        "type": "korn_ferry",
    },
    {
        "name": "Heidrick & Struggles",
        "url": "https://www.heidrick.com/en/about-us/careers",
        "type": "heidrick",
    },
]

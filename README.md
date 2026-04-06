# JLG Executive Job Hunt Agent

Automated daily search for CEO/COO/EVP/SVP roles at $5B+ companies
in Telecom, Technology, Data Centers, AI, and Energy.

## Architecture

```
GitHub Actions (daily 07:00 Madrid)
    │
    ▼
agent.py
    ├── scraper.py    → Adzuna API + The Muse + Remotive
    ├── scorer.py     → Claude API (scores 0–100, recommends CV version, drafts outreach)
    ├── database.py   → Supabase (persistent storage)
    └── notifier.py   → Telegram (instant alerts for score ≥70)
```

## One-time Setup (≈15 minutes)

### Step 1 — Get API credentials (all free)

| Service | Where to register | What you need |
|---------|-------------------|---------------|
| Anthropic | console.anthropic.com | API key |
| Supabase | supabase.com | Project URL + service_role key + anon key |
| Telegram Bot | Message @BotFather on Telegram → /newbot | Bot token + your Chat ID |
| Adzuna | developer.adzuna.com/signup | App ID + App Key |

**Finding your Telegram Chat ID:**
Message `@userinfobot` on Telegram and it will reply with your ID.

---

### Step 2 — Set up Supabase database

1. Go to supabase.com → New project → create free project
2. Go to SQL Editor → paste and run the SQL from `database.py` (the `SCHEMA_SQL` variable)
3. Copy your Project URL and both API keys (service_role and anon)

---

### Step 3 — Create GitHub repository

```bash
git init job_hunt_agent
cd job_hunt_agent
# copy all files into this directory
git add .
git commit -m "Initial setup"
git remote add origin https://github.com/YOUR_USERNAME/job-hunt-agent
git push -u origin main
```

---

### Step 4 — Add GitHub Secrets

Go to your GitHub repo → Settings → Secrets and variables → Actions → New repository secret

Add each of these:
- `ANTHROPIC_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_ANON_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `ADZUNA_APP_ID`
- `ADZUNA_APP_KEY`

---

### Step 5 — Test locally

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in .env
cp .env.example .env
# Edit .env with your credentials

# Test Telegram connection
python agent.py --test

# Dry run (score jobs, don't save)
python agent.py --dry-run

# Full live run
python agent.py
```

---

### Step 6 — Trigger first GitHub Actions run

Go to your repo → Actions → JLG Daily Job Hunt → Run workflow

After the first run, it will run automatically every day at 07:00 Madrid time.

---

## Dashboard

The in-chat Claude dashboard works standalone using browser storage.

To connect it to Supabase (so it shows agent-sourced jobs automatically):
- Use the `SUPABASE_ANON_KEY` and `SUPABASE_URL` in the dashboard fetch calls
- Tell Claude: "Connect the dashboard to Supabase" and it will update the artifact

---

## Customisation

### Add/remove search queries
Edit `SEARCH_QUERIES` in `config.py`

### Change scoring thresholds
Edit in `config.py`:
- `SCORE_ALERT_THRESHOLD` (default 70) — triggers Telegram alert
- `SCORE_PRIORITY_THRESHOLD` (default 85) — marks as priority
- `SCORE_ARCHIVE_THRESHOLD` (default 50) — below this, job is not saved

### Change search countries
Edit `ADZUNA_COUNTRIES` in `config.py`

### Change run schedule
Edit the cron expression in `.github/workflows/daily_hunt.yml`
Format: `"minute hour * * *"` — current `"0 5 * * *"` = 05:00 UTC = 07:00 Madrid CEST

---

## Costs

| Service | Cost |
|---------|------|
| GitHub Actions | Free (2,000 min/month — agent uses ~5 min/day) |
| Supabase | Free tier (500MB — sufficient for thousands of jobs) |
| Telegram Bot API | Free |
| Adzuna API | Free (250 requests/day) |
| Anthropic API | ~€0.10–0.30/day (haiku for scoring, sonnet for outreach) |

**Total: ~€3–9/month** (Anthropic API only)

---

## Upgrade path

When free sources are validated and you want broader coverage:
1. Sign up for SerpAPI (~€50/month) → uncomment Google Jobs scraper
2. Add LinkedIn scraper with your account cookies (optional, fragile)
3. Add Indeed scraper (also fragile, use SerpAPI instead)

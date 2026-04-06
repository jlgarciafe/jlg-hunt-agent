import json
import logging
import anthropic
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import ANTHROPIC_API_KEY, SCORING_MODEL, OUTREACH_MODEL
from cv_profile import CV_SUMMARY

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Concurrency limits — tuned to stay within Anthropic rate limits
SCORE_WORKERS   = 10   # Haiku is fast and cheap; 10 concurrent calls is safe
OUTREACH_WORKERS = 3   # Sonnet is slower; keep lower to avoid rate limiting

SCORING_SYSTEM = (
    "You are a JSON-only API. Respond with ONLY valid JSON. "
    "No markdown, no code fences, no explanation. Raw JSON only."
)

OUTREACH_SYSTEM = (
    "You are an expert executive career advisor writing outreach emails."
)


def build_scoring_prompt(title, company, geography, description):
    """Build scoring prompt using concatenation to avoid .format() brace conflicts."""
    return (
        "Score this executive job opportunity for the candidate below.\n\n"
        "CANDIDATE:\n" + CV_SUMMARY + "\n\n"
        "JOB:\n"
        "Title: " + title + "\n"
        "Company: " + company + "\n"
        "Geography: " + geography + "\n"
        "Description: " + description[:2000] + "\n\n"
        "Return a JSON object with EXACTLY these keys and types:\n"
        "- sectorFit: integer 0-20 (20=Telecom/Tech/DataCenter/AI/Energy/CritInfra, 12-18=Adjacent, 0-10=Unrelated)\n"
        "- titleSeniority: integer 0-20 (20=CEO/President, 17-19=COO/EVP, 14-16=SVP/MD global, 0-10=VP or below)\n"
        "- companyType: integer 0-20 (20=Listed $5B+, 17-19=Large PE/VC-backed, 10-14=Large unclear, 0-8=SMB)\n"
        "- scope: integer 0-20 (20=Global multi-continent, 15-18=Multi-country, 8-12=Single country, 0-6=Local)\n"
        "- skillsMatch: integer 0-20 (P&L at scale/transformation/M&A/critical infra/managed services/AI)\n"
        "- totalScore: integer (sum of above five)\n"
        '- cvVersion: string, either "Corporate / Listed Co." or "PE Operating Partner"\n'
        "- rationale: string, one sentence explaining fit\n"
        "- shouldDraftOutreach: boolean, true only if totalScore >= 70\n\n"
        "Respond with raw JSON only, no other text."
    )


def build_outreach_prompt(title, company, geography, description_excerpt):
    return (
        "Draft a concise, warm, professional outreach email.\n\n"
        "CANDIDATE: Joseluis Garcia\n"
        "- COO Telus Digital: $3B P&L, 32 countries, 70,000 people (EQT PE-backed)\n"
        "- EY Global Managing Partner: $5B managed services, $250M EBITDA expansion\n"
        "- Nokia President: $520M EBITDA uplift, Motorola acquisition $2.5B revenue\n"
        "- Critical infrastructure: NATO backbone, GSM-R railways, SCADA energy grids\n"
        "- Base: Madrid | Global | English/Spanish/Portuguese\n\n"
        "ROLE: " + title + " at " + company + "\n"
        "GEOGRAPHY: " + geography + "\n"
        "CONTEXT: " + description_excerpt + "\n\n"
        "Write 3 short paragraphs:\n"
        "1. Why this role resonates personally (connect to company mission/sector)\n"
        "2. Two concrete credentials with numbers that directly match\n"
        "3. Warm close inviting a conversation\n\n"
        "Under 180 words. Confident, direct, warm tone. "
        "Do NOT start with 'I am writing to'."
    )


def score_job(job: dict) -> dict:
    prompt = build_scoring_prompt(
        title       = job.get("title", ""),
        company     = job.get("company", ""),
        geography   = job.get("geography", ""),
        description = job.get("description", ""),
    )

    try:
        message = client.messages.create(
            model      = SCORING_MODEL,
            max_tokens = 512,
            system     = SCORING_SYSTEM,
            messages   = [{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # Strip markdown fences if present
        raw = raw.replace("```json", "").replace("```", "").strip()

        # Extract JSON object
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        result = json.loads(raw)

        dims = ["sectorFit", "titleSeniority", "companyType", "scope", "skillsMatch"]
        for d in dims:
            result[d] = max(0, min(20, int(result.get(d, 0))))
        result["totalScore"] = sum(result[d] for d in dims)

        logger.info(
            f"Scored: {job.get('title')} @ {job.get('company')} "
            f"-> {result['totalScore']}/100  [{result.get('rationale', '')}]"
        )

        return {
            **job,
            "score":               result["totalScore"],
            "cvVersion":           result.get("cvVersion", "Corporate / Listed Co."),
            "scoringRationale":    result.get("rationale", ""),
            "scoringBreakdown":    {d: result[d] for d in dims},
            "shouldDraftOutreach": bool(result.get("shouldDraftOutreach", False)),
            "outreachDraft":       "",
        }

    except Exception as e:
        logger.error(f"Scoring error for {job.get('title')}: {e}")
        return {
            **job,
            "score": 0,
            "cvVersion": "Corporate / Listed Co.",
            "scoringRationale": f"Scoring failed: {e}",
            "scoringBreakdown": {},
            "shouldDraftOutreach": False,
            "outreachDraft": "",
        }


def draft_outreach(job: dict) -> str:
    prompt = build_outreach_prompt(
        title               = job.get("title", ""),
        company             = job.get("company", ""),
        geography           = job.get("geography", ""),
        description_excerpt = job.get("description", "")[:600],
    )
    try:
        message = client.messages.create(
            model      = OUTREACH_MODEL,
            max_tokens = 400,
            system     = OUTREACH_SYSTEM,
            messages   = [{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"Outreach draft error: {e}")
        return ""


def score_jobs_batch(jobs: list) -> list:
    """Score all jobs in parallel, then draft outreach for high-scorers in parallel."""
    total = len(jobs)
    scored = [None] * total  # preserve original order

    # ── Phase 1: parallel scoring (Haiku) ─────────────────────────────────────
    logger.info(f"Scoring {total} jobs with up to {SCORE_WORKERS} parallel workers...")
    with ThreadPoolExecutor(max_workers=SCORE_WORKERS) as pool:
        future_to_idx = {
            pool.submit(score_job, job): i
            for i, job in enumerate(jobs)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                scored[idx] = future.result()
            except Exception as e:
                logger.error(f"Scoring thread failed for job index {idx}: {e}")
                scored[idx] = {**jobs[idx], "score": 0, "cvVersion": "Corporate / Listed Co.",
                               "scoringRationale": f"Scoring failed: {e}",
                               "scoringBreakdown": {}, "shouldDraftOutreach": False,
                               "outreachDraft": ""}

    # ── Phase 2: parallel outreach drafting (Sonnet) for high-scorers ─────────
    needs_outreach = [
        (i, j) for i, j in enumerate(scored)
        if j and j.get("shouldDraftOutreach") and j.get("score", 0) >= 70
    ]
    if needs_outreach:
        logger.info(f"Drafting outreach for {len(needs_outreach)} high-score roles "
                    f"with up to {OUTREACH_WORKERS} parallel workers...")
        with ThreadPoolExecutor(max_workers=OUTREACH_WORKERS) as pool:
            future_to_idx = {
                pool.submit(draft_outreach, job): i
                for i, job in needs_outreach
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    scored[idx]["outreachDraft"] = future.result()
                except Exception as e:
                    logger.error(f"Outreach draft thread failed for index {idx}: {e}")
                    scored[idx]["outreachDraft"] = ""

    return scored

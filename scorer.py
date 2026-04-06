import json
import logging
import anthropic
from config import ANTHROPIC_API_KEY, SCORING_MODEL, OUTREACH_MODEL
from cv_profile import CV_SUMMARY

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Prompts ───────────────────────────────────────────────────────────────────
# NOTE: JSON example uses << >> instead of {{ }} to avoid Python format conflicts.
# The model is instructed to use standard braces in its response.

SCORING_SYSTEM = (
    "You are a JSON-only API. Respond with ONLY valid JSON — no markdown, "
    "no code fences, no explanation, no text before or after. "
    "Use standard JSON with double-quoted keys and values."
)

SCORING_TEMPLATE = (
    "Score this executive job opportunity for the candidate below.\n\n"
    "CANDIDATE:\n{cv_profile}\n\n"
    "JOB:\nTitle: {title}\nCompany: {company}\nGeography: {geography}\n"
    "Description: {description}\n\n"
    "Return ONLY a JSON object with exactly these keys:\n"
    "sectorFit (0-20): 20=Telecom/Tech/DataCenter/AI/Energy/CriticalInfra, 12-18=Adjacent digital, 0-10=Unrelated\n"
    "titleSeniority (0-20): 20=CEO/President, 17-19=COO/EVP, 14-16=SVP/MD global, 0-10=VP or below\n"
    "companyType (0-20): 20=Listed $5B+, 17-19=Large PE/VC-backed, 10-14=Large unclear, 0-8=SMB/startup\n"
    "scope (0-20): 20=Global multi-continent, 15-18=Multi-country regional, 8-12=Single country, 0-6=Local\n"
    "skillsMatch (0-20): How well role needs P&L scale/transformation/M&A/critical infra/managed services/AI\n"
    "totalScore (integer): sum of all five scores\n"
    'cvVersion (string): either "Corporate / Listed Co." or "PE Operating Partner"\n'
    "rationale (string): one sentence on fit\n"
    "shouldDraftOutreach (boolean): true only if totalScore >= 70\n\n"
    "Respond with JSON only. Example structure:\n"
    '{"sectorFit":18,"titleSeniority":20,"companyType":20,"scope":20,"skillsMatch":16,'
    '"totalScore":94,"cvVersion":"Corporate / Listed Co.","rationale":"Strong fit.",'
    '"shouldDraftOutreach":true}'
)

OUTREACH_TEMPLATE = (
    "Draft a concise, warm, professional outreach email.\n\n"
    "CANDIDATE: Joseluis Garcia\n"
    "- COO Telus Digital: $3B P&L, 32 countries, 70,000 people (EQT PE-backed)\n"
    "- EY Global Managing Partner: $5B managed services, $250M EBITDA expansion\n"
    "- Nokia President Global Service Delivery: $520M EBITDA uplift, Motorola acquisition $2.5B\n"
    "- Critical infrastructure: NATO backbone, GSM-R railways, SCADA energy grids\n"
    "- Base: Madrid | Global | English/Spanish/Portuguese\n\n"
    "ROLE: {title} at {company}\n"
    "GEOGRAPHY: {geography}\n"
    "CONTEXT: {description_excerpt}\n\n"
    "Write 3 short paragraphs: (1) why this role resonates personally, "
    "(2) two concrete credentials with numbers that match, "
    "(3) warm close. Under 180 words. Confident, direct, warm. "
    "Do NOT start with 'I am writing to'."
)


# ── Core functions ────────────────────────────────────────────────────────────

def score_job(job: dict) -> dict:
    prompt = SCORING_TEMPLATE.format(
        cv_profile  = CV_SUMMARY,
        title       = job.get("title", ""),
        company     = job.get("company", ""),
        geography   = job.get("geography", ""),
        description = job.get("description", "")[:2000],
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

        # Find the JSON object
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
            f"-> {result['totalScore']}/100  [{result.get('rationale','')}]"
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
            "score": 0, "cvVersion": "Corporate / Listed Co.",
            "scoringRationale": f"Scoring failed: {e}",
            "scoringBreakdown": {}, "shouldDraftOutreach": False, "outreachDraft": "",
        }


def draft_outreach(job: dict) -> str:
    prompt = OUTREACH_TEMPLATE.format(
        title              = job.get("title", ""),
        company            = job.get("company", ""),
        geography          = job.get("geography", ""),
        description_excerpt= job.get("description", "")[:600],
    )
    try:
        message = client.messages.create(
            model      = OUTREACH_MODEL,
            max_tokens = 400,
            messages   = [{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"Outreach draft error: {e}")
        return ""


def score_jobs_batch(jobs: list) -> list:
    scored = []
    for i, job in enumerate(jobs, 1):
        logger.info(f"Scoring {i}/{len(jobs)}: {job.get('title')} @ {job.get('company')}")
        enriched = score_job(job)
        if enriched.get("shouldDraftOutreach") and enriched.get("score", 0) >= 70:
            enriched["outreachDraft"] = draft_outreach(enriched)
        scored.append(enriched)
    return scored

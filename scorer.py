import json
import logging
import anthropic
from config import ANTHROPIC_API_KEY, SCORING_MODEL, OUTREACH_MODEL
from cv_profile import CV_SUMMARY

logger   = logging.getLogger(__name__)
client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Scoring prompt ────────────────────────────────────────────────────────────

SCORING_PROMPT = """\
You are an executive career advisor scoring job opportunities for a specific candidate.

CANDIDATE PROFILE:
{cv_profile}

JOB OPPORTUNITY:
Title: {title}
Company: {company}
Geography: {geography}
Description:
{description}

Score this opportunity on 5 dimensions (0–20 each). Be strict and realistic.

1. SECTOR FIT (0–20)
   20 = Telecom, Technology, Data Centre, AI, Energy, Critical Infrastructure
   12–18 = Adjacent digital/industrial sector
   0–10 = Unrelated sector

2. TITLE SENIORITY (0–20)
   20 = CEO, President
   17–20 = COO, EVP
   14–17 = SVP, MD with global scope
   0–10 = VP or below, regional only

3. COMPANY TYPE (0–20)
   20 = Listed company, revenue clearly $5B+
   17–20 = Large PE/VC-backed, institutional scale
   10–15 = Large but unclear ownership or size
   0–8 = SMB, startup, or small company

4. SCOPE (0–20)
   20 = Explicitly global, multi-continent mandate
   15–18 = Multi-country regional (EMEA, Americas etc.)
   8–12 = Single large country
   0–6 = Local or city-level

5. SKILLS MATCH (0–20)
   Score how well the role requires: P&L ownership at scale, transformation,
   M&A integration, critical infrastructure, managed services, AI/digital,
   multi-country teams. Penalise heavily if specialist skills not in candidate profile.

ALSO DETERMINE:
- CV_VERSION: Which CV fits better?
  "Corporate / Listed Co." = for listed companies, transformation mandates
  "PE Operating Partner" = for PE/VC-backed companies, turnaround/value creation

- RATIONALE: One sharp sentence explaining the score (what matches, what doesn't)

- SHOULD_DRAFT_OUTREACH: true only if totalScore >= 70

Respond ONLY with valid JSON. No preamble, no markdown, no explanation:
{{
  "sectorFit": <0-20>,
  "titleSeniority": <0-20>,
  "companyType": <0-20>,
  "scope": <0-20>,
  "skillsMatch": <0-20>,
  "totalScore": <integer sum of above>,
  "cvVersion": "<Corporate / Listed Co. or PE Operating Partner>",
  "rationale": "<one sentence>",
  "shouldDraftOutreach": <true or false>
}}"""

# ── Outreach prompt ───────────────────────────────────────────────────────────

OUTREACH_PROMPT = """\
Draft a concise, warm, professional outreach email for this executive job opportunity.

CANDIDATE: Jose-Luis Garcia
- 30+ year global executive (Nokia, EY, Telus Digital, Dell, Ericsson)
- COO, Telus Digital: $3B P&L, 32 countries, 70,000 people
- Deep expertise: critical infrastructure, AI transformation, M&A integration
- Board experience: Europe, Asia, Americas
- Base: Madrid, open globally
- Languages: English (bilingual), Spanish (native), Portuguese

ROLE: {title} at {company}
GEOGRAPHY: {geography}
KEY CONTEXT: {description_excerpt}

Write exactly 3 short paragraphs:
1. Why this specific role resonates (connect to company mission/sector, not generic)
2. Two concrete credentials that directly match this mandate (specific numbers)
3. Warm close inviting a conversation

Tone: Confident, direct, warm — not formal or stiff. Under 180 words total.
Do NOT use: "I am writing to", "please find", "I believe I would be", filler phrases.
Start with something that hooks the reader immediately."""


# ── Main scoring function ─────────────────────────────────────────────────────

def score_job(job: dict) -> dict:
    """
    Score a job against the candidate profile using Claude.
    Returns enriched job dict with score, breakdown, cv version, rationale.
    """
    title       = job.get("title", "")
    company     = job.get("company", "")
    geography   = job.get("geography", "")
    description = job.get("description", "")[:3000]  # cap at 3k chars for haiku

    prompt = SCORING_PROMPT.format(
        cv_profile  = CV_SUMMARY,
        title       = title,
        company     = company,
        geography   = geography,
        description = description,
    )

    try:
        message = client.messages.create(
            model     = SCORING_MODEL,
            max_tokens= 512,
            messages  = [{"role": "user", "content": prompt}],
        )
        raw    = message.content[0].text.strip()
        result = json.loads(raw)

        # Validate and clamp
        dims = ["sectorFit", "titleSeniority", "companyType", "scope", "skillsMatch"]
        for d in dims:
            result[d] = max(0, min(20, int(result.get(d, 0))))
        result["totalScore"] = sum(result[d] for d in dims)

        enriched = {
            **job,
            "score":              result["totalScore"],
            "cvVersion":          result.get("cvVersion", "Corporate / Listed Co."),
            "scoringRationale":   result.get("rationale", ""),
            "scoringBreakdown":   {d: result[d] for d in dims},
            "shouldDraftOutreach":result.get("shouldDraftOutreach", False),
        }

        logger.info(f"Scored: {title} @ {company} → {result['totalScore']}/100  [{result.get('rationale','')}]")
        return enriched

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error scoring {title}: {e}")
        return {**job, "score": 0, "cvVersion": "Corporate / Listed Co.",
                "scoringRationale": "Scoring failed — JSON parse error",
                "scoringBreakdown": {}, "shouldDraftOutreach": False}
    except Exception as e:
        logger.error(f"Scoring error for {title}: {e}")
        return {**job, "score": 0, "cvVersion": "Corporate / Listed Co.",
                "scoringRationale": "Scoring failed",
                "scoringBreakdown": {}, "shouldDraftOutreach": False}


# ── Outreach draft function ───────────────────────────────────────────────────

def draft_outreach(job: dict) -> str:
    """Generate a tailored outreach email draft for a high-scoring job."""
    title             = job.get("title", "")
    company           = job.get("company", "")
    geography         = job.get("geography", "")
    description_excerpt = job.get("description", "")[:600]

    prompt = OUTREACH_PROMPT.format(
        title              = title,
        company            = company,
        geography          = geography,
        description_excerpt= description_excerpt,
    )

    try:
        message = client.messages.create(
            model     = OUTREACH_MODEL,
            max_tokens= 400,
            messages  = [{"role": "user", "content": prompt}],
        )
        draft = message.content[0].text.strip()
        logger.info(f"Outreach draft generated for {title} @ {company}")
        return draft

    except Exception as e:
        logger.error(f"Outreach draft error for {title}: {e}")
        return ""


# ── Batch scorer ──────────────────────────────────────────────────────────────

def score_jobs_batch(jobs: list) -> list:
    """Score a list of jobs and draft outreach for high-scorers."""
    scored = []
    for i, job in enumerate(jobs, 1):
        logger.info(f"Scoring {i}/{len(jobs)}: {job.get('title')} @ {job.get('company')}")
        enriched = score_job(job)

        if enriched.get("shouldDraftOutreach") and enriched.get("score", 0) >= 70:
            enriched["outreachDraft"] = draft_outreach(enriched)
        else:
            enriched["outreachDraft"] = ""

        scored.append(enriched)

    return scored

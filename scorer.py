import json
import logging
import anthropic
from config import ANTHROPIC_API_KEY, SCORING_MODEL, OUTREACH_MODEL
from cv_profile import CV_SUMMARY

logger   = logging.getLogger(__name__)
client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SCORING_PROMPT = """\
You are a JSON-only scoring API for executive job matching. Respond with ONLY raw JSON, no markdown, no fences, no explanation.

CANDIDATE PROFILE:
{cv_profile}

JOB OPPORTUNITY:
Title: {title}
Company: {company}
Geography: {geography}
Description: {description}

Score on 5 dimensions (0-20 each). Be strict and realistic.

1. SECTOR FIT (0-20): 20=Telecom/Tech/DataCenter/AI/Energy/CriticalInfra, 12-18=Adjacent digital/industrial, 0-10=Unrelated
2. TITLE SENIORITY (0-20): 20=CEO/President, 17-20=COO/EVP, 14-17=SVP/MD global scope, 0-10=VP or below
3. COMPANY TYPE (0-20): 20=Listed $5B+, 17-20=Large PE/VC-backed, 10-15=Large unclear size, 0-8=SMB/startup
4. SCOPE (0-20): 20=Global multi-continent, 15-18=Multi-country regional, 8-12=Single large country, 0-6=Local
5. SKILLS MATCH (0-20): How well role requires P&L at scale, transformation, M&A integration, critical infra, managed services, AI/digital, multi-country teams

Also determine:
- cvVersion: "Corporate / Listed Co." for listed companies; "PE Operating Partner" for PE/VC-backed
- rationale: one sharp sentence on fit
- shouldDraftOutreach: true only if totalScore >= 70

Respond with ONLY this JSON structure, nothing else:
{"sectorFit":0,"titleSeniority":0,"companyType":0,"scope":0,"skillsMatch":0,"totalScore":0,"cvVersion":"Corporate / Listed Co.","rationale":"","shouldDraftOutreach":false}"""

OUTREACH_PROMPT = """\
Draft a concise, warm, professional outreach email for this executive job opportunity.

CANDIDATE: Joseluis Garcia
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
1. Why this specific role resonates (connect to company mission/sector)
2. Two concrete credentials that directly match (specific numbers)
3. Warm close inviting a conversation

Tone: Confident, direct, warm. Under 180 words total.
Do NOT start with "I am writing to". Start with something that hooks immediately."""


def score_job(job: dict) -> dict:
    title       = job.get("title", "")
    company     = job.get("company", "")
    geography   = job.get("geography", "")
    description = job.get("description", "")[:2000]

    prompt = SCORING_PROMPT.format(
        cv_profile  = CV_SUMMARY,
        title       = title,
        company     = company,
        geography   = geography,
        description = description,
    )

    try:
        message = client.messages.create(
            model      = SCORING_MODEL,
            max_tokens = 512,
            messages   = [{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        # Strip any accidental markdown fences
        raw = raw.replace("```json", "").replace("```", "").strip()
        # Handle prefixed opening brace from assistant prefill patterns
        if not raw.startswith("{"):
            idx = raw.find("{")
            if idx != -1:
                raw = raw[idx:]
        result = json.loads(raw)

        dims = ["sectorFit", "titleSeniority", "companyType", "scope", "skillsMatch"]
        for d in dims:
            result[d] = max(0, min(20, int(result.get(d, 0))))
        result["totalScore"] = sum(result[d] for d in dims)

        enriched = {
            **job,
            "score":               result["totalScore"],
            "cvVersion":           result.get("cvVersion", "Corporate / Listed Co."),
            "scoringRationale":    result.get("rationale", ""),
            "scoringBreakdown":    {d: result[d] for d in dims},
            "shouldDraftOutreach": result.get("shouldDraftOutreach", False),
        }
        logger.info(f"Scored: {title} @ {company} -> {result['totalScore']}/100")
        return enriched

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error scoring {title}: {e} | raw: {raw[:200]}")
        return {**job, "score": 0, "cvVersion": "Corporate / Listed Co.",
                "scoringRationale": "Scoring failed", "scoringBreakdown": {},
                "shouldDraftOutreach": False}
    except Exception as e:
        logger.error(f"Scoring error for {title}: {e}")
        return {**job, "score": 0, "cvVersion": "Corporate / Listed Co.",
                "scoringRationale": "Scoring failed", "scoringBreakdown": {},
                "shouldDraftOutreach": False}


def draft_outreach(job: dict) -> str:
    prompt = OUTREACH_PROMPT.format(
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
        else:
            enriched["outreachDraft"] = ""
        scored.append(enriched)
    return scored

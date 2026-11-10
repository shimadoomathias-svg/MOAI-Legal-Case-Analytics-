import os
import re
from statistics import median

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import (
    CaseRecord, CaseOffence, Offence, CaseOutcome, Jurisdiction, Court, CaseFactor
)
from ..schemas import PredictionRequest

router = APIRouter(prefix="/api/predictions", tags=["Predictions"])
MINIMUM_COMPARABLE_CASES = 10
AI_TIMEOUT_SECONDS = 60

STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "was", "were",
    "has", "had", "have", "into", "upon", "where", "when", "which",
    "their", "there", "under", "over", "case", "court", "appellant",
    "respondent", "defendant", "prosecution", "accused"
}


def terms(value: str) -> set[str]:
    return {
        x for x in re.findall(r"[a-z0-9]{3,}", (value or "").lower())
        if x not in STOP_WORDS
    }


def similarity_score(hypothetical_terms: set[str], case: CaseRecord):
    if not hypothetical_terms:
        return None
    material = terms(case.facts)
    for factor in case.factors:
        material |= terms(factor.category + " " + factor.description)
    if not material:
        return 0.0
    union = hypothetical_terms | material
    return round(len(hypothetical_terms & material) / len(union) * 100, 1) if union else 0.0


async def generate_ai_prediction(payload, comparable_cases, outcome_distribution, sentence_statistics):
    """Ask the configured free OpenRouter model to interpret the supplied evidence."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return {
            "status": "not_configured",
            "message": "AI prediction is unavailable because OPENROUTER_API_KEY is not configured."
        }

    model = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    if not (model == "openrouter/free" or model.endswith(":free")):
        return {
            "status": "invalid_model_configuration",
            "message": "AI prediction is disabled because this application permits free OpenRouter models only."
        }

    evidence = {
        "jurisdiction_id": payload.jurisdiction_id,
        "offence": payload.offence,
        "court_id": payload.court_id,
        "hypothetical_facts": payload.facts,
        "aggravating_factors": payload.aggravating_factors,
        "mitigating_factors": payload.mitigating_factors,
        "recorded_outcome_distribution": outcome_distribution,
        "recorded_sentence_statistics_months": sentence_statistics,
        "most_relevant_sourced_cases": comparable_cases[:15],
    }
    system_prompt = (
        "You are an evidence-led legal case outcome research assistant. "
        "Assess a hypothetical case using ONLY the supplied dataset. "
        "Do not invent case names, citations, statutes, facts, statistics, or legal rules. "
        "Do not treat lexical similarity as proof of legal similarity. "
        "Clearly distinguish observed dataset patterns from your cautious interpretation. "
        "Give a likely outcome only as a conditional, non-guaranteed research assessment. "
        "Discuss material aggravating and mitigating factors, explain what evidence is missing, "
        "and state when the data does not support a defensible prediction. "
        "Cite supporting cases only by the exact titles and citations supplied. "
        "Do not provide legal advice. Use concise headings: "
        "Provisional outcome assessment; Why; Supporting comparable cases; "
        "Factors that may change the assessment; Confidence and limitations."
    )
    try:
        async with httpx.AsyncClient(timeout=AI_TIMEOUT_SECONDS) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": os.getenv(
                        "APP_PUBLIC_URL",
                        "https://moai-legal-case-analytics.onrender.com"
                    ),
                    "X-Title": "MOAI Legal Case Analytics",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": "Assess this hypothetical case from the following evidence. "
                                       "Return a reasoned assessment, not a guaranteed result.\n\n"
                                       + __import__("json").dumps(evidence, ensure_ascii=False)
                        },
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1200,
                },
            )
        if response.status_code == 429:
            return {"status": "rate_limited", "message": "The free AI request limit has been reached. Try again later."}
        if response.status_code >= 400:
            return {"status": "provider_error", "message": "The AI provider could not complete the prediction. Statistical results are still available."}
        data = response.json()
        answer = data.get("choices", [{}])[0].get("message", {}).get("content")
        if not answer:
            return {"status": "empty_response", "message": "The AI provider returned no prediction."}
        return {
            "status": "generated",
            "provider": "OpenRouter",
            "model": data.get("model", model),
            "assessment": answer,
            "evidence_case_count": len(comparable_cases),
        }
    except httpx.TimeoutException:
        return {"status": "timeout", "message": "The AI prediction timed out. Please try again."}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {"status": "provider_error", "message": "The AI provider is temporarily unavailable. Statistical results are still available."}


@router.get("/status")
def prediction_status():
    return {
        "status": "ai_and_statistical_prediction",
        "minimum_comparable_cases": MINIMUM_COMPARABLE_CASES,
        "ai_configured": bool(os.getenv("OPENROUTER_API_KEY")),
        "ai_model": os.getenv("OPENROUTER_MODEL", "openrouter/free"),
        "method": (
            "Same-jurisdiction exact-offence cohort, with optional same-court restriction; "
            "transparent lexical similarity ranks records; a free OpenRouter AI model "
            "interprets the hypothetical facts against the sourced case cohort and statistics."
        ),
        "warning": "Research assessment only. It is conditional, dataset-dependent, and not a guaranteed court outcome or legal advice."
    }


@router.post("/estimate")
async def estimate_outcome(payload: PredictionRequest, db: Session = Depends(get_db)):
    if db.get(Jurisdiction, payload.jurisdiction_id) is None:
        raise HTTPException(status_code=400, detail="Unknown jurisdiction_id")
    if payload.court_id is not None:
        court = db.get(Court, payload.court_id)
        if court is None or court.jurisdiction_id != payload.jurisdiction_id:
            raise HTTPException(status_code=400, detail="Court must belong to the selected jurisdiction")

    offence_name = payload.offence.strip()
    stmt = (
        select(CaseRecord)
        .join(CaseOffence, CaseOffence.case_id == CaseRecord.id)
        .join(Offence, Offence.id == CaseOffence.offence_id)
        .where(
            CaseRecord.jurisdiction_id == payload.jurisdiction_id,
            CaseRecord.data_status == "researcher-entered",
            CaseRecord.sources.any(),
            func.lower(Offence.name) == offence_name.lower(),
            func.lower(CaseOffence.role).in_(["charged", "convicted"])
        )
        .options(
            selectinload(CaseRecord.court),
            selectinload(CaseRecord.outcomes).selectinload(CaseOutcome.sentences),
            selectinload(CaseRecord.factors)
        )
        .order_by(CaseRecord.decision_date.desc(), CaseRecord.id.desc())
    )
    if payload.court_id is not None:
        stmt = stmt.where(CaseRecord.court_id == payload.court_id)
    cases = db.scalars(stmt).unique().all()

    hypothetical_terms = terms(
        payload.facts + " " +
        " ".join(payload.aggravating_factors + payload.mitigating_factors)
    )
    comparable = []
    outcome_counts = {}
    sentence_months = []
    factor_patterns = {"aggravating": {}, "mitigating": {}, "neutral": {}}

    for case in cases:
        case_outcomes = [o.outcome_type.lower() for o in case.outcomes]
        for outcome in case_outcomes:
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        for outcome in case.outcomes:
            if outcome.outcome_type.lower() in ("conviction", "appeal_dismissed"):
                for sentence in outcome.sentences:
                    if sentence.duration_months is not None:
                        sentence_months.append(float(sentence.duration_months))
        factor_list = []
        for factor in case.factors:
            factor_patterns.setdefault(factor.factor_type, {})
            factor_patterns[factor.factor_type][factor.category] = (
                factor_patterns[factor.factor_type].get(factor.category, 0) + 1
            )
            factor_list.append({
                "type": factor.factor_type,
                "category": factor.category,
                "description": factor.description
            })
        score = similarity_score(hypothetical_terms, case)
        comparable.append({
            "case_id": case.id,
            "title": case.title,
            "citation": case.case_reference,
            "decision_date": case.decision_date.isoformat() if case.decision_date else None,
            "court": case.court.name if case.court else None,
            "facts": case.facts[:2500],
            "outcomes": case_outcomes,
            "factors": factor_list,
            "similarity_score": score
        })

    comparable.sort(
        key=lambda x: (
            x["similarity_score"] is not None,
            x["similarity_score"] or 0,
            x["decision_date"] or ""
        ),
        reverse=True
    )
    count = len(cases)
    if count >= 50:
        sample_indicator = "Larger sample"
    elif count >= 25:
        sample_indicator = "Moderate sample"
    elif count >= MINIMUM_COMPARABLE_CASES:
        sample_indicator = "Limited sample"
    else:
        sample_indicator = "Insufficient sample"

    base = {
        "jurisdiction_id": payload.jurisdiction_id,
        "offence": offence_name,
        "court_id": payload.court_id,
        "comparable_case_count": count,
        "minimum_required": MINIMUM_COMPARABLE_CASES,
        "comparable_cases": comparable[:25],
        "factor_patterns": factor_patterns,
        "sample_adequacy": sample_indicator,
        "method": (
            "Exact offence name and same jurisdiction; optional same-court restriction. "
            "Similarity ranking uses Jaccard overlap of words in supplied hypothetical facts "
            "and factors against recorded case facts and factors. The AI interprets the "
            "supplied evidence and cohort statistics; it does not independently verify judgments."
        ),
        "limitations": [
            "Only researcher-entered records with at least one source entry are included; source content is not independently certified.",
            "Exact offence matching can omit cases recorded under a different offence label or statutory provision.",
            "Lexical similarity is a text-overlap aid, not a validated legal similarity or machine-learning score.",
            "Recorded factor frequencies show association in this dataset and do not establish causation.",
            "Missing, selective or inconsistent data can materially affect results.",
            "Cross-court legal and sentencing differences may remain within one jurisdiction.",
            "AI output is conditional research analysis, not legal advice or a guaranteed prediction."
        ]
    }

    if count < MINIMUM_COMPARABLE_CASES:
        return {
            **base,
            "status": "insufficient_data",
            "message": (
                f"Only {count} sourced researcher-entered comparable case record(s) were found. "
                f"At least {MINIMUM_COMPARABLE_CASES} are required before generating an AI-supported "
                "outcome assessment."
            ),
            "outcome_distribution": None,
            "sentence_statistics": None,
            "ai_prediction": {
                "status": "insufficient_data",
                "message": "The system will not manufacture a likely outcome from an inadequate case sample."
            }
        }

    total_outcomes = sum(outcome_counts.values())
    distribution = {
        name: {"count": value, "percentage": round(value / total_outcomes * 100, 1)}
        for name, value in sorted(outcome_counts.items())
    } if total_outcomes else {}
    sentence_stats = None
    if sentence_months:
        values = sorted(sentence_months)
        q1 = values[int((len(values) - 1) * 0.25)]
        q3 = values[int((len(values) - 1) * 0.75)]
        sentence_stats = {
            "sample_size": len(values),
            "median_months": round(median(values), 1),
            "middle_50_percent_months": [round(q1, 1), round(q3, 1)],
            "minimum_months": round(values[0], 1),
            "maximum_months": round(values[-1], 1)
        }

    ai_prediction = await generate_ai_prediction(
        payload, comparable, distribution, sentence_stats
    )
    return {
        **base,
        "status": "estimate_available",
        "message": "Statistical estimates calculated from the sourced comparable records.",
        "outcome_sample_size": total_outcomes,
        "outcome_distribution": distribution,
        "sentence_statistics": sentence_stats,
        "ai_prediction": ai_prediction
    }

import re
from statistics import median
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from ..database import get_db
from ..models import CaseRecord, CaseOffence, Offence, CaseOutcome, Sentence, Jurisdiction, Court, CaseFactor
from ..schemas import PredictionRequest

router = APIRouter(prefix="/api/predictions", tags=["Predictions"])
MINIMUM_COMPARABLE_CASES = 10

STOP_WORDS = {"the", "and", "for", "with", "from", "that", "this", "was", "were",
              "has", "had", "have", "into", "upon", "where", "when", "which",
              "their", "there", "under", "over", "case", "court", "appellant",
              "respondent", "defendant", "prosecution", "accused"}

def terms(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]{3,}", (value or "").lower()) if x not in STOP_WORDS}

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

@router.get("/status")
def prediction_status():
    return {
        "status": "statistical_estimates_enabled",
        "minimum_comparable_cases": MINIMUM_COMPARABLE_CASES,
        "method": "Same-jurisdiction exact-offence cohort, with optional same-court restriction and transparent lexical similarity ranking using hypothetical facts and recorded factors.",
        "warning": "Descriptive research statistics, not legal advice or a guaranteed prediction."
    }

@router.post("/estimate")
def estimate_outcome(payload: PredictionRequest, db: Session = Depends(get_db)):
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

    hypothetical_terms = terms(payload.facts + " " + " ".join(payload.aggravating_factors + payload.mitigating_factors))
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
            factor_patterns[factor.factor_type][factor.category] = factor_patterns[factor.factor_type].get(factor.category, 0) + 1
            factor_list.append({"type": factor.factor_type, "category": factor.category, "description": factor.description})
        score = similarity_score(hypothetical_terms, case)
        comparable.append({
            "case_id": case.id,
            "title": case.title,
            "citation": case.case_reference,
            "decision_date": case.decision_date.isoformat() if case.decision_date else None,
            "court": case.court.name if case.court else None,
            "outcomes": case_outcomes,
            "factors": factor_list,
            "similarity_score": score
        })

    comparable.sort(key=lambda x: (x["similarity_score"] is not None, x["similarity_score"] or 0,
                                   x["decision_date"] or ""), reverse=True)
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
        "method": "Exact offence name and same jurisdiction; optional same-court restriction. Similarity ranking uses Jaccard overlap of words in supplied hypothetical facts/factors against recorded case facts and factors. Outcome and sentence statistics use the full qualifying offence cohort, not only the top-ranked cases.",
        "limitations": [
            "Only researcher-entered records with at least one source entry are included; the platform does not independently certify the source content.",
            "Exact offence matching can omit cases recorded under a different offence label or statutory provision.",
            "Lexical similarity is a transparent text-overlap aid, not a validated legal similarity or machine-learning model.",
            "Recorded factor frequencies show association in this dataset and do not establish that a factor caused an outcome or sentence.",
            "The estimate reflects only records currently stored; missing, selective or inconsistent data can materially affect results.",
            "Cross-court legal and sentencing differences may remain even within one jurisdiction.",
            "This is a research aid, not legal advice or a prediction of what a court will decide."
        ]
    }
    if count < MINIMUM_COMPARABLE_CASES:
        return {
            **base,
            "status": "insufficient_data",
            "message": f"Only {count} verified comparable case record(s) were found. At least {MINIMUM_COMPARABLE_CASES} are required before displaying statistical outcome estimates.",
            "outcome_distribution": None,
            "sentence_statistics": None
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
    return {
        **base,
        "status": "estimate_available",
        "message": "Descriptive estimates calculated from the comparable records listed below.",
        "outcome_sample_size": total_outcomes,
        "outcome_distribution": distribution,
        "sentence_statistics": sentence_stats
    }

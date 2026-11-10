from statistics import median
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from ..database import get_db
from ..models import CaseRecord, CaseOffence, Offence, CaseOutcome, Sentence
from ..schemas import PredictionRequest

router = APIRouter(prefix="/api/predictions", tags=["Predictions"])

MINIMUM_COMPARABLE_CASES = 10

@router.get("/status")
def prediction_status():
    return {
        "status": "statistical_estimates_enabled",
        "minimum_comparable_cases": MINIMUM_COMPARABLE_CASES,
        "method": "Exact offence matching within the selected jurisdiction, using source-verified researcher-entered records",
        "warning": "Estimates are descriptive statistical indications, not legal advice or guarantees."
    }

@router.post("/estimate")
def estimate_outcome(payload: PredictionRequest, db: Session = Depends(get_db)):
    offence_name = payload.offence.strip()
    stmt = (
        select(CaseRecord)
        .join(CaseOffence, CaseOffence.case_id == CaseRecord.id)
        .join(Offence, Offence.id == CaseOffence.offence_id)
        .where(
            CaseRecord.jurisdiction_id == payload.jurisdiction_id,
            CaseRecord.data_status == "researcher-entered",
            func.lower(Offence.name) == offence_name.lower(),
            CaseOffence.role.in_(["charged", "convicted"])
        )
        .options(
            selectinload(CaseRecord.court),
            selectinload(CaseRecord.outcomes).selectinload(CaseOutcome.sentences)
        )
        .order_by(CaseRecord.decision_date.desc(), CaseRecord.id.desc())
    )
    if payload.court_id is not None:
        stmt = stmt.where(CaseRecord.court_id == payload.court_id)
    cases = db.scalars(stmt).unique().all()
    comparable = []
    outcome_counts = {}
    sentence_months = []
    fine_amounts = []
    for case in cases:
        case_outcomes = [o.outcome_type.lower() for o in case.outcomes]
        for outcome in case_outcomes:
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        for outcome in case.outcomes:
            if outcome.outcome_type.lower() in ("conviction", "appeal_dismissed"):
                for sentence in outcome.sentences:
                    if sentence.duration_months is not None:
                        sentence_months.append(float(sentence.duration_months))
                    if sentence.fine_amount is not None:
                        fine_amounts.append(float(sentence.fine_amount))
        comparable.append({
            "case_id": case.id,
            "title": case.title,
            "citation": case.case_reference,
            "decision_date": case.decision_date.isoformat() if case.decision_date else None,
            "court": case.court.name if case.court else None,
            "outcomes": case_outcomes
        })
    count = len(cases)
    base = {
        "jurisdiction_id": payload.jurisdiction_id,
        "offence": offence_name,
        "court_id": payload.court_id,
        "comparable_case_count": count,
        "minimum_required": MINIMUM_COMPARABLE_CASES,
        "comparable_cases": comparable[:25],
        "method": "Exact offence name; same jurisdiction; researcher-entered records only" + ("; same court" if payload.court_id else ""),
        "limitations": [
            "The estimate reflects only records currently stored in this platform.",
            "A matching offence name does not guarantee identical facts, charges, statutory provisions, or sentencing circumstances.",
            "Unverified and synthetic records are excluded.",
            "This is a statistical research aid, not legal advice or a prediction of what a court will decide."
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

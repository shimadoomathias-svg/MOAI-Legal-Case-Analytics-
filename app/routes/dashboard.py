from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from statistics import median
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import CaseRecord, CaseOutcome, Sentence, CaseOffence, Offence

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

@router.get("/overview")
def overview(jurisdiction_id: int | None = None, db: Session = Depends(get_db)):
    case_stmt = select(func.count(CaseRecord.id))
    if jurisdiction_id is not None:
        case_stmt = case_stmt.where(CaseRecord.jurisdiction_id == jurisdiction_id)
    total_cases = db.scalar(case_stmt) or 0
    outcome_stmt = select(CaseOutcome.outcome_type, func.count(CaseOutcome.id)).join(CaseRecord, CaseOutcome.case_id == CaseRecord.id)
    if jurisdiction_id is not None:
        outcome_stmt = outcome_stmt.where(CaseRecord.jurisdiction_id == jurisdiction_id)
    outcome_rows = db.execute(outcome_stmt.group_by(CaseOutcome.outcome_type)).all()
    outcomes = {name: count for name, count in outcome_rows}
    sentence_stmt = select(func.avg(Sentence.duration_months), func.min(Sentence.duration_months),
        func.max(Sentence.duration_months), func.count(Sentence.id)).join(CaseOutcome, Sentence.outcome_id == CaseOutcome.id).join(CaseRecord, CaseOutcome.case_id == CaseRecord.id).where(Sentence.duration_months.is_not(None))
    if jurisdiction_id is not None:
        sentence_stmt = sentence_stmt.where(CaseRecord.jurisdiction_id == jurisdiction_id)
    sentence_stats = db.execute(sentence_stmt).one()
    duration_stmt = (select(Sentence.duration_months).join(CaseOutcome, Sentence.outcome_id == CaseOutcome.id)
        .join(CaseRecord, CaseOutcome.case_id == CaseRecord.id)
        .where(Sentence.duration_months.is_not(None)))
    if jurisdiction_id is not None:
        duration_stmt = duration_stmt.where(CaseRecord.jurisdiction_id == jurisdiction_id)
    durations = sorted(float(x) for x in db.scalars(duration_stmt).all())
    q1 = durations[int((len(durations) - 1) * 0.25)] if durations else None
    q3 = durations[int((len(durations) - 1) * 0.75)] if durations else None
    offence_stmt = (select(Offence.name, func.count(func.distinct(CaseRecord.id)).label("case_count"))
        .join(CaseOffence, CaseOffence.offence_id == Offence.id)
        .join(CaseRecord, CaseRecord.id == CaseOffence.case_id))
    if jurisdiction_id is not None:
        offence_stmt = offence_stmt.where(CaseRecord.jurisdiction_id == jurisdiction_id)
    common_offences = [{"name": name, "cases": count} for name, count in
        db.execute(offence_stmt.group_by(Offence.name).order_by(func.count(func.distinct(CaseRecord.id)).desc(), Offence.name).limit(10)).all()]
    return {
        "total_cases": total_cases, "outcomes": outcomes,
        "convictions": outcomes.get("conviction", 0), "acquittals": outcomes.get("acquittal", 0),
        "dismissals": outcomes.get("dismissal", 0),
        "sentence_duration_months": {
            "average": round(sentence_stats[0], 2) if sentence_stats[0] is not None else None,
            "median": round(median(durations), 2) if durations else None,
            "minimum": sentence_stats[1], "maximum": sentence_stats[2], "records": sentence_stats[3],
            "middle_50_percent": [round(q1, 2), round(q3, 2)] if durations else None
        },
        "common_offences": common_offences,
        "note": "Figures are calculated from records currently stored; an empty database returns zero or null values."
    }

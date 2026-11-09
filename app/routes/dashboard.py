from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import CaseRecord, CaseOutcome, Sentence

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
    return {
        "total_cases": total_cases, "outcomes": outcomes,
        "convictions": outcomes.get("conviction", 0), "acquittals": outcomes.get("acquittal", 0),
        "dismissals": outcomes.get("dismissal", 0),
        "sentence_duration_months": {"average": round(sentence_stats[0], 2) if sentence_stats[0] is not None else None,
            "minimum": sentence_stats[1], "maximum": sentence_stats[2], "records": sentence_stats[3]},
        "note": "Figures are calculated from records currently stored; an empty database returns zero or null values."
    }

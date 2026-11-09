from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import CaseRecord, CaseOutcome

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

@router.get("/outcomes-by-year")
def outcomes_by_year(jurisdiction_id: int | None = None, db: Session = Depends(get_db)):
    stmt = (
        select(CaseRecord.year, CaseOutcome.outcome_type, func.count(CaseOutcome.id))
        .join(CaseOutcome, CaseOutcome.case_id == CaseRecord.id)
        .where(CaseRecord.year.is_not(None))
        .group_by(CaseRecord.year, CaseOutcome.outcome_type)
        .order_by(CaseRecord.year)
    )
    if jurisdiction_id is not None:
        stmt = stmt.where(CaseRecord.jurisdiction_id == jurisdiction_id)
    return [
        {"year": year, "outcome": outcome, "count": count}
        for year, outcome, count in db.execute(stmt).all()
    ]

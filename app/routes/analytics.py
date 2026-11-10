from fastapi import APIRouter, Depends
from sqlalchemy import func, select, String
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import CaseRecord, CaseOutcome, Offence, CaseOffence, Court, Jurisdiction

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

@router.get("/outcomes-by-year")
def outcomes_by_year(jurisdiction_id: int | None = None, db: Session = Depends(get_db)):
    stmt = (select(CaseRecord.year, CaseOutcome.outcome_type, func.count(CaseOutcome.id))
        .join(CaseOutcome, CaseOutcome.case_id == CaseRecord.id)
        .where(CaseRecord.year.is_not(None))
        .group_by(CaseRecord.year, CaseOutcome.outcome_type).order_by(CaseRecord.year))
    if jurisdiction_id is not None:
        stmt = stmt.where(CaseRecord.jurisdiction_id == jurisdiction_id)
    return [{"year": year, "outcome": outcome, "count": count}
            for year, outcome, count in db.execute(stmt).all()]


@router.get("/breakdown")
def analytics_breakdown(dimension: str, jurisdiction_id: int | None = None, db: Session = Depends(get_db)):
    allowed = {"offence", "court", "outcome", "jurisdiction", "year"}
    if dimension not in allowed:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Dimension must be offence, court, outcome, jurisdiction, or year")
    if dimension == "offence":
        label = Offence.name
        stmt = (select(label, func.count(func.distinct(CaseRecord.id))).select_from(CaseRecord)
            .join(CaseOffence, CaseOffence.case_id == CaseRecord.id).join(Offence, Offence.id == CaseOffence.offence_id).group_by(Offence.name))
    elif dimension == "court":
        label = func.coalesce(Court.name, "Not recorded")
        stmt = (select(label, func.count(func.distinct(CaseRecord.id))).select_from(CaseRecord)
            .outerjoin(Court, Court.id == CaseRecord.court_id).group_by(label))
    elif dimension == "outcome":
        label = CaseOutcome.outcome_type
        stmt = (select(label, func.count(CaseOutcome.id)).select_from(CaseRecord)
            .join(CaseOutcome, CaseOutcome.case_id == CaseRecord.id).group_by(CaseOutcome.outcome_type))
    elif dimension == "jurisdiction":
        label = Jurisdiction.name
        stmt = (select(label, func.count(CaseRecord.id)).select_from(CaseRecord)
            .join(Jurisdiction, Jurisdiction.id == CaseRecord.jurisdiction_id).group_by(Jurisdiction.name))
    else:
        label = func.coalesce(func.cast(CaseRecord.year, String), "Not recorded")
        stmt = select(label, func.count(CaseRecord.id)).select_from(CaseRecord).group_by(label)
    if jurisdiction_id is not None and dimension != "jurisdiction":
        stmt = stmt.where(CaseRecord.jurisdiction_id == jurisdiction_id)
    rows = db.execute(stmt.order_by(func.count().desc(), label)).all()
    return [{"label": str(name), "count": count} for name, count in rows]

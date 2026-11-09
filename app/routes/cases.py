from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import CaseRecord, Jurisdiction, Court
from ..schemas import CaseCreate, CaseOut

router = APIRouter(prefix="/api/cases", tags=["Cases"])

@router.get("", response_model=list[CaseOut])
def list_cases(jurisdiction_id: int | None = None, year: int | None = None,
               verdict: str | None = Query(default=None, description="Reserved for outcome filtering"),
               search: str | None = None, limit: int = Query(default=100, ge=1, le=500),
               offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    stmt = select(CaseRecord).order_by(CaseRecord.decision_date.desc(), CaseRecord.id.desc())
    if jurisdiction_id is not None:
        stmt = stmt.where(CaseRecord.jurisdiction_id == jurisdiction_id)
    if year is not None:
        stmt = stmt.where(CaseRecord.year == year)
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where((CaseRecord.title.ilike(term)) | (CaseRecord.case_reference.ilike(term)))
    return db.scalars(stmt.offset(offset).limit(limit)).all()

@router.post("", response_model=CaseOut, status_code=201)
def create_case(payload: CaseCreate, db: Session = Depends(get_db)):
    if db.get(Jurisdiction, payload.jurisdiction_id) is None:
        raise HTTPException(status_code=400, detail="Unknown jurisdiction_id")
    if payload.court_id is not None:
        court = db.get(Court, payload.court_id)
        if court is None or court.jurisdiction_id != payload.jurisdiction_id:
            raise HTTPException(status_code=400, detail="Court must belong to the selected jurisdiction")
    item = CaseRecord(**payload.model_dump(exclude={"decision_date"}),
                      decision_date=payload.decision_date,
                      year=payload.decision_date.year if payload.decision_date else None)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: int, db: Session = Depends(get_db)):
    item = db.get(CaseRecord, case_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return item

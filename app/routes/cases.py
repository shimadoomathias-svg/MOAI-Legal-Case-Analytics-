from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from ..database import get_db
from ..models import CaseRecord, Jurisdiction, Court, Offence, CaseOffence, CaseOutcome, Sentence, CaseSource
from ..schemas import CaseCreate, CaseUpdate, CaseOut, ResearchDataCreate

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

@router.put("/{case_id}", response_model=CaseOut)
def update_case(case_id: int, payload: CaseUpdate, db: Session = Depends(get_db)):
    item = db.get(CaseRecord, case_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found")
    changes = payload.model_dump(exclude_unset=True)
    new_jurisdiction_id = changes.get("jurisdiction_id", item.jurisdiction_id)
    if "jurisdiction_id" in changes and db.get(Jurisdiction, new_jurisdiction_id) is None:
        raise HTTPException(status_code=400, detail="Unknown jurisdiction_id")
    new_court_id = changes.get("court_id", item.court_id)
    if new_court_id is not None:
        court = db.get(Court, new_court_id)
        if court is None or court.jurisdiction_id != new_jurisdiction_id:
            raise HTTPException(status_code=400, detail="Court must belong to the selected jurisdiction")
    for field, value in changes.items():
        setattr(item, field, value)
    if "decision_date" in changes or "decision_date" not in changes and "year" not in changes:
        item.year = item.decision_date.year if item.decision_date else None
    db.commit()
    db.refresh(item)
    return item

@router.get("/{case_id}/research")
def get_case_research(case_id: int, db: Session = Depends(get_db)):
    item = db.scalar(select(CaseRecord).where(CaseRecord.id == case_id).options(
        selectinload(CaseRecord.jurisdiction), selectinload(CaseRecord.court),
        selectinload(CaseRecord.offences).selectinload(CaseOffence.offence),
        selectinload(CaseRecord.outcomes).selectinload(CaseOutcome.sentences),
        selectinload(CaseRecord.sources)))
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return {
        "case": CaseOut.model_validate(item).model_dump(mode="json"),
        "jurisdiction": item.jurisdiction.name if item.jurisdiction else None,
        "court": item.court.name if item.court else None,
        "offences": [{"id": x.id, "name": x.offence.name, "category": x.offence.category, "role": x.role} for x in item.offences],
        "outcomes": [{"id": o.id, "outcome_type": o.outcome_type, "notes": o.notes,
                      "sentences": [{"id": s.id, "sentence_type": s.sentence_type, "duration_months": s.duration_months,
                                     "fine_amount": s.fine_amount, "currency": s.currency,
                                     "is_suspended": s.is_suspended, "notes": s.notes} for s in o.sentences]}
                     for o in item.outcomes],
        "sources": [{"id": s.id, "source_type": s.source_type, "title": s.title, "url": s.url,
                     "citation": s.citation, "accessed_on": s.accessed_on.isoformat() if s.accessed_on else None}
                    for s in item.sources]
    }

@router.post("/{case_id}/research", status_code=201)
def add_case_research(case_id: int, payload: ResearchDataCreate, db: Session = Depends(get_db)):
    item = db.get(CaseRecord, case_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        for entry in payload.offences:
            name = entry.name.strip()
            if not name:
                continue
            offence = db.scalar(select(Offence).where(
                Offence.jurisdiction_id == item.jurisdiction_id,
                Offence.name.ilike(name)))
            if offence is None:
                offence = Offence(name=name, category=entry.category, jurisdiction_id=item.jurisdiction_id)
                db.add(offence)
                db.flush()
            exists = db.scalar(select(CaseOffence).where(
                CaseOffence.case_id == case_id, CaseOffence.offence_id == offence.id,
                CaseOffence.role == entry.role))
            if exists is None:
                db.add(CaseOffence(case_id=case_id, offence_id=offence.id, role=entry.role))
        for entry in payload.outcomes:
            outcome = CaseOutcome(case_id=case_id, outcome_type=entry.outcome_type.strip().lower(), notes=entry.notes)
            db.add(outcome)
            db.flush()
            for s in entry.sentences:
                db.add(Sentence(outcome_id=outcome.id, **s.model_dump()))
        for entry in payload.sources:
            url = entry.url.strip()
            if url and not url.startswith(("https://", "http://")):
                raise HTTPException(status_code=422, detail="Source URLs must begin with http:// or https://")
            db.add(CaseSource(case_id=case_id, **entry.model_dump()))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"message": "Research data saved", "case_id": case_id}

@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: int, db: Session = Depends(get_db)):
    item = db.get(CaseRecord, case_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return item

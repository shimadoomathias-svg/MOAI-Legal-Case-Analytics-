from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Jurisdiction, Court, Offence

router = APIRouter(prefix="/api", tags=["Research metadata"])

@router.get("/jurisdictions")
def jurisdictions(db: Session = Depends(get_db)):
    rows = db.scalars(select(Jurisdiction).where(Jurisdiction.is_active == True).order_by(Jurisdiction.name)).all()
    return [{"id": x.id, "name": x.name, "country_code": x.country_code, "legal_system": x.legal_system, "region": x.region} for x in rows]

@router.get("/courts")
def courts(jurisdiction_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(Court).order_by(Court.name)
    if jurisdiction_id is not None:
        stmt = stmt.where(Court.jurisdiction_id == jurisdiction_id)
    return [{"id": x.id, "name": x.name, "level": x.level, "location": x.location, "jurisdiction_id": x.jurisdiction_id} for x in db.scalars(stmt).all()]

@router.get("/offences")
def offences(jurisdiction_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(Offence).order_by(Offence.name)
    if jurisdiction_id is not None:
        stmt = stmt.where((Offence.jurisdiction_id == jurisdiction_id) | (Offence.jurisdiction_id.is_(None)))
    return [{"id": x.id, "name": x.name, "category": x.category, "jurisdiction_id": x.jurisdiction_id} for x in db.scalars(stmt).all()]

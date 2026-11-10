from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
import csv
import io
from datetime import date
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session, selectinload
from ..database import get_db
from ..models import CaseRecord, Jurisdiction, Court, Offence, CaseOffence, CaseOutcome, Sentence, CaseSource, CaseFactor
from ..schemas import CaseCreate, CaseUpdate, CaseOut, ResearchDataCreate

router = APIRouter(prefix="/api/cases", tags=["Cases"])

@router.get("", response_model=list[CaseOut])
def list_cases(jurisdiction_id: int | None = None, year: int | None = None,
               verdict: str | None = None, offence: str | None = None,
               court_id: int | None = None, sentence_type: str | None = None,
               min_sentence_months: float | None = Query(default=None, ge=0),
               max_sentence_months: float | None = Query(default=None, ge=0),
               search: str | None = None, limit: int = Query(default=100, ge=1, le=500),
               offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    stmt = select(CaseRecord).order_by(CaseRecord.decision_date.desc(), CaseRecord.id.desc())
    if jurisdiction_id is not None:
        stmt = stmt.where(CaseRecord.jurisdiction_id == jurisdiction_id)
    if year is not None:
        stmt = stmt.where(CaseRecord.year == year)
    if court_id is not None:
        stmt = stmt.where(CaseRecord.court_id == court_id)
    if verdict:
        stmt = stmt.where(CaseRecord.outcomes.any(func.lower(CaseOutcome.outcome_type) == verdict.strip().lower()))
    if offence:
        stmt = stmt.where(CaseRecord.offences.any(CaseOffence.offence.has(func.lower(Offence.name) == offence.strip().lower())))
    if sentence_type:
        stmt = stmt.where(CaseRecord.outcomes.any(CaseOutcome.sentences.any(
            func.lower(Sentence.sentence_type) == sentence_type.strip().lower())))
    if min_sentence_months is not None and max_sentence_months is not None:
        stmt = stmt.where(CaseRecord.outcomes.any(CaseOutcome.sentences.any(
            (Sentence.duration_months >= min_sentence_months) &
            (Sentence.duration_months <= max_sentence_months))))
    elif min_sentence_months is not None:
        stmt = stmt.where(CaseRecord.outcomes.any(CaseOutcome.sentences.any(
            Sentence.duration_months >= min_sentence_months)))
    elif max_sentence_months is not None:
        stmt = stmt.where(CaseRecord.outcomes.any(CaseOutcome.sentences.any(
            Sentence.duration_months <= max_sentence_months)))
    if min_sentence_months is not None and max_sentence_months is not None and min_sentence_months > max_sentence_months:
        raise HTTPException(status_code=400, detail="Minimum sentence duration cannot exceed maximum duration")
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where((CaseRecord.title.ilike(term)) | (CaseRecord.case_reference.ilike(term)))
    return db.scalars(stmt.offset(offset).limit(limit)).all()

@router.get("/count")
def count_cases(jurisdiction_id: int | None = None, year: int | None = None,
                verdict: str | None = None, offence: str | None = None,
                court_id: int | None = None, sentence_type: str | None = None,
                min_sentence_months: float | None = Query(default=None, ge=0),
                max_sentence_months: float | None = Query(default=None, ge=0),
                search: str | None = None, db: Session = Depends(get_db)):
    stmt = select(func.count(func.distinct(CaseRecord.id))).select_from(CaseRecord)
    if jurisdiction_id is not None:
        stmt = stmt.where(CaseRecord.jurisdiction_id == jurisdiction_id)
    if year is not None:
        stmt = stmt.where(CaseRecord.year == year)
    if court_id is not None:
        stmt = stmt.where(CaseRecord.court_id == court_id)
    if verdict:
        stmt = stmt.where(CaseRecord.outcomes.any(func.lower(CaseOutcome.outcome_type) == verdict.strip().lower()))
    if offence:
        stmt = stmt.where(CaseRecord.offences.any(CaseOffence.offence.has(func.lower(Offence.name) == offence.strip().lower())))
    sentence_conditions = []
    if sentence_type:
        sentence_conditions.append(func.lower(Sentence.sentence_type) == sentence_type.strip().lower())
    if min_sentence_months is not None:
        sentence_conditions.append(Sentence.duration_months >= min_sentence_months)
    if max_sentence_months is not None:
        sentence_conditions.append(Sentence.duration_months <= max_sentence_months)
    if min_sentence_months is not None and max_sentence_months is not None and min_sentence_months > max_sentence_months:
        raise HTTPException(status_code=400, detail="Minimum sentence duration cannot exceed maximum duration")
    if sentence_conditions:
        stmt = stmt.where(CaseRecord.outcomes.any(CaseOutcome.sentences.any(and_(*sentence_conditions))))
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where((CaseRecord.title.ilike(term)) | (CaseRecord.case_reference.ilike(term)))
    return {"total": db.scalar(stmt) or 0}


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


@router.get("/import-template.csv")
def import_template():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["title", "case_reference", "jurisdiction", "court", "decision_date",
        "summary", "facts", "data_status", "source_title", "source_citation", "source_url",
        "offence", "offence_role", "outcome_type", "outcome_notes", "sentence_type",
        "duration_months", "fine_amount", "currency", "is_suspended", "factor_type", "factor_category", "factor_description"])
    writer.writerow(["Example v Example", "Neutral citation", "Nigeria", "", "2024-01-15",
        "Short factual summary", "Material facts", "unverified", "Judgment source",
        "Source citation", "https://example.org/judgment", "Theft", "convicted",
        "conviction", "", "Imprisonment", "12", "", "NGN", "false", "mitigating", "Personal circumstances", "First-time offender where established by the record"])
    buffer.seek(0)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=moai_case_import_template.csv"})


@router.post("/import.csv")
async def import_cases_csv(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not raw or len(raw) > 5_000_000:
        raise HTTPException(status_code=400, detail="Upload a non-empty CSV file smaller than 5 MB")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        required = {"title", "case_reference", "jurisdiction"}
        if not reader.fieldnames or not required.issubset({x.strip() for x in reader.fieldnames if x}):
            raise HTTPException(status_code=400, detail="CSV must include title, case_reference and jurisdiction columns")
        rows = list(reader)
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded")
    if not rows:
        raise HTTPException(status_code=400, detail="CSV contains no case rows")
    if len(rows) > 1000:
        raise HTTPException(status_code=400, detail="Import is limited to 1,000 rows per upload")

    imported, errors = 0, []
    for line_number, raw_row in enumerate(rows, start=2):
        row = {(k or "").strip(): (v or "").strip() for k, v in raw_row.items()}
        try:
            with db.begin_nested():
                title = row.get("title", "")
                reference = row.get("case_reference", "")
                jurisdiction_name = row.get("jurisdiction", "")
                if not title or not reference or not jurisdiction_name:
                    raise ValueError("title, case_reference and jurisdiction are required")
                jurisdiction = db.scalar(select(Jurisdiction).where(
                    func.lower(Jurisdiction.name) == jurisdiction_name.lower()))
                if jurisdiction is None:
                    raise ValueError(f"Unknown jurisdiction: {jurisdiction_name}")
                court = None
                if row.get("court"):
                    court = db.scalar(select(Court).where(
                        func.lower(Court.name) == row["court"].lower(),
                        Court.jurisdiction_id == jurisdiction.id))
                    if court is None:
                        raise ValueError(f"Court not found in {jurisdiction.name}: {row['court']}")
                decision_date = date.fromisoformat(row["decision_date"]) if row.get("decision_date") else None
                status = row.get("data_status", "unverified").lower()
                if status not in {"researcher-entered", "unverified", "synthetic"}:
                    raise ValueError("data_status must be researcher-entered, unverified or synthetic")
                source_url = row.get("source_url", "")
                if source_url and not source_url.startswith(("https://", "http://")):
                    raise ValueError("source_url must begin with http:// or https://")
                source_citation = row.get("source_citation", "")
                source_title = row.get("source_title", "")
                if status == "researcher-entered" and not (source_url or source_citation or source_title):
                    status = "unverified"
                item = CaseRecord(
                    title=title, case_reference=reference, jurisdiction_id=jurisdiction.id,
                    court_id=court.id if court else None, decision_date=decision_date,
                    year=decision_date.year if decision_date else None,
                    summary=row.get("summary", ""), facts=row.get("facts", ""), data_status=status)
                db.add(item)
                db.flush()
                if source_url or source_citation or source_title:
                    db.add(CaseSource(case_id=item.id, source_type="judgment",
                        title=source_title, citation=source_citation, url=source_url))
                offence_name = row.get("offence", "")
                if offence_name:
                    offence = db.scalar(select(Offence).where(
                        func.lower(Offence.name) == offence_name.lower(),
                        Offence.jurisdiction_id == jurisdiction.id))
                    if offence is None:
                        offence = Offence(name=offence_name, jurisdiction_id=jurisdiction.id)
                        db.add(offence)
                        db.flush()
                    db.add(CaseOffence(case_id=item.id, offence_id=offence.id,
                        role=row.get("offence_role", "charged") or "charged"))
                factor_description = row.get("factor_description", "")
                if factor_description:
                    factor_type = row.get("factor_type", "mitigating").lower() or "mitigating"
                    if factor_type not in {"aggravating", "mitigating", "neutral"}:
                        raise ValueError("factor_type must be aggravating, mitigating or neutral")
                    db.add(CaseFactor(case_id=item.id, factor_type=factor_type,
                        category=row.get("factor_category", "Other") or "Other",
                        description=factor_description))
                outcome_type = row.get("outcome_type", "").lower()
                if outcome_type:
                    outcome = CaseOutcome(case_id=item.id, outcome_type=outcome_type,
                        notes=row.get("outcome_notes", ""))
                    db.add(outcome)
                    db.flush()
                    sentence_type = row.get("sentence_type", "")
                    duration = float(row["duration_months"]) if row.get("duration_months") else None
                    fine = float(row["fine_amount"]) if row.get("fine_amount") else None
                    if sentence_type or duration is not None or fine is not None:
                        suspended = row.get("is_suspended", "false").lower() in {"true", "1", "yes"}
                        db.add(Sentence(outcome_id=outcome.id,
                            sentence_type=sentence_type or "Unspecified",
                            duration_months=duration, fine_amount=fine,
                            currency=row.get("currency", "").upper(), is_suspended=suspended))
                db.flush()
            imported += 1
        except Exception as exc:
            errors.append({"row": line_number, "error": str(exc)})
    if imported:
        db.commit()
    return {"imported": imported, "failed": len(errors), "errors": errors[:100],
        "message": f"Imported {imported} case row(s); {len(errors)} row(s) need correction."}


@router.get("/export.csv")
def export_cases_csv(db: Session = Depends(get_db)):
    stmt = select(CaseRecord).options(
        selectinload(CaseRecord.jurisdiction), selectinload(CaseRecord.court),
        selectinload(CaseRecord.offences).selectinload(CaseOffence.offence),
        selectinload(CaseRecord.outcomes).selectinload(CaseOutcome.sentences),
        selectinload(CaseRecord.sources), selectinload(CaseRecord.factors)
    ).order_by(CaseRecord.decision_date.desc(), CaseRecord.id.desc())
    records = db.scalars(stmt).unique().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Case ID", "Title", "Citation", "Decision date", "Jurisdiction", "Court",
        "Data status", "Summary", "Facts", "Offences", "Outcomes", "Sentences", "Sources", "Factors"])
    for case in records:
        offences = "; ".join(f"{x.offence.name} ({x.role})" for x in case.offences)
        outcomes = "; ".join(o.outcome_type for o in case.outcomes)
        sentences = "; ".join(
            f"{s.sentence_type}: {s.duration_months if s.duration_months is not None else ''} months; fine {s.fine_amount if s.fine_amount is not None else ''} {s.currency}"
            for o in case.outcomes for s in o.sentences)
        sources = "; ".join(x.url or x.citation or x.title for x in case.sources)
        factors = "; ".join(f"{x.factor_type}: {x.category}: {x.description}" for x in case.factors)
        writer.writerow([case.id, case.title, case.case_reference,
            case.decision_date.isoformat() if case.decision_date else "",
            case.jurisdiction.name if case.jurisdiction else "",
            case.court.name if case.court else "", case.data_status, case.summary, case.facts,
            offences, outcomes, sentences, sources, factors])
    buffer.seek(0)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=moai_case_research_export.csv"})

@router.get("/{case_id}/research")
def get_case_research(case_id: int, db: Session = Depends(get_db)):
    item = db.scalar(select(CaseRecord).where(CaseRecord.id == case_id).options(
        selectinload(CaseRecord.jurisdiction), selectinload(CaseRecord.court),
        selectinload(CaseRecord.offences).selectinload(CaseOffence.offence),
        selectinload(CaseRecord.outcomes).selectinload(CaseOutcome.sentences),
        selectinload(CaseRecord.sources), selectinload(CaseRecord.factors)))
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
        "factors": [{"id": f.id, "factor_type": f.factor_type, "category": f.category, "description": f.description} for f in item.factors],
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
        for entry in payload.factors:
            db.add(CaseFactor(case_id=case_id, factor_type=entry.factor_type,
                category=entry.category, description=entry.description))
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

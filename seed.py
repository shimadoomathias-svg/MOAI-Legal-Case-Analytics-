from sqlalchemy import select
from .database import SessionLocal
from .models import Jurisdiction, Court, Offence

JURISDICTIONS = [
    ("Nigeria", "NGA", "Common law", "West Africa"),
    ("England and Wales", "GB-ENG", "Common law", "Europe"),
    ("United States", "USA", "Common law / mixed state systems", "North America"),
    ("Canada", "CAN", "Bijural: common law and civil law", "North America"),
    ("Australia", "AUS", "Common law", "Oceania"),
    ("Ghana", "GHA", "Common law", "West Africa"),
    ("South Africa", "ZAF", "Mixed legal system", "Southern Africa"),
]
STARTER_OFFENCES = [
    ("Theft", "Property"),
    ("Fraud", "Financial"),
    ("Assault", "Violence"),
    ("Robbery", "Property / Violence"),
    ("Drug possession", "Drug-related"),
]

def seed_database():
    db = SessionLocal()
    try:
        jurisdictions = {}
        for name, code, system, region in JURISDICTIONS:
            item = db.scalar(select(Jurisdiction).where(Jurisdiction.name == name))
            if item is None:
                item = Jurisdiction(name=name, country_code=code, legal_system=system, region=region)
                db.add(item)
                db.flush()
            jurisdictions[name] = item

        court_seeds = [
            ("Federal High Court (sample)", "Federal court", "Nigeria"),
            ("Crown Court (sample)", "Trial court", "England and Wales"),
            ("U.S. District Court (sample)", "Federal trial court", "United States"),
            ("Superior Court (sample)", "Superior court", "Canada"),
            ("Supreme Court (sample)", "Superior court", "Australia"),
            ("High Court (sample)", "Superior court", "Ghana"),
            ("High Court (sample)", "Superior court", "South Africa"),
        ]
        for name, level, jurisdiction_name in court_seeds:
            jid = jurisdictions[jurisdiction_name].id
            exists = db.scalar(select(Court).where(Court.name == name, Court.jurisdiction_id == jid))
            if exists is None:
                db.add(Court(name=name, level=level, jurisdiction_id=jid))

        for name, category in STARTER_OFFENCES:
            exists = db.scalar(select(Offence).where(Offence.name == name, Offence.jurisdiction_id.is_(None)))
            if exists is None:
                db.add(Offence(name=name, category=category, jurisdiction_id=None))
        db.commit()
    finally:
        db.close()

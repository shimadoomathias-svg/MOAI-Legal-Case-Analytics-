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

# Court names are scoped to their jurisdiction. These are standard court levels,
# not sample records. More specialist courts can be added as the dataset expands.
COURT_SEEDS = [
    ("Supreme Court of Nigeria", "Final appellate court", "Nigeria"),
    ("Court of Appeal of Nigeria", "Appellate court", "Nigeria"),
    ("Federal High Court", "Federal trial court", "Nigeria"),
    ("National Industrial Court of Nigeria", "Specialist federal court", "Nigeria"),
    ("High Court of the Federal Capital Territory", "Superior trial court", "Nigeria"),
    ("State High Court", "State superior trial court", "Nigeria"),
    ("Magistrates' Court", "Lower court", "Nigeria"),
    ("Crown Court", "Trial court", "England and Wales"),
    ("High Court of Justice", "Superior court", "England and Wales"),
    ("Court of Appeal", "Appellate court", "England and Wales"),
    ("Supreme Court of the United Kingdom", "Final appellate court", "England and Wales"),
    ("U.S. District Court", "Federal trial court", "United States"),
    ("U.S. Court of Appeals", "Federal appellate court", "United States"),
    ("Supreme Court of the United States", "Final appellate court", "United States"),
    ("Superior Court", "Superior court", "Canada"),
    ("Court of Appeal", "Appellate court", "Canada"),
    ("Supreme Court of Canada", "Final appellate court", "Canada"),
    ("Supreme Court of New South Wales", "State superior court", "Australia"),
    ("Federal Court of Australia", "Federal superior court", "Australia"),
    ("High Court of Australia", "Final appellate court", "Australia"),
    ("High Court of Ghana", "Superior court", "Ghana"),
    ("Court of Appeal of Ghana", "Appellate court", "Ghana"),
    ("Supreme Court of Ghana", "Final appellate court", "Ghana"),
    ("High Court of South Africa", "Superior court", "South Africa"),
    ("Supreme Court of Appeal of South Africa", "Appellate court", "South Africa"),
    ("Constitutional Court of South Africa", "Constitutional court", "South Africa"),
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

        # Rename the original Nigerian placeholder in place, preserving its ID
        # and any existing case relationships.
        nigeria_id = jurisdictions["Nigeria"].id
        old_nigeria_court = db.scalar(
            select(Court).where(
                Court.name == "Federal High Court (sample)",
                Court.jurisdiction_id == nigeria_id,
            )
        )
        if old_nigeria_court is not None:
            old_nigeria_court.name = "Federal High Court"
            old_nigeria_court.level = "Federal trial court"

        # Remove "(sample)" from the original starter courts without changing IDs.
        legacy_names = {
            ("Crown Court (sample)", "England and Wales"): ("Crown Court", "Trial court"),
            ("U.S. District Court (sample)", "United States"): ("U.S. District Court", "Federal trial court"),
            ("Superior Court (sample)", "Canada"): ("Superior Court", "Superior court"),
            ("Supreme Court (sample)", "Australia"): ("Supreme Court of Australia", "Final appellate court"),
            ("High Court (sample)", "Ghana"): ("High Court of Ghana", "Superior court"),
            ("High Court (sample)", "South Africa"): ("High Court of South Africa", "Superior court"),
        }
        for (old_name, jurisdiction_name), (new_name, new_level) in legacy_names.items():
            jid = jurisdictions[jurisdiction_name].id
            old = db.scalar(select(Court).where(
                Court.name == old_name, Court.jurisdiction_id == jid
            ))
            if old is not None:
                duplicate = db.scalar(select(Court).where(
                    Court.name == new_name, Court.jurisdiction_id == jid
                ))
                if duplicate is None or duplicate.id == old.id:
                    old.name = new_name
                    old.level = new_level

        for name, level, jurisdiction_name in COURT_SEEDS:
            jid = jurisdictions[jurisdiction_name].id
            exists = db.scalar(select(Court).where(
                Court.name == name, Court.jurisdiction_id == jid
            ))
            if exists is None:
                db.add(Court(name=name, level=level, jurisdiction_id=jid))

        for name, category in STARTER_OFFENCES:
            exists = db.scalar(select(Offence).where(
                Offence.name == name, Offence.jurisdiction_id.is_(None)
            ))
            if exists is None:
                db.add(Offence(name=name, category=category, jurisdiction_id=None))
        db.commit()
    finally:
        db.close()

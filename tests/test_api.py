import sys
from pathlib import Path

# Ensure the repository root is importable when pytest is launched by CI.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Jurisdiction
from app.routes import cases, dashboard, analytics, predictions, metadata

@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(cases.router)
    app.include_router(dashboard.router)
    app.include_router(analytics.router)
    app.include_router(predictions.router)
    app.include_router(metadata.router)
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

def test_case_create_duplicate_and_filters(client):
    db_generator = client.app.dependency_overrides[get_db]()
    db = next(db_generator)
    jurisdiction = Jurisdiction(
        name="Test jurisdiction", country_code="TST", legal_system="Common law"
    )
    db.add(jurisdiction)
    db.commit()
    db.refresh(jurisdiction)
    jurisdiction_id = jurisdiction.id
    db_generator.close()

    payload = {
        "case_reference": "TEST/001",
        "title": "State v Example",
        "jurisdiction_id": jurisdiction_id,
        "decision_date": "2024-01-15",
        "summary": "A test record",
        "facts": "Test facts",
        "data_status": "researcher-entered",
    }
    created = client.post("/api/cases", json=payload)
    assert created.status_code == 201
    assert created.json()["year"] == 2024
    assert client.post("/api/cases", json=payload).status_code == 409
    filtered = client.get(
        f"/api/cases?jurisdiction_id={jurisdiction_id}&year=2024"
    )
    assert filtered.status_code == 200
    assert filtered.json()[0]["title"] == "State v Example"
    assert client.get("/api/cases/count").json()["total"] == 1

def test_unknown_case_returns_404(client):
    assert client.get("/api/cases/99999").status_code == 404

def test_analytics_empty_database_returns_empty_breakdown(client):
    response = client.get("/api/analytics/breakdown?dimension=offence")
    assert response.status_code == 200
    assert response.json() == []

def test_invalid_analytics_dimension_returns_400(client):
    assert client.get("/api/analytics/breakdown?dimension=invalid").status_code == 400

def test_prediction_rejects_unknown_jurisdiction(client):
    response = client.post("/api/predictions/estimate", json={
        "jurisdiction_id": 99999,
        "offence": "Theft",
        "facts": "A hypothetical set of facts",
    })
    assert response.status_code == 400

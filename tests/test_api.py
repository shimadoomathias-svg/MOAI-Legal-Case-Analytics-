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



def test_automated_research_uses_external_judgments_without_local_case_corpus(client, monkeypatch):
    db_generator = client.app.dependency_overrides[get_db]()
    db = next(db_generator)
    jurisdiction = Jurisdiction(
        name="Nigeria", country_code="NGA", legal_system="Common law"
    )
    db.add(jurisdiction)
    db.commit()
    db.refresh(jurisdiction)
    jurisdiction_id = jurisdiction.id
    db_generator.close()

    async def fake_search(offence, facts, court_name=None, db=None):
        return {
            "query": offence,
            "total": 1,
            "queries": [offence],
            "judgment_count": 1,
            "legislation_count": 0,
            "documents": [{
                "title": "A v B",
                "citation": "2024 NGSC 1",
                "court": "Supreme Court of Nigeria",
                "url": "https://openlegal.casewinai.com/judgments/example",
                "source": "OpenLegal Nigeria",
                "source_id": "example",
                "text": "Holding: Example holding"
            }]
        }

    async def fake_assessment(payload, jurisdiction_name, research):
        assert jurisdiction_name == "Nigeria"
        assert len(research["documents"]) == 1
        return {"status": "generated", "assessment": "Conditional assessment"}

    monkeypatch.setattr(predictions, "search_openlegal_nigeria", fake_search)
    monkeypatch.setattr(predictions, "assess_researched_case", fake_assessment)

    response = client.post("/api/predictions/research", json={
        "jurisdiction_id": jurisdiction_id,
        "offence": "Armed robbery",
        "facts": "The accused allegedly used a firearm during a robbery."
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "research_completed"
    assert data["retrieved_judgment_count"] == 1
    assert data["research_results"][0]["citation"] == "2024 NGSC 1"
    assert data["ai_prediction"]["status"] == "generated"


def test_automated_research_does_not_claim_unconnected_jurisdiction_support(client):
    db_generator = client.app.dependency_overrides[get_db]()
    db = next(db_generator)
    jurisdiction = Jurisdiction(
        name="England and Wales", country_code="GB-ENG", legal_system="Common law"
    )
    db.add(jurisdiction)
    db.commit()
    db.refresh(jurisdiction)
    jurisdiction_id = jurisdiction.id
    db_generator.close()

    response = client.post("/api/predictions/research", json={
        "jurisdiction_id": jurisdiction_id,
        "offence": "Theft",
        "facts": "A hypothetical theft case."
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "source_not_connected"
    assert data["research_results"] == []



def test_external_source_text_extraction_and_relevance_ranking():
    source = {
        "title": "State v Example",
        "holding": "The Supreme Court considered armed robbery and proof beyond reasonable doubt.",
        "full_text": "The appeal was dismissed."
    }
    extracted = predictions._flatten_text(source)
    assert "armed robbery" in extracted.lower()
    score = predictions._relevance_score(
        predictions.terms("armed robbery proof beyond reasonable doubt"),
        {"title": "State v Example", "text": extracted}
    )
    assert score > 0


def test_external_source_cache_expiry():
    from datetime import datetime, timedelta
    from app.models import ExternalLegalSource

    fresh = ExternalLegalSource(
        provider="OpenLegal Nigeria", source_id="case-1",
        material_type="judgment", content="judgment text",
        retrieved_at=datetime.utcnow()
    )
    stale = ExternalLegalSource(
        provider="OpenLegal Nigeria", source_id="law-1",
        material_type="legislation", content="old statutory text",
        retrieved_at=datetime.utcnow() - timedelta(days=2)
    )
    assert predictions._cache_is_fresh(fresh, 30)
    assert not predictions._cache_is_fresh(stale, 1)



def test_openlegal_connector_searches_judgments_and_legislation(monkeypatch):
    import asyncio

    requested_queries = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, headers=None):
            if url.endswith("/judgments"):
                requested_queries.append(params["q"])
                return FakeResponse({
                    "total": 1,
                    "results": [{
                        "id": "ngsc-example-1",
                        "title": "State v Example",
                        "cite_as": "2024 NGSC 1",
                        "court": "Supreme Court of Nigeria",
                        "holding": "Armed robbery requires proof beyond reasonable doubt.",
                        "excerpt": "The appeal concerned armed robbery.",
                        "url": "https://openlegal.casewinai.com/judgments/ngsc-example-1"
                    }]
                })
            if url.endswith("/judgments/ngsc-example-1"):
                return FakeResponse({
                    "full_text": "The Supreme Court dismissed the appeal.",
                    "issues": ["Proof of armed robbery"],
                    "holding": "The conviction was affirmed."
                })
            if url.endswith("/laws"):
                return FakeResponse({
                    "results": [{
                        "id": "robbery-act-section-1",
                        "title": "Robbery and Firearms Act",
                        "section": "Section 1",
                        "text": "Any person who commits armed robbery..."
                    }]
                })
            raise AssertionError("Unexpected OpenLegal endpoint: " + url)

    monkeypatch.setattr(predictions.httpx, "AsyncClient", FakeAsyncClient)
    result = asyncio.run(predictions.search_openlegal_nigeria(
        "Armed robbery",
        "The accused used a firearm during the robbery.",
        db=None
    ))

    assert len(requested_queries) >= 2
    assert requested_queries[0] == "Armed robbery"
    assert result["judgment_count"] == 1
    assert result["legislation_count"] == 1
    assert result["documents"][0]["material_type"] in {"judgment", "legislation"}
    assert any("dismissed the appeal" in d["text"] for d in result["documents"])
    assert any(d["material_type"] == "legislation" for d in result["documents"])



def test_courtlistener_connector_retrieves_full_opinion(monkeypatch):
    import asyncio

    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, headers=None):
            assert headers["Authorization"] == "Token test-token"
            if url.endswith("/search/"):
                assert params["type"] == "o"
                return FakeResponse({
                    "count": 1,
                    "results": [{
                        "caseName": "Example v State",
                        "caseNameFull": "Example v. State",
                        "citation": ["600 U.S. 1"],
                        "court": "Supreme Court of the United States",
                        "cluster_id": 12345,
                        "absolute_url": "/opinion/12345/example-v-state/",
                        "opinions": [{"id": 67890, "type": "lead-opinion"}]
                    }]
                })
            if url.endswith("/opinions/67890/"):
                return FakeResponse({
                    "html_with_citations": "<p>The Court affirmed the judgment.</p>"
                })
            raise AssertionError("Unexpected CourtListener endpoint: " + url)

    monkeypatch.setattr(predictions.httpx, "AsyncClient", FakeAsyncClient)
    result = asyncio.run(predictions.search_courtlistener_us(
        "constitutional challenge", "The appellant challenged a federal statute."
    ))

    assert result["judgment_count"] == 1
    assert result["documents"][0]["source"] == "CourtListener"
    assert "affirmed the judgment" in result["documents"][0]["text"]
    assert result["documents"][0]["citation"] == "600 U.S. 1"


def test_us_research_requires_courtlistener_token(client, monkeypatch):
    monkeypatch.delenv("COURTLISTENER_API_TOKEN", raising=False)
    db_generator = client.app.dependency_overrides[get_db]()
    db = next(db_generator)
    jurisdiction = Jurisdiction(
        name="United States", country_code="USA",
        legal_system="Common law / mixed state systems"
    )
    db.add(jurisdiction)
    db.commit()
    db.refresh(jurisdiction)
    jurisdiction_id = jurisdiction.id
    db_generator.close()

    response = client.post("/api/predictions/research", json={
        "jurisdiction_id": jurisdiction_id,
        "offence": "Constitutional challenge",
        "facts": "A challenge to a federal statute."
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "source_not_configured"
    assert data["source_provider"] == "CourtListener"



def test_setup_status_never_exposes_secret_values(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-openrouter-secret")
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "private-courtlistener-secret")
    response = client.get("/api/predictions/setup-status")
    assert response.status_code == 200
    payload = response.json()
    rendered = str(payload)
    assert "private-openrouter-secret" not in rendered
    assert "private-courtlistener-secret" not in rendered
    assert payload["ai_provider"]["ready"] is True
    assert payload["legal_sources"][0]["ready"] is True
    courtlistener = next(x for x in payload["legal_sources"] if x["name"] == "CourtListener")
    assert courtlistener["ready"] is True


def test_no_retrieved_material_blocks_ai_prediction(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    result = asyncio.run(predictions.assess_researched_case(
        SimpleNamespace(
            offence="Test offence", facts="Test facts",
            aggravating_factors=[], mitigating_factors=[]
        ),
        "Nigeria",
        {"documents": []}
    ))
    assert result["status"] == "insufficient_evidence"


def test_retrieval_relevance_measures_query_coverage_not_document_length():
    issue_terms = predictions.terms("murder self defence eyewitness")
    short = {"title": "Murder self defence", "text": "eyewitness evidence"}
    long = {
        "title": "Murder self defence",
        "text": "eyewitness evidence " + ("unrelated procedural discussion " * 500)
    }
    assert predictions._relevance_score(issue_terms, short) == 100.0
    assert predictions._relevance_score(issue_terms, long) == 100.0


def test_retrieval_relevance_can_include_fact_pattern_terms():
    issue_terms = predictions.terms("murder self defence")
    facts = predictions.terms("wooden object hospital eyewitness")
    document = {
        "title": "State v Example",
        "text": "Murder self defence eyewitness evidence after hospital treatment with wooden object"
    }
    score = predictions._relevance_score(issue_terms, document, facts)
    assert score > 80

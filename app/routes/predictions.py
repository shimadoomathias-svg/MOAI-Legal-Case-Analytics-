import asyncio
import os
import re
from html.parser import HTMLParser
from datetime import datetime, timezone
from statistics import median

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import (
    CaseRecord, CaseOffence, Offence, CaseOutcome, Jurisdiction, Court, CaseFactor,
    ExternalLegalSource
)
from ..schemas import PredictionRequest

router = APIRouter(prefix="/api/predictions", tags=["Predictions"])
MINIMUM_COMPARABLE_CASES = 10
AI_TIMEOUT_SECONDS = 60

STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "was", "were",
    "has", "had", "have", "into", "upon", "where", "when", "which",
    "their", "there", "under", "over", "case", "court", "appellant",
    "respondent", "defendant", "prosecution", "accused"
}


def terms(value: str) -> set[str]:
    return {
        x for x in re.findall(r"[a-z0-9]{3,}", (value or "").lower())
        if x not in STOP_WORDS
    }


def similarity_score(hypothetical_terms: set[str], case: CaseRecord):
    if not hypothetical_terms:
        return None
    material = terms(case.facts)
    for factor in case.factors:
        material |= terms(factor.category + " " + factor.description)
    if not material:
        return 0.0
    union = hypothetical_terms | material
    return round(len(hypothetical_terms & material) / len(union) * 100, 1) if union else 0.0


async def generate_ai_prediction(payload, comparable_cases, outcome_distribution, sentence_statistics):
    """Ask the configured free OpenRouter model to interpret the supplied evidence."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return {
            "status": "not_configured",
            "message": "AI prediction is unavailable because OPENROUTER_API_KEY is not configured."
        }

    model = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    if not (model == "openrouter/free" or model.endswith(":free")):
        return {
            "status": "invalid_model_configuration",
            "message": "AI prediction is disabled because this application permits free OpenRouter models only."
        }

    evidence = {
        "jurisdiction_id": payload.jurisdiction_id,
        "offence": payload.offence,
        "court_id": payload.court_id,
        "hypothetical_facts": payload.facts,
        "aggravating_factors": payload.aggravating_factors,
        "mitigating_factors": payload.mitigating_factors,
        "recorded_outcome_distribution": outcome_distribution,
        "recorded_sentence_statistics_months": sentence_statistics,
        "most_relevant_sourced_cases": comparable_cases[:15],
    }
    system_prompt = (
        "You are an evidence-led legal case outcome research assistant. "
        "Assess a hypothetical case using ONLY the supplied dataset. "
        "Do not invent case names, citations, statutes, facts, statistics, or legal rules. "
        "Do not treat lexical similarity as proof of legal similarity. "
        "Clearly distinguish observed dataset patterns from your cautious interpretation. "
        "Give a likely outcome only as a conditional, non-guaranteed research assessment. "
        "Discuss material aggravating and mitigating factors, explain what evidence is missing, "
        "and state when the data does not support a defensible prediction. "
        "Cite supporting cases only by the exact titles and citations supplied. "
        "Do not provide legal advice. Use concise headings: "
        "Provisional outcome assessment; Why; Supporting comparable cases; "
        "Factors that may change the assessment; Confidence and limitations."
    )
    try:
        async with httpx.AsyncClient(timeout=AI_TIMEOUT_SECONDS) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": os.getenv(
                        "APP_PUBLIC_URL",
                        "https://moai-legal-case-analytics.onrender.com"
                    ),
                    "X-Title": "MOAI Legal Case Analytics",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": "Assess this hypothetical case from the following evidence. "
                                       "Return a reasoned assessment, not a guaranteed result.\n\n"
                                       + __import__("json").dumps(evidence, ensure_ascii=False)
                        },
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1200,
                },
            )
        if response.status_code == 429:
            return {"status": "rate_limited", "message": "The free AI request limit has been reached. Try again later."}
        if response.status_code >= 400:
            return {"status": "provider_error", "message": "The AI provider could not complete the prediction. Statistical results are still available."}
        data = response.json()
        answer = data.get("choices", [{}])[0].get("message", {}).get("content")
        if not answer:
            return {"status": "empty_response", "message": "The AI provider returned no prediction."}
        return {
            "status": "generated",
            "provider": "OpenRouter",
            "model": data.get("model", model),
            "assessment": answer,
            "evidence_case_count": len(comparable_cases),
        }
    except httpx.TimeoutException:
        return {"status": "timeout", "message": "The AI prediction timed out. Please try again."}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {"status": "provider_error", "message": "The AI provider is temporarily unavailable. Statistical results are still available."}


@router.get("/status")
def prediction_status():
    return {
        "status": "ai_and_statistical_prediction",
        "minimum_comparable_cases": MINIMUM_COMPARABLE_CASES,
        "ai_configured": bool(os.getenv("OPENROUTER_API_KEY")),
        "ai_model": os.getenv("OPENROUTER_MODEL", "openrouter/free"),
        "method": (
            "Same-jurisdiction exact-offence cohort, with optional same-court restriction; "
            "transparent lexical similarity ranks records; a free OpenRouter AI model "
            "interprets the hypothetical facts against the sourced case cohort and statistics."
        ),
        "warning": "Research assessment only. It is conditional, dataset-dependent, and not a guaranteed court outcome or legal advice."
    }



OPENLEGAL_API = "https://openlegal.casewinai.com/api/v1"


def _flatten_text(value, limit=14000):
    """Extract readable legal text from a source JSON response without assuming one schema."""
    chunks = []
    preferred = {"title", "cite_as", "suit_number", "court", "holding", "issues",
                 "excerpt", "summary", "full_text", "text", "judgment", "content",
                 "statutes", "cases_cited", "date", "decision_date", "body", "section",
                 "section_text", "section_title", "provision", "statute", "law", "law_name", "name"}
    def walk(node, key=""):
        if len("\n".join(chunks)) >= limit:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if k.lower() in preferred and isinstance(v, (str, int, float)):
                    chunks.append(f"{k}: {v}")
                elif isinstance(v, (dict, list)):
                    walk(v, k)
        elif isinstance(node, list):
            for item in node[:30]:
                walk(item, key)
        elif isinstance(node, str) and key.lower() in preferred:
            chunks.append(f"{key}: {node}")
    walk(value)
    return "\n".join(dict.fromkeys(chunks))[:limit]


def _cache_is_fresh(record, max_age_days):
    if record is None or not record.content or record.retrieved_at is None:
        return False
    stored = record.retrieved_at.replace(tzinfo=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (now - stored).total_seconds() < max_age_days * 86400


def _relevance_score(query_terms, document):
    searchable = " ".join([
        str(document.get("title", "")),
        str(document.get("citation", "")),
        str(document.get("court", "")),
        str(document.get("text", "")),
    ])
    found = terms(searchable)
    if not query_terms or not found:
        return 0.0
    return round(100 * len(query_terms & found) / len(query_terms | found), 1)


async def search_openlegal_nigeria(offence, facts, court_name=None, db=None):
    """Search and retrieve public Nigerian judgments and legislation via OpenLegal's documented API."""
    fact_words = [w for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", facts or "")
                  if w.lower() not in STOP_WORDS]
    distinct_fact_words = list(dict.fromkeys(fact_words))
    query_candidates = [
        offence.strip(),
        " ".join([offence.strip()] + distinct_fact_words[:8]),
    ]
    queries = list(dict.fromkeys(q for q in query_candidates if q))
    query_terms = terms(offence + " " + (facts or ""))
    headers = {"Accept": "application/json", "User-Agent": "MOAI-Legal-Case-Analytics/1.0"}
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        async def fetch_search(query):
            params = {"q": query, "limit": 6, "page": 1}
            if court_name:
                params["court"] = court_name
            response = await client.get(
                f"{OPENLEGAL_API}/judgments", params=params, headers=headers
            )
            response.raise_for_status()
            data = response.json()
            rows = data.get("results", []) if isinstance(data, dict) else data
            return rows if isinstance(rows, list) else [], (
                data.get("total", len(rows)) if isinstance(data, dict) else len(rows)
            )

        search_responses = await asyncio.gather(*(fetch_search(q) for q in queries))
        rows_by_id = {}
        total_matches = 0
        for rows, total in search_responses:
            total_matches += int(total or 0)
            for row in rows:
                if isinstance(row, dict) and row.get("id"):
                    rows_by_id.setdefault(str(row["id"]), row)

        # Fetch the strongest candidate summaries first; source ranking is only
        # a retrieval aid and is never represented as legal similarity.
        ranked_rows = sorted(
            rows_by_id.values(),
            key=lambda row: _relevance_score(query_terms, {
                "title": row.get("title", ""),
                "citation": row.get("cite_as", ""),
                "court": row.get("court", ""),
                "text": " ".join(str(row.get(k, "")) for k in ("holding", "excerpt")),
            }),
            reverse=True,
        )[:10]

        semaphore = asyncio.Semaphore(4)
        async def retrieve_judgment(row):
            source_id = str(row["id"])
            cached = None
            if db is not None:
                cached = db.query(ExternalLegalSource).filter_by(
                    provider="OpenLegal Nigeria", source_id=source_id,
                    material_type="judgment"
                ).first()
            if _cache_is_fresh(cached, 30):
                return {
                    "title": cached.title, "citation": cached.citation,
                    "court": cached.court, "url": cached.url,
                    "source": cached.provider, "source_id": source_id,
                    "material_type": "judgment", "text": cached.content,
                    "cached": True,
                }

            detail = {}
            async with semaphore:
                try:
                    detail_response = await client.get(
                        f"{OPENLEGAL_API}/judgments/{source_id}", headers=headers
                    )
                    if detail_response.status_code < 400:
                        detail = detail_response.json()
                except (httpx.HTTPError, ValueError):
                    detail = {}
            merged = {**row, **(detail if isinstance(detail, dict) else {})}
            title = merged.get("title") or "Untitled judgment"
            citation = (merged.get("cite_as") or merged.get("suit_number") or "")
            court = merged.get("court") or ""
            url = merged.get("url") or (
                f"https://openlegal.casewinai.com/judgments/{source_id}"
            )
            text = _flatten_text(merged)[:14000]
            if db is not None:
                record = cached or ExternalLegalSource(
                    provider="OpenLegal Nigeria", source_id=source_id,
                    material_type="judgment"
                )
                record.title, record.citation, record.court = title, citation, court
                record.url, record.content = url, text
                record.retrieved_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.add(record)
            doc = {
                "title": title, "citation": citation, "court": court,
                "url": url, "source": "OpenLegal Nigeria", "source_id": source_id,
                "material_type": "judgment", "text": text, "cached": False,
            }
            doc["relevance_score"] = _relevance_score(query_terms, doc)
            return doc

        judgment_docs = await asyncio.gather(*(retrieve_judgment(row) for row in ranked_rows))

        # Search statutory sections using both the offence and the principal
        # factual terms. Legislation search is allowed to fail independently.
        law_queries = list(dict.fromkeys([
            offence.strip(),
            " ".join(distinct_fact_words[:6]),
        ]))
        law_rows_by_id = {}
        for law_query in law_queries:
            if not law_query:
                continue
            try:
                law_response = await client.get(
                    f"{OPENLEGAL_API}/laws",
                    params={"q": law_query, "limit": 5},
                    headers=headers,
                )
                if law_response.status_code < 400:
                    law_payload = law_response.json()
                    law_rows = law_payload.get("results", []) if isinstance(law_payload, dict) else law_payload
                    if isinstance(law_rows, list):
                        for law in law_rows:
                            if isinstance(law, dict):
                                identity = str(law.get("id") or (
                                    law.get("title", "") + law.get("section", "")
                                ))
                                if identity:
                                    law_rows_by_id.setdefault(identity, law)
            except (httpx.HTTPError, ValueError):
                continue

        law_docs = []
        for identity, law in list(law_rows_by_id.items())[:8]:
            law_id = str(law.get("id") or identity)
            cached = None
            if db is not None and law.get("id"):
                cached = db.query(ExternalLegalSource).filter_by(
                    provider="OpenLegal Nigeria", source_id=law_id,
                    material_type="legislation"
                ).first()
            if _cache_is_fresh(cached, 1):
                law_doc = {
                    "title": cached.title, "citation": cached.citation,
                    "court": "", "url": cached.url, "source": cached.provider,
                    "source_id": law_id, "material_type": "legislation",
                    "text": cached.content, "cached": True,
                }
            else:
                law_doc = {
                    "title": law.get("title") or law.get("name") or law.get("law") or "Legislation section",
                    "citation": law.get("citation") or law.get("section") or law.get("cite_as") or "",
                    "court": "", "url": law.get("url") or "",
                    "source": "OpenLegal Nigeria", "source_id": law_id,
                    "material_type": "legislation",
                    "text": _flatten_text(law)[:6000], "cached": False,
                }
                if db is not None and law.get("id"):
                    record = cached or ExternalLegalSource(
                        provider="OpenLegal Nigeria", source_id=law_id,
                        material_type="legislation"
                    )
                    record.title = law_doc["title"]
                    record.citation = law_doc["citation"]
                    record.court = ""
                    record.url = law_doc["url"]
                    record.content = law_doc["text"]
                    record.retrieved_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    db.add(record)
            law_doc["relevance_score"] = _relevance_score(query_terms, law_doc)
            law_docs.append(law_doc)

        if db is not None:
            db.commit()

        documents = sorted(
            judgment_docs + law_docs,
            key=lambda doc: doc.get("relevance_score", 0),
            reverse=True,
        )
        return {
            "query": queries[0] if queries else offence,
            "queries": queries,
            "total": total_matches,
            "documents": documents,
            "judgment_count": len(judgment_docs),
            "legislation_count": len(law_docs),
            "cache_hits": sum(1 for doc in documents if doc.get("cached")),
        }


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        if data and data.strip():
            self.parts.append(data.strip())


def _html_to_text(value):
    parser = _HTMLTextExtractor()
    try:
        parser.feed(value or "")
        return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


async def search_courtlistener_us(offence, facts, db=None):
    """Search US published opinions through the authenticated CourtListener v4 API."""
    token = os.getenv("COURTLISTENER_API_TOKEN")
    if not token:
        return {
            "status": "not_configured",
            "message": "United States research requires a CourtListener API token in the deployment environment.",
            "query": offence, "queries": [offence], "total": 0,
            "documents": [], "judgment_count": 0, "legislation_count": 0,
            "cache_hits": 0,
        }

    fact_words = [
        word for word in re.findall(r"[A-Za-z][A-Za-z-]{3,}", facts or "")
        if word.lower() not in STOP_WORDS
    ]
    query = " ".join([offence.strip()] + list(dict.fromkeys(fact_words[:6])))
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "User-Agent": "MOAI-Legal-Case-Analytics/1.0",
    }
    base = "https://www.courtlistener.com/api/rest/v4"
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        response = await client.get(
            f"{base}/search/", params={"q": query, "type": "o"}, headers=headers
        )
        if response.status_code == 401:
            return {
                "status": "authentication_failed",
                "message": "CourtListener rejected the configured API token.",
                "query": query, "queries": [query], "total": 0,
                "documents": [], "judgment_count": 0, "legislation_count": 0,
                "cache_hits": 0,
            }
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            rows = []

        # Search results are already ranked by CourtListener's search engine.
        # Keep the request budget below the documented five requests/minute.
        selected_rows = rows[:3]
        query_terms = terms(offence + " " + (facts or ""))
        documents = []
        cache_hits = 0
        for row in selected_rows:
            if not isinstance(row, dict):
                continue
            opinions = row.get("opinions") or []
            opinion = next(
                (item for item in opinions if isinstance(item, dict)
                 and "lead" in str(item.get("type", "")).lower()),
                next((item for item in opinions if isinstance(item, dict)), {})
            )
            opinion_id = opinion.get("id")
            cluster_id = row.get("cluster_id")
            if not opinion_id:
                continue
            source_id = f"{cluster_id or 'cluster'}:{opinion_id}"
            cached = None
            if db is not None:
                cached = db.query(ExternalLegalSource).filter_by(
                    provider="CourtListener", source_id=source_id,
                    material_type="judgment"
                ).first()
            if _cache_is_fresh(cached, 30):
                cache_hits += 1
                text_content = cached.content
                title, citation, court, url = (
                    cached.title, cached.citation, cached.court, cached.url
                )
                completeness = "cached_opinion_text"
            else:
                detail = {}
                detail_response = await client.get(
                    f"{base}/opinions/{opinion_id}/", headers=headers
                )
                if detail_response.status_code < 400:
                    detail = detail_response.json()
                title = row.get("caseNameFull") or row.get("caseName") or "Untitled opinion"
                citations = row.get("citation") or []
                citation = "; ".join(str(item) for item in citations) if isinstance(citations, list) else str(citations)
                court = row.get("court") or ""
                absolute_url = row.get("absolute_url") or ""
                url = absolute_url if absolute_url.startswith("http") else (
                    "https://www.courtlistener.com" + absolute_url
                    if absolute_url else f"https://www.courtlistener.com/opinion/{cluster_id}/"
                )
                html_text = detail.get("html_with_citations") or detail.get("html") or ""
                text_content = _html_to_text(html_text)
                completeness = "full_opinion_text"
                if not text_content:
                    text_content = detail.get("plain_text") or opinion.get("snippet") or row.get("snippet") or ""
                    completeness = "search_snippet_only"
                if db is not None and text_content:
                    record = cached or ExternalLegalSource(
                        provider="CourtListener", source_id=source_id,
                        material_type="judgment"
                    )
                    record.title, record.citation = title, citation
                    record.court, record.url, record.content = court, url, text_content[:14000]
                    record.retrieved_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    db.add(record)

            document = {
                "title": title, "citation": citation, "court": court,
                "url": url, "source": "CourtListener",
                "source_id": source_id, "material_type": "judgment",
                "text": text_content[:14000],
                "content_completeness": completeness,
            }
            document["relevance_score"] = _relevance_score(query_terms, document)
            documents.append(document)

        if db is not None:
            db.commit()
        documents.sort(key=lambda item: item.get("relevance_score", 0), reverse=True)
        return {
            "status": "research_completed" if documents else "no_matches",
            "query": query, "queries": [query],
            "total": payload.get("count", len(rows)),
            "documents": documents,
            "judgment_count": len(documents),
            "legislation_count": 0,
            "cache_hits": cache_hits,
        }


async def assess_researched_case(payload, jurisdiction_name, research):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return {"status": "not_configured",
                "message": "Legal judgments were retrieved, but OPENROUTER_API_KEY is not configured for AI analysis."}
    model = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    if not (model == "openrouter/free" or model.endswith(":free")):
        return {"status": "invalid_model_configuration",
                "message": "Only OpenRouter free models are enabled."}
    # Bound the prompt size while preserving the highest-ranked source material.
    ranked_judgments = sorted(
        [d for d in research["documents"] if d.get("material_type") == "judgment"],
        key=lambda d: d.get("relevance_score", 0), reverse=True
    )[:5]
    ranked_laws = sorted(
        [d for d in research["documents"] if d.get("material_type") == "legislation"],
        key=lambda d: d.get("relevance_score", 0), reverse=True
    )[:3]
    selected_material = []
    for source in ranked_judgments + ranked_laws:
        selected_material.append({
            **{k: source.get(k) for k in (
                "title", "citation", "court", "url", "source",
                "material_type", "relevance_score"
            )},
            "text": (source.get("text") or "")[
                :7000 if source.get("material_type") == "judgment" else 3500
            ],
        })
    evidence = {
        "jurisdiction": jurisdiction_name,
        "offence_or_legal_issue": payload.offence,
        "submitted_case_facts": payload.facts,
        "aggravating_factors": payload.aggravating_factors,
        "mitigating_factors": payload.mitigating_factors,
        "retrieved_legal_material": selected_material,
    }
    system = (
        "You are an evidence-grounded legal research and case-outcome assessment assistant. "
        "Use only the submitted facts and retrieved judgments and legislation below. Do not invent case names, "
        "citations, holdings, statutory provisions, sentencing figures, or legal rules. "
        "Distinguish what the judgments actually say from your inference. Explain material "
        "similarities and differences, procedural posture, court level, and missing facts. "
        "Give a cautious conditional assessment of plausible outcomes, not a probability "
        "unless the supplied evidence supports a real statistical calculation. Never call this "
        "a trained predictive model. If sources are too few or weak, say the evidence is "
        "insufficient rather than guessing. Cite each authority using the supplied citation "
        "and URL. Mention that OpenLegal is a research source and certified court copies and "
        "official legislation must be checked. This is not legal advice."
    )
    try:
        async with httpx.AsyncClient(timeout=65) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json",
                         "HTTP-Referer": os.getenv("APP_PUBLIC_URL",
                             "https://moai-legal-case-analytics.onrender.com"),
                         "X-Title": "MOAI Legal Case Analytics"},
                json={"model": model,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content":
                                    "Research and assess this case using the following retrieved primary-source material:\n"
                                    + __import__("json").dumps(evidence, ensure_ascii=False)}],
                      "temperature": 0.1, "max_tokens": 1800},
            )
        if response.status_code == 429:
            return {"status": "rate_limited", "message": "OpenRouter free-model rate limit reached. Try again later."}
        if response.status_code >= 400:
            return {"status": "provider_error", "message": "OpenRouter could not complete the analysis."}
        data = response.json()
        answer = data.get("choices", [{}])[0].get("message", {}).get("content")
        if not answer:
            return {"status": "empty_response", "message": "The AI provider returned no assessment."}
        return {"status": "generated", "provider": "OpenRouter",
                "model": data.get("model", model), "assessment": answer}
    except httpx.TimeoutException:
        return {"status": "timeout", "message": "The AI analysis timed out."}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {"status": "provider_error", "message": "The AI provider is temporarily unavailable."}


@router.post("/research")
async def automated_legal_research(payload: PredictionRequest, db: Session = Depends(get_db)):
    """One submitted case triggers source retrieval and AI evidence analysis; no manual case corpus required."""
    jurisdiction = db.get(Jurisdiction, payload.jurisdiction_id)
    if jurisdiction is None:
        raise HTTPException(status_code=400, detail="Unknown jurisdiction_id")
    if payload.court_id is not None:
        court = db.get(Court, payload.court_id)
        if court is None or court.jurisdiction_id != payload.jurisdiction_id:
            raise HTTPException(status_code=400, detail="Court must belong to the selected jurisdiction")
    country_code = jurisdiction.country_code.upper()
    court_name = None
    if payload.court_id is not None:
        court_name = db.get(Court, payload.court_id).name

    if country_code == "NGA":
        source_provider = "OpenLegal Nigeria"
        try:
            research = await search_openlegal_nigeria(
                payload.offence, payload.facts, court_name, db
            )
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"OpenLegal Nigeria returned HTTP {exc.response.status_code}."
            )
        except (httpx.HTTPError, ValueError):
            raise HTTPException(
                status_code=502,
                detail="Could not reach the OpenLegal Nigeria legal research API."
            )
    elif country_code == "USA":
        source_provider = "CourtListener"
        research = await search_courtlistener_us(payload.offence, payload.facts, db)
        if research["status"] in {"not_configured", "authentication_failed"}:
            return {
                "status": "source_not_configured",
                "jurisdiction": jurisdiction.name,
                "source_provider": source_provider,
                "message": research["message"],
                "research_results": [],
                "search_queries": research.get("queries", []),
                "retrieved_judgment_count": 0,
                "retrieved_legislation_count": 0,
                "ai_prediction": {"status": "not_run", "message": research["message"]},
                "limitations": [
                    "A valid CourtListener API token is required for United States source retrieval.",
                    "Only published case-law opinions are searched by the current connector."
                ]
            }
    else:
        return {
            "status": "source_not_connected",
            "jurisdiction": jurisdiction.name,
            "message": (
                "Automated source retrieval is not yet enabled for this jurisdiction. "
                "A permitted legal-data API or licence must be connected first. "
                "The application will not scrape sources that prohibit automated access."
            ),
            "research_sources": [], "research_results": [],
            "ai_prediction": {
                "status": "not_run",
                "message": "No authorised source connector is available for this jurisdiction."
            }
        }

    if research.get("status") == "authentication_failed":
        return {
            "status": "source_authentication_failed",
            "jurisdiction": jurisdiction.name,
            "source_provider": source_provider,
            "message": research.get("message", "The legal source rejected authentication."),
            "research_results": [],
            "ai_prediction": {"status": "not_run", "message": "Source authentication failed."}
        }
    ai_result = await assess_researched_case(payload, jurisdiction.name, research)
    sources = [{"title": d["title"], "citation": d["citation"], "court": d["court"],
                "url": d["url"], "source": d["source"], "material_type": d.get("material_type", "judgment"),
                "relevance_score": d.get("relevance_score", 0)} for d in research["documents"]]
    return {
        "status": "research_completed" if research["documents"] else "no_matches",
        "jurisdiction": jurisdiction.name,
        "source_provider": source_provider,
        "search_query": research["query"],
        "search_queries": research.get("queries", [research["query"]]),
        "cached_source_count": research.get("cache_hits", 0),
        "source_total_matches": research["total"],
        "retrieved_judgment_count": research.get("judgment_count", len(research["documents"])),
        "retrieved_legislation_count": research.get("legislation_count", 0),
        "research_results": sources,
        "ai_prediction": ai_result,
        "limitations": [
            "This is retrieval-augmented legal analysis, not a trained machine-learning model.",
            "Search results depend on the judgments available in the connected source; absence of a result does not mean no authority exists.",
            "A legal research assessment is not a statistical probability or guaranteed court outcome.",
            "Verify judgments against certified court copies and legislation against official gazettes.",
            "The CourtListener connector searches United States opinions; it does not retrieve United States legislation."
        ]
    }


@router.post("/estimate")
async def estimate_outcome(payload: PredictionRequest, db: Session = Depends(get_db)):
    if db.get(Jurisdiction, payload.jurisdiction_id) is None:
        raise HTTPException(status_code=400, detail="Unknown jurisdiction_id")
    if payload.court_id is not None:
        court = db.get(Court, payload.court_id)
        if court is None or court.jurisdiction_id != payload.jurisdiction_id:
            raise HTTPException(status_code=400, detail="Court must belong to the selected jurisdiction")

    offence_name = payload.offence.strip()
    stmt = (
        select(CaseRecord)
        .join(CaseOffence, CaseOffence.case_id == CaseRecord.id)
        .join(Offence, Offence.id == CaseOffence.offence_id)
        .where(
            CaseRecord.jurisdiction_id == payload.jurisdiction_id,
            CaseRecord.data_status == "researcher-entered",
            CaseRecord.sources.any(),
            func.lower(Offence.name) == offence_name.lower(),
            func.lower(CaseOffence.role).in_(["charged", "convicted"])
        )
        .options(
            selectinload(CaseRecord.court),
            selectinload(CaseRecord.outcomes).selectinload(CaseOutcome.sentences),
            selectinload(CaseRecord.factors)
        )
        .order_by(CaseRecord.decision_date.desc(), CaseRecord.id.desc())
    )
    if payload.court_id is not None:
        stmt = stmt.where(CaseRecord.court_id == payload.court_id)
    cases = db.scalars(stmt).unique().all()

    hypothetical_terms = terms(
        payload.facts + " " +
        " ".join(payload.aggravating_factors + payload.mitigating_factors)
    )
    comparable = []
    outcome_counts = {}
    sentence_months = []
    factor_patterns = {"aggravating": {}, "mitigating": {}, "neutral": {}}

    for case in cases:
        case_outcomes = [o.outcome_type.lower() for o in case.outcomes]
        for outcome in case_outcomes:
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        for outcome in case.outcomes:
            if outcome.outcome_type.lower() in ("conviction", "appeal_dismissed"):
                for sentence in outcome.sentences:
                    if sentence.duration_months is not None:
                        sentence_months.append(float(sentence.duration_months))
        factor_list = []
        for factor in case.factors:
            factor_patterns.setdefault(factor.factor_type, {})
            factor_patterns[factor.factor_type][factor.category] = (
                factor_patterns[factor.factor_type].get(factor.category, 0) + 1
            )
            factor_list.append({
                "type": factor.factor_type,
                "category": factor.category,
                "description": factor.description
            })
        score = similarity_score(hypothetical_terms, case)
        comparable.append({
            "case_id": case.id,
            "title": case.title,
            "citation": case.case_reference,
            "decision_date": case.decision_date.isoformat() if case.decision_date else None,
            "court": case.court.name if case.court else None,
            "facts": case.facts[:2500],
            "outcomes": case_outcomes,
            "factors": factor_list,
            "similarity_score": score
        })

    comparable.sort(
        key=lambda x: (
            x["similarity_score"] is not None,
            x["similarity_score"] or 0,
            x["decision_date"] or ""
        ),
        reverse=True
    )
    count = len(cases)
    if count >= 50:
        sample_indicator = "Larger sample"
    elif count >= 25:
        sample_indicator = "Moderate sample"
    elif count >= MINIMUM_COMPARABLE_CASES:
        sample_indicator = "Limited sample"
    else:
        sample_indicator = "Insufficient sample"

    base = {
        "jurisdiction_id": payload.jurisdiction_id,
        "offence": offence_name,
        "court_id": payload.court_id,
        "comparable_case_count": count,
        "minimum_required": MINIMUM_COMPARABLE_CASES,
        "comparable_cases": comparable[:25],
        "factor_patterns": factor_patterns,
        "sample_adequacy": sample_indicator,
        "method": (
            "Exact offence name and same jurisdiction; optional same-court restriction. "
            "Similarity ranking uses Jaccard overlap of words in supplied hypothetical facts "
            "and factors against recorded case facts and factors. The AI interprets the "
            "supplied evidence and cohort statistics; it does not independently verify judgments."
        ),
        "limitations": [
            "Only researcher-entered records with at least one source entry are included; source content is not independently certified.",
            "Exact offence matching can omit cases recorded under a different offence label or statutory provision.",
            "Lexical similarity is a text-overlap aid, not a validated legal similarity or machine-learning score.",
            "Recorded factor frequencies show association in this dataset and do not establish causation.",
            "Missing, selective or inconsistent data can materially affect results.",
            "Cross-court legal and sentencing differences may remain within one jurisdiction.",
            "AI output is conditional research analysis, not legal advice or a guaranteed prediction."
        ]
    }

    if count < MINIMUM_COMPARABLE_CASES:
        return {
            **base,
            "status": "insufficient_data",
            "message": (
                f"Only {count} sourced researcher-entered comparable case record(s) were found. "
                f"At least {MINIMUM_COMPARABLE_CASES} are required before generating an AI-supported "
                "outcome assessment."
            ),
            "outcome_distribution": None,
            "sentence_statistics": None,
            "ai_prediction": {
                "status": "insufficient_data",
                "message": "The system will not manufacture a likely outcome from an inadequate case sample."
            }
        }

    total_outcomes = sum(outcome_counts.values())
    distribution = {
        name: {"count": value, "percentage": round(value / total_outcomes * 100, 1)}
        for name, value in sorted(outcome_counts.items())
    } if total_outcomes else {}
    sentence_stats = None
    if sentence_months:
        values = sorted(sentence_months)
        q1 = values[int((len(values) - 1) * 0.25)]
        q3 = values[int((len(values) - 1) * 0.75)]
        sentence_stats = {
            "sample_size": len(values),
            "median_months": round(median(values), 1),
            "middle_50_percent_months": [round(q1, 1), round(q3, 1)],
            "minimum_months": round(values[0], 1),
            "maximum_months": round(values[-1], 1)
        }

    ai_prediction = await generate_ai_prediction(
        payload, comparable, distribution, sentence_stats
    )
    return {
        **base,
        "status": "estimate_available",
        "message": "Statistical estimates calculated from the sourced comparable records.",
        "outcome_sample_size": total_outcomes,
        "outcome_distribution": distribution,
        "sentence_statistics": sentence_stats,
        "ai_prediction": ai_prediction
    }

# MOAI Legal Case Analytics

A multi-jurisdiction legal research and case-outcome analytics platform. A researcher can submit one hypothetical case for automated legal-source retrieval and evidence-grounded analysis; building a manual comparable-case database is not required for the connected source workflow.

## Current capabilities

- FastAPI backend with interactive API documentation.
- PostgreSQL deployment support and SQLite local fallback.
- Seven jurisdiction reference profiles: Nigeria, England and Wales, United States, Canada, Australia, Ghana and South Africa.
- Case library for optional researcher-managed case records, sources, offences, outcomes, sentences and factors.
- Dashboard and descriptive analytics for the records actually stored in the application's database.
- Case comparison and CSV workflows.
- **Automated Nigerian legal research:** queries the free, read-only OpenLegal Nigeria REST API for judgments and legislation.
- **Automated United States case-law research:** queries CourtListener's authenticated v4 opinions search and retrieves full opinion text when `COURTLISTENER_API_TOKEN` is configured.
- Multi-query retrieval using the offence and material factual terms; deduplicates results, ranks source matches, retrieves judgment details and caches public source text.
- **AI-supported legal assessment:** sends the submitted hypothetical facts and a bounded selection of retrieved public legal materials to the configured OpenRouter free model.
- Results include source links, citations where supplied, retrieval relevance indicators, the number of retrieved judgments and legislation sections, and limitations.
- Automated regression tests run through GitHub Actions.

## Automated research workflow

1. The user selects a jurisdiction and submits an offence/legal issue, material facts, and optional aggravating or mitigating factors.
2. For Nigeria, the application searches OpenLegal Nigeria using the offence and factual keywords.
3. It retrieves matching judgment details and searches the source for relevant statutory sections.
4. It deduplicates and ranks the returned public material, reuses cached judgment text for up to 30 days and cached legislation for up to one day, and refreshes expired cache entries.
5. If OpenRouter is configured, a free model receives the submitted facts and a bounded selection of source material to produce a conditional, cited research assessment.
6. The application displays retrieved sources and makes clear when the source returns no matches or AI analysis is unavailable.

The retrieval relevance score is a text-search aid, **not** a legal similarity score. The AI assessment is retrieval-augmented reasoning, **not** a trained or statistically validated machine-learning prediction model. Do not interpret it as a probability or guaranteed court outcome.

## Legal source access

### Nigeria — connected

OpenLegal Nigeria documents a free, read-only REST API requiring no API key:
- Search judgments: `GET https://openlegal.casewinai.com/api/v1/judgments?q=...`
- Retrieve a judgment: `GET https://openlegal.casewinai.com/api/v1/judgments/{id}`
- Search/list legislation: `GET https://openlegal.casewinai.com/api/v1/laws?q=...`

The application links to the source judgment pages. OpenLegal is a legal information service; verify material against certified court copies and official legislation before relying on it.

### United States — connected when token is configured

CourtListener's v4 API requires token authentication. The connector searches published opinion clusters, retrieves up to three lead opinions per request, and caches public opinion text for 30 days. CourtListener documents default authenticated limits of 5 requests per minute, 50 per hour and 125 per day; the connector deliberately caps each search to one search request and up to three opinion-detail requests. No United States legislation connector is included yet.

### Other jurisdictions — not yet connected

The jurisdiction reference data is present, but an automated research connector is not enabled merely because a jurisdiction appears in the selector. Each jurisdiction needs an authorised source/API and its permitted access method. The application does not scrape sites that prohibit automated access or computational reuse. Where a source requires an API key, account approval or licence, that requirement must be met before enabling it.

## Environment variables

Set these in the deployment environment, not in source code:

- `DATABASE_URL`: PostgreSQL connection string. If omitted locally, SQLite is used.
- `OPENROUTER_API_KEY`: OpenRouter API key for AI analysis.
- `OPENROUTER_MODEL`: defaults to `openrouter/free`; alternatively use a verified model ID ending in `:free`.
- `COURTLISTENER_API_TOKEN`: optional CourtListener token; required only to enable United States case-law research.
- `APP_PUBLIC_URL`: optional public application URL used in OpenRouter request metadata.

The application rejects a configured OpenRouter model that is not `openrouter/free` or a model ID ending in `:free`. Never commit API keys or paste them into public issue trackers.

**Privacy:** submitted case facts are sent as search terms to the connected legal-source API (OpenLegal Nigeria or CourtListener, depending on jurisdiction) and, when AI analysis is enabled, are sent to OpenRouter together with selected public source extracts. Submit anonymised facts only. Do not enter privileged, confidential, identifying or otherwise sensitive client information.

## Run locally

Requires Python 3.11 or newer.

```bash
python -m venv .venv
```

Activate the environment:
- Windows: `.venv\\Scripts\\activate`
- macOS/Linux: `source .venv/bin/activate`

Install and run:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:
- http://127.0.0.1:8000
- http://127.0.0.1:8000/docs
- http://127.0.0.1:8000/health

The first run creates database tables and seeds jurisdiction, court and offence reference data. It does not insert fabricated case judgments.

## API endpoints

- `GET /health`
- `GET /api/dashboard/overview`
- `GET /api/cases`
- `POST /api/cases`
- `GET /api/cases/{case_id}`
- `GET /api/analytics/outcomes-by-year`
- `GET /api/predictions/status`
- `POST /api/predictions/research` — automated external legal-source research and AI assessment for connected jurisdictions.
- `POST /api/predictions/estimate` — optional statistical analysis using the researcher's own sourced case records; it is separate from automated external research.
- `GET /api/ai/status`
- `POST /api/ai/explain`

## Research and data-integrity safeguards

- External judgments and legislation are cached separately from researcher-entered case records.
- Source provider, source identifier, citation, court, URL, content and retrieval time are retained in the external-source cache.
- A retrieval relevance score is not presented as legal similarity.
- The system must not invent cases, citations, statutes, holdings, outcomes or sentencing statistics.
- An absent search result does not prove that no relevant authority exists.
- Statistical summaries describe only the available records and are not population-level findings unless a representative dataset has been established.
- Cross-jurisdiction comparisons require attention to differences in legislation, procedure, court hierarchy and sentencing practice.
- AI output is a research aid, not legal advice. Verify authorities and legislation independently.

## Deployment

The repository is connected to Render for deployment from the main branch. Confirm the active Render service and plan before changing infrastructure. Add secrets through the Render environment settings, never to GitHub source files. After deployment, verify `/health`, `/docs` and a real research request.

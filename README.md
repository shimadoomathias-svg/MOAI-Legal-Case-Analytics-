# MOAI Legal Case Analytics — Backend Foundation

A multi-jurisdiction case-research and sentencing analytics platform for legal researchers.

## Included in this foundation
- FastAPI backend and interactive API documentation
- SQLAlchemy database models for jurisdictions, courts, offences, cases, outcomes, sentences, sources and researchers
- Idempotent starter seed data for seven jurisdictions
- Case listing, case creation and case detail endpoints
- Dashboard overview and yearly outcome analytics endpoints
- Prediction endpoint placeholder (the estimator is a later stage)
- Optional OpenRouter AI explanation endpoint, restricted to `openrouter/free` or model IDs ending in `:free`
- SQLite local fallback and PostgreSQL support for deployment

## Run locally
Requires Python 3.11 or newer.

```bash
python -m venv .venv
```

Activate the environment:
- Windows: `.venv\Scripts\activate`
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

The first run creates a local SQLite database and seeds jurisdiction, court and offence reference data. The case database starts empty; no fabricated judgments are inserted.

## OpenRouter
Set `OPENROUTER_API_KEY` in the environment. The default model is `openrouter/free`. You may set `OPENROUTER_MODEL` to a specific free model ID ending in `:free`. The application rejects model IDs that do not meet this free-only rule. Never put the API key in source code or commit it to Git.

Only send public or properly anonymised research material to an external AI provider. Do not submit confidential, privileged, or identifying case information.

## Render deployment
1. Push this project to a GitHub repository.
2. In Render, create a Blueprint from that repository and review the services before applying.
3. The Blueprint declares a PostgreSQL database and a Python web service. Check the current Render plan/pricing before creating resources; database and service costs depend on the selected plan.
4. Add `OPENROUTER_API_KEY` as a secret environment variable in the Render service.
5. Keep `OPENROUTER_MODEL` set to `openrouter/free` unless selecting a verified free model ending in `:free`.
6. Deploy and test `/health`, `/docs`, and `/api/dashboard/overview`.

## API endpoints
- `GET /health`
- `GET /api/dashboard/overview`
- `GET /api/cases`
- `POST /api/cases`
- `GET /api/cases/{case_id}`
- `GET /api/analytics/outcomes-by-year`
- `GET /api/predictions/status`
- `GET /api/ai/status`
- `POST /api/ai/explain`

## Data integrity notes
- Synthetic sample records must be explicitly labelled synthetic. This foundation does not insert fictional case judgments.
- Charged offences and convicted offences are stored separately.
- One case can have multiple outcomes and sentences.
- Each case belongs to a jurisdiction; court selection is checked against that jurisdiction.
- Cross-jurisdiction comparisons must be contextualised rather than treated as directly equivalent.
- Prediction features are not yet implemented and must not be presented as reliable estimates until validated against an appropriately sourced dataset.

## Production work still required
Authentication, role-based permissions, database migrations, audit logs, pagination refinements, stricter CORS, full offence/outcome management, CSV import/export, validated analytics and prediction models, automated tests, and a production frontend.

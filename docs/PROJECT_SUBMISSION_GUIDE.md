# Project Submission and Demonstration Guide

## Project title
**MOAI Legal Case Analytics** — an AI-assisted legal research and case-outcome analysis platform.

## 1. Project purpose
The platform is designed to help a legal researcher examine a hypothetical or real case by retrieving relevant legal materials from connected external sources, organising the retrieved evidence, and producing a cautious, source-grounded assessment. It also provides a case library, comparisons, descriptive analytics and data-import/export facilities for researcher-managed records.

The automated research workflow is intended to work from one submitted case. The user does not have to create a manual library of comparable cases before using that workflow.

## 2. System architecture
- **Frontend:** browser-based workspace served by the FastAPI application.
- **Backend:** Python 3.11+, FastAPI REST API.
- **Database:** PostgreSQL in deployment; SQLite fallback for local development and tests.
- **Legal-source retrieval:** documented external APIs, with source-specific authentication where required.
- **AI layer:** OpenRouter free-model route, subject to a configured API key and free-model restriction.
- **Testing:** pytest regression tests executed by GitHub Actions on pushes and pull requests.
- **Deployment:** Render configuration is provided in `render.yaml`.

## 3. Main functional modules
1. **Case library:** create, view, filter and manage researcher-entered case records.
2. **Case comparison:** compare selected records in the local case library.
3. **Automated legal research:** submit jurisdiction, offence/legal issue and facts; the application queries an enabled external legal source.
4. **Source extraction and ranking:** retrieve source details, extract available text, deduplicate records and rank search matches. The displayed retrieval score is a search relevance aid, not a legal-similarity score.
5. **AI-assisted assessment:** where source judgments have actually been retrieved and AI is configured, submit the hypothetical facts and selected source extracts to OpenRouter for a conditional analysis.
6. **Analytics:** descriptive summaries of the records actually held in the researcher's database.
7. **Data exchange:** CSV import/export workflows.
8. **Configuration and source status:** disclose which research sources are automated, which require credentials, and which remain manual or unavailable.

## 4. Current source integration status

| Source / jurisdiction | Current status | Important qualification |
|---|---|---|
| OpenLegal Nigeria | Automated REST API connector | Public indexed coverage is limited; zero results do not mean no relevant Nigerian case exists. |
| NigeriaLII | Manual research link; automated API integration pending | An email requesting API documentation, access conditions and permission has been sent to the provider. Do not scrape or guess endpoints. |
| Supreme Court of Nigeria judgment portal | Manual official portal link | No verified public machine-readable API has been configured. |
| CourtListener (United States) | Connector implemented; token required | Automated searches are unavailable until a valid `COURTLISTENER_API_TOKEN` is configured. |
| England and Wales, Canada, Australia, Ghana and South Africa | Jurisdiction profiles only | Do not describe these as connected automated research sources. Authorised source/API integration remains future work. |

### External dependency still pending
The project owner has contacted NigeriaLII/AfricanLII requesting official API documentation, authentication/access details, rate limits, attribution rules and permission for a public non-commercial academic integration. The request is pending a provider response. The application intentionally does not scrape NigeriaLII or use an undocumented endpoint.

## 5. AI and outcome-analysis methodology
The automated workflow uses retrieval-augmented generation (RAG): it first retrieves external legal materials and then supplies selected source material and the submitted facts to an AI model for interpretation. The model is instructed not to invent authorities, citations, statutory provisions, outcomes or statistics and to state when the evidence is inadequate.

This is **not a supervised machine-learning model trained on a labelled dataset of court decisions**. The legacy local estimator and dashboard statistics operate on researcher-entered records and must not be presented as validated national outcome probabilities. A retrieval score is not a probability that a party will win.

A defensible statistical predictive model would require a sufficiently large, representative and labelled dataset, feature definitions, training/validation/test splits, calibration and independent performance evaluation. Those prerequisites are not currently established.

## 6. Data-integrity and legal safeguards
- AI analysis must not be represented as a guaranteed result or legal advice.
- A prediction must not be generated as though it were evidence-based when no relevant judgment documents were retrieved.
- Statutory search results alone are not a substitute for comparable judgments when assessing case outcomes.
- Search-result absence is not proof that no relevant authority exists.
- Allegations, disputed facts and established evidence must be distinguished.
- A defence such as self-defence is analysed as a potential issue of liability, not merely as a mitigating factor.
- Users should independently verify every authority and statutory provision against authoritative sources.
- Users should anonymise case facts and must not submit privileged, confidential or identifying client information. Submitted facts may be transmitted to the selected legal-source provider and, when enabled, OpenRouter.

## 7. Current test evidence
The repository's GitHub Actions workflow runs the API regression suite on pushes and pull requests. The latest main-branch commit at the time this guide was prepared is:

- Commit: `2180bea411f01a627db02da4fcdcb556903d0244`
- Change: documentation of NigeriaLII coverage and pending authorised API integration.
- Workflow: **API tests**
- Run: [GitHub Actions run 42935254102](https://github.com/shimadoomathias-svg/MOAI-Legal-Case-Analytics-/actions/runs/42935254102)
- Result: **success**.

The suite includes API tests for case records, analytics, jurisdiction handling, automated research without a local case corpus, source-not-connected behaviour, source text extraction and ranking, caching, OpenLegal retrieval, CourtListener retrieval and missing-token handling. These are automated regression tests with mocked external responses; they do not prove that a third-party API will always return relevant authorities or that legal conclusions are correct.

### Example murder research test
A murder hypothetical involving a land dispute, a fatal assault, a self-defence claim, eyewitness evidence and medical evidence was submitted. The connected OpenLegal search returned **0 judgments** and **4 legislation sections**. The application returned an `insufficient_evidence` assessment instead of inventing comparable cases or a likely outcome.

This result demonstrates the system's evidence threshold and limitation. It does **not** demonstrate successful retrieval of comparable murder judgments. NigeriaLII API approval/integration or another authorised judgment corpus is needed to improve this coverage.

## 8. Demonstration script (about 5–7 minutes)
1. Open the deployed application and show the workspace/dashboard.
2. Open the automated case research/insights area.
3. Select **Nigeria** and enter a short anonymised hypothetical offence and fact pattern.
4. Run the research request.
5. Show the source provider, search queries, retrieved judgment and legislation counts, source links and excerpts.
6. If judgments are retrieved, explain how the AI assessment compares the hypothetical facts with the retrieved materials and identifies similarities, differences, legal issues and limitations.
7. If no judgments are retrieved, show the `insufficient_evidence` result and explain why the application refuses to manufacture a prediction.
8. Show the manual case library, comparison and analytics as separate functions based on researcher-managed records.
9. Explain the source status honestly: OpenLegal is automated; NigeriaLII automated access is pending provider authorisation; CourtListener requires a token; other jurisdiction profiles are not yet automated.

## 9. Suggested viva explanation
**What makes the platform AI-assisted?** It combines automated legal-source retrieval with an AI model that interprets retrieved judgments and legislation in the context of submitted facts. It is not simply a chatbot because the analysis is designed to be grounded in retrieved legal materials and source links.

**Does it predict the exact judgment?** No. It provides a conditional research assessment, not a guaranteed outcome or a statistically validated probability.

**Why can the platform return insufficient evidence?** The quality of an assessment depends on relevant source material. If the connected source returns no comparable judgments, the system should disclose that limitation rather than fabricate a case comparison.

**Why is NigeriaLII not yet automated?** The provider's authorised API details and access permission have been requested. The application avoids scraping or undocumented endpoints while approval is pending.

**What is required to improve predictive accuracy?** Authorised access to a larger judgment corpus, reliable extraction and annotation of case facts/issues/holdings/outcomes, a representative labelled dataset, and rigorous model validation.

## 10. Final pre-submission checklist
- [ ] Open the deployed application in a browser and confirm the page loads.
- [ ] Open `/health` and confirm the service reports healthy.
- [ ] Open `/docs` and confirm the API documentation loads.
- [ ] Open the research setup/source-status screen and confirm the configured source statuses.
- [ ] Run one anonymised Nigeria research example and retain its actual output as a screenshot.
- [ ] Do not describe an `insufficient_evidence` test as a successful case-outcome prediction.
- [ ] Keep the NigeriaLII email request as evidence that authorised access was sought.
- [ ] Do not publish API keys, tokens, database credentials or confidential case facts.
- [ ] Include this guide and the README with the project submission.

## 11. Limitations and future work
The most important next step is authorised access to a broader Nigerian judgment corpus, followed by more complete case-level comparison and systematic evaluation. Further work includes a validated labelled dataset, expanded jurisdiction-specific source integrations, improved retrieval evaluation, and independent legal review of generated assessments.

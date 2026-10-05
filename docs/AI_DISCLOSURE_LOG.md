# AI Disclosure Working Log

Copy the relevant facts into Appendix A of the supplied report template and
write the final explanation in your own words. Add every later AI interaction;
do not treat this starter log as complete forever.

## 5 October 2026

AI aid: OpenAI Codex in the Codex desktop application.

Student prompts:

- "i want to build this for my course work."
- "i want the code base to be student friedly for me . add comments in imporant places and code should be simple not hard to undersatnd"

Context supplied to the AI:

- NB6007CEM Coursework Brief
- NB6007CEM Marking Rubric
- NB6007CEM Report Template 25.1P

Generated or assisted artefacts:

- FastAPI project structure and configuration
- SQLAlchemy data model and security helpers
- Catalog, reading, composite, and summary endpoints
- JWT scopes and jurisdiction checks
- Conditional request, pagination, and error helpers
- Deterministic seed generator
- Tests, Docker/Render configuration, and study documentation

Critical review performed:

- Preserved readings as an append-only time series despite ambiguous "full
  CRUD" wording; CRUD is demonstrated on mutable catalog resources.
- Kept the meter identifier on SolarInstallation instead of creating a Device
  entity.
- Separated operation scopes from jurisdiction row filtering.
- Differenced cumulative energy per installation instead of summing raw meter
  totals in the district summary.
- Added integration tests for cross-installation and cross-district denial,
  conditional requests, validation, pagination, and response headers.

Verification commands:

```text
pytest
ruff check src scripts tests
python scripts/seed.py
```

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system api && adduser --system --ingroup api api

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts

RUN pip install .

USER api
EXPOSE 8000

# Seeding is idempotent: it inserts data only when the database is empty.
CMD ["sh", "-c", "python scripts/seed.py && uvicorn slsea_api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

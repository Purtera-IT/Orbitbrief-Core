# Build context must include sibling checkouts (see scripts/prepare-build-context.sh):
#   parser-os/  Orbitbrief-Core/  orbitbrief-core-worker/
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY orbitbrief-core-worker/requirements.txt /app/requirements.txt
# Worker HTTP stack + Orbitbrief-Core / parser-os runtime deps (no editable file:// installs).
RUN pip install --no-cache-dir -r /app/requirements.txt \
    "pydantic>=2.8.0" \
    "PyYAML>=6.0.1" \
    "openpyxl>=3.1.2" \
    "jsonschema>=4.23.0" \
    "duckdb>=1.0,<2.0" \
    "httpx>=0.27.0" \
    "requests>=2.31.0" \
    "sqlmodel>=0.0.16" \
    "python-docx>=1.1" \
    "beautifulsoup4>=4.12" \
    "typer>=0.12" \
    "rich>=13.0" \
    "rapidfuzz>=3.0" \
    "numpy>=1.26" \
    "scikit-learn>=1.3" \
    "pypdfium2>=4.30" \
    "Pillow>=10.0"

COPY parser-os /app/parser-os
COPY Orbitbrief-Core /app/Orbitbrief-Core
COPY orbitbrief-core-worker /app/orbitbrief-core-worker

ENV ORBITBRIEF_CORE_ROOT=/app/Orbitbrief-Core
ENV PARSER_OS_ROOT=/app/parser-os
ENV PYTHONPATH=/app/parser-os:/app/Orbitbrief-Core/src
ENV PORT=8080
ENV COMPILE_TIMEOUT_SEC=840

WORKDIR /app/orbitbrief-core-worker
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]

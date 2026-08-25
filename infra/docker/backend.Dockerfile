# Single image, two entrypoints (api / worker) — see app/main.py and app/workers/run.py

FROM python:3.12-slim AS base

WORKDIR /srv

RUN groupadd --system helix && useradd --system --gid helix --create-home helix

COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[dev]"

COPY backend/ ./

RUN chown -R helix:helix /srv
USER helix

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

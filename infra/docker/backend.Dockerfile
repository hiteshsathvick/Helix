# Single image, two entrypoints (api / worker) — see app/main.py and app/workers/run.py

FROM python:3.15-slim AS base

WORKDIR /srv

RUN groupadd --system helix && useradd --system --gid helix --create-home helix

COPY backend/pyproject.toml ./
# sentence-transformers pulls in torch, which defaults to the CUDA build on
# Linux (~2.6GB of NVIDIA libraries this container, with no GPU, will never
# use). The CPU wheel index resolves torch itself to a CPU-only build while
# every other dependency still comes from PyPI as normal.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -e ".[dev]"

# tiktoken (assistant/service.py, loaded at import time) and the default
# local embedding model (ingestion/embeddings.py, loaded on first use) both
# fetch a file from the network the first time they're used, with nowhere
# to cache it previously -- every fresh container needed working egress to
# an external host just to import app.main, and a DNS/network blip crashed
# the whole app at startup (Phase 20, found while verifying this phase's
# own changes). Pre-fetching both here bakes them into the image layer, so
# `docker build` (expected to need network) is the only place this can ever
# fail -- every container start after that is fully offline for these two.
# Only covers the *default* embedding_model_name -- an org/deployment that
# overrides EMBEDDING_MODEL_NAME still needs network on first ingest.
ENV TIKTOKEN_CACHE_DIR=/opt/cache/tiktoken
ENV HF_HOME=/opt/cache/huggingface
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" \
    && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY backend/ ./

RUN chown -R helix:helix /srv /opt/cache
USER helix

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

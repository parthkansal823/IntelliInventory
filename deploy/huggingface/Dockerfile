# IntelliInventory on a FREE Hugging Face Space (CPU basic: 2 vCPU, 16 GB RAM) - with Hermes AI running inside
# the container through Ollama. No API key, no paid service.
#
# Put this file + README.md from this folder into a new Docker Space. It builds the latest code from GitHub.
# To update later: Space -> Settings -> "Factory rebuild" (or let the GitHub Action do it on every push to main).

# ---- 1. Get the code and build the React app ---------------------------------------------
FROM node:22-slim AS src
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
ARG REPO=https://github.com/parthkansal823/IntelliInventory.git
ARG REF=main
RUN git clone --depth 1 --branch ${REF} ${REPO} /src
WORKDIR /src/frontend
RUN npm ci --no-audit --no-fund && npm run build

# ---- 2. Runtime: FastAPI + the built app + Ollama with a Hermes model baked in -------------------
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates zstd && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://ollama.com/install.sh | sh

# hermes3:3b (~2 GB) answers in seconds on 2 CPUs. hermes3 (8B, ~4.7 GB) is smarter but slower on free CPUs.
ARG HERMES_MODEL=hermes3:3b
ENV OLLAMA_MODELS=/opt/ollama/models OLLAMA_HOST=127.0.0.1:11434 OLLAMA_KEEP_ALIVE=24h
RUN mkdir -p /opt/ollama/models \
 && (ollama serve > /tmp/ollama-build.log 2>&1 &) \
 && for i in $(seq 1 60); do curl -sf http://127.0.0.1:11434/api/tags > /dev/null && break; sleep 1; done \
 && ollama pull ${HERMES_MODEL} \
 && chmod -R a+rwX /opt/ollama

RUN pip install --no-cache-dir uv
RUN useradd -m -u 1000 user
WORKDIR /app/backend
COPY --from=src /src/backend/ ./
COPY --from=src /src/integrations/ /app/integrations/
COPY --from=src /src/deploy/huggingface/start.sh /app/start.sh
COPY --from=src /src/frontend/dist /app/frontend/dist
RUN UV_COMPILE_BYTECODE=1 uv sync --frozen --no-dev && chmod +x /app/start.sh && chown -R user:user /app

USER user
ENV HOME=/home/user \
    PATH=/app/backend/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    FRONTEND_DIST=/app/frontend/dist \
    PORT=7860 \
    HERMES_MODEL=${HERMES_MODEL} \
    OLLAMA_URL=http://127.0.0.1:11434 \
    DATABASE_URL=sqlite:////tmp/intelliinventory.db
EXPOSE 7860
CMD ["/app/start.sh"]

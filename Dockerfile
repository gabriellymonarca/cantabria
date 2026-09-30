# Imagem única do Cantábria: serve o app (Chainlit) e roda o seed do ClickHouse
# (serviço `seed` do compose). Tudo que é copiado aqui está versionado no git;
# segredos (.env, config.yaml) entram só em runtime, via compose.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CHAINLIT_HOST=0.0.0.0 \
    CHAINLIT_PORT=8000 \
    CONFIG_PATH=/app/config.yaml \
    CANTABRIA_DATA_DIR=/app/data

WORKDIR /app

# USE_LOCK=1 (padrão): instala as versões pinadas de requirements.lock quando
# o arquivo existe (gerado por `make lock` a partir do uv.lock). Sem o lock —
# ou com USE_LOCK=0 — cai para os ranges do pyproject.toml, então o build nunca
# quebra por falta do arquivo. O padrão `requirements.loc[k]` torna o COPY
# opcional: um glob sem match não falha.
ARG USE_LOCK=1
COPY pyproject.toml requirements.txt requirements.loc[k] ./
COPY src/ ./src/
RUN if [ "$USE_LOCK" = "1" ] && [ -f requirements.lock ]; then \
        echo "usando requirements.lock" \
        && pip install -r requirements.lock \
        && pip install --no-deps . ; \
    else \
        echo "sem requirements.lock: instalando ranges do pyproject.toml" \
        && pip install . ; \
    fi \
    # Extras do seed/ingest (utils/): só as linhas de geração de dados do
    # requirements.txt, não o tooling de teste (pytest, testcontainers, ruff).
    && grep -E '^(faker|openpyxl|pyarrow|python-docx|python-pptx)' requirements.txt \
         | sed 's/#.*//' \
         > /tmp/requirements-seed.txt \
    && pip install -r /tmp/requirements-seed.txt \
    && rm -f /tmp/requirements-seed.txt

# Dados governados (catálogo, prompts, capabilities, .xlsm das hierarquias),
# gerador/seed e o DDL versionado que o seed aplica.
COPY data/ ./data/
COPY utils/ ./utils/
COPY infra/clickhouse/init/ ./infra/clickhouse/init/
COPY config.example.yaml chainlit.md ./
COPY .chainlit/config.toml ./.chainlit/config.toml

EXPOSE 8000

CMD ["python", "-m", "entrypoints.app"]

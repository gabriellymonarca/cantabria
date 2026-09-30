PYTHON ?= python3
RUFF ?= ruff
COMPOSE ?= docker compose
# Todos os profiles do compose.yaml: `stack-down` derruba tudo de uma vez.
ALL_PROFILES := --profile core --profile seed --profile stores --profile observability

.PHONY: help setup lock data run test test-integration lint format up seed ingest \
        eval eval-smoke demo preflight stack stack-down stores observability logs build

help:
	@$(PYTHON) -c "print('Targets: setup | lock | data | run | test | test-integration | lint | format | eval | eval-smoke | demo | preflight | seed | ingest | stack | stack-down | stores | observability | logs | build')"

setup:
	$(PYTHON) -m pip install -e .
	$(PYTHON) -m pip install -r requirements.txt

# Exporta o uv.lock como requirements.lock (pinado, com hashes) para o
# Dockerfile. Exige `uv` (https://docs.astral.sh/uv/). Roda no host Linux;
# sem o arquivo a imagem cai para os ranges do pyproject.toml (ver Dockerfile).
lock:
	uv lock
	uv export --no-dev --no-emit-project --format requirements-txt -o requirements.lock

# Gera o dataset fictício em Parquet (data/dataset/, gitignored) com a seed
# padrão — mesmo gerador determinístico usado pelo seed do ClickHouse.
data:
	$(PYTHON) utils/generate_cantabria_data.py --out data/dataset

run:
	PYTHONPATH=src $(PYTHON) -m entrypoints.app

test:
	PYTHONPATH=src $(PYTHON) -m pytest

test-integration:
	PYTHONPATH=src $(PYTHON) -m pytest -m integration

lint:
	$(RUFF) check src tests utils scripts

format:
	$(RUFF) format src tests utils scripts

up:
	$(PYTHON) scripts/up.py $(MSG)

# Avaliação. `eval` roda o harness de verdade (camadas engine e redteam
# offline, relatório em reports/ — gitignored); `eval-smoke` continua o subset
# rápido determinístico em pytest, para rodar a cada mudança.
EVAL_TESTS := tests/test_oracle_comparison.py tests/test_oracle_artifact.py \
              tests/test_cases.py tests/test_prompt_examples.py

eval:
	PYTHONPATH=src $(PYTHON) -m eval --layer all --split dev --report reports/

eval-smoke:
	PYTHONPATH=src $(PYTHON) -m pytest -q $(EVAL_TESTS)

# Seed pelo host (ClickHouse publicado em 127.0.0.1:8123). Dentro do Docker,
# prefira `$(COMPOSE) --profile seed run --rm seed` (target `demo`).
seed:
	$(PYTHON) utils/seed_clickhouse.py

# Documentos de referência (docx/pptx determinísticos) + ingestão no Qdrant.
# Exige o profile `stores` de pé e config.yaml com a seção `embeddings`; sem
# ela, use `utils/ingest_documents.py --dry-run`.
ingest:
	PYTHONPATH=src $(PYTHON) utils/generate_reference_documents.py
	PYTHONPATH=src $(PYTHON) utils/ingest_documents.py

# Demo em um comando: sobe core → espera o ClickHouse healthy → seed no
# container → preflight → URL. Exige .env e config.yaml preenchidos.
demo:
	@test -f config.yaml || { echo "config.yaml ausente: cp config.example.yaml config.yaml e preencha llm.api_key"; exit 1; }
	@test -f .env || { echo ".env ausente: cp .env.example .env e preencha as senhas"; exit 1; }
	@echo "subindo o profile core e aguardando o ClickHouse ficar healthy..."
	$(COMPOSE) --profile core up -d --build --wait
	$(COMPOSE) --profile seed run --rm seed
	$(PYTHON) scripts/preflight.py
	@echo "Cantábria pronto: http://localhost:8000"

preflight:
	$(PYTHON) scripts/preflight.py

stack:
	$(COMPOSE) --profile core up -d --build

stack-down:
	$(COMPOSE) $(ALL_PROFILES) down --remove-orphans

# Stores da Fase 3: o app usa o MongoDB (histórico/auditoria); Qdrant/MinIO
# aguardam a Fase 3c.
stores:
	$(COMPOSE) --profile stores up -d

# Langfuse (tracing opcional): renderiza os segredos e sobe o profile.
observability:
	./scripts/langfuse_up.sh

logs:
	$(COMPOSE) logs -f app

build:
	docker build -t cantabria .

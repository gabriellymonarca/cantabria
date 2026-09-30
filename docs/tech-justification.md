# Justificativa técnica

## 1. Estratégia (no vocabulário do curso)

**Text-to-plan governado por catálogo semântico + execução determinística + RAG
só para conhecimento aprovado** — uma "abordagem alternativa" a RAG puro e a
fine-tuning. O LLM traduz a pergunta num plano estruturado
(`InterpretationProposal`, pydantic); `validate_plan` aprova contra
`data/catalogs/semantic_catalog_v3.yaml` e as capacidades do perfil; o motor
calcula no ClickHouse; o LLM redige só sobre números verificados, citando
documentos `approved` (`data/knowledge/`, 20 docs). Prova de que o desenho
funciona: `tests/test_validate_plan.py`, `python -m eval` (engine contra
oráculo independente, redteam sem LLM — números em `docs/evaluation-report.md`).

## 2. Alternativas

| Alternativa | Por que rejeitada | Quando reconsiderar |
|---|---|---|
| **Text-to-SQL/pandas livre** | erro silencioso nas armadilhas de agregação (média de taxas, soma de estoque entre meses, soma de clientes entre produtos); expõe nomes físicos; autorização dependeria do LLM | nunca como caminho principal; útil só como **baseline** de controle — implementado no harness (`python -m eval --layer baseline --live`, SQLite sobre o fixture do oráculo), run pendente (checklist §6) |
| **Fine-tuning** | não resolve governança (número inventado, autorização); custo de retreino a cada mudança de catálogo; dataset `dev` tem 80 casos | acurácia do planner estagnar no `test`; custo por pergunta com volume alto |
| **RAG puro sobre tabelas** | RAG recupera texto, não calcula; taxa re-derivada exige agregação; sem oráculo possível | nunca para números; **aceito** para definições/métodos (rota `documental`, ADR 0012) |
| **Agentic tool-use livre** (LLM chama ferramentas de cálculo/gráfico) | ferramenta chamada errado é número errado; gráfico gerado pelo LLM não é auditável | **aceito parcialmente**: o LLM escolhe `presentation` de um catálogo fechado; o gráfico é gerado deterministicamente (ADR 0005) |

## 3. Tecnologias

| Tecnologia | Papel | Alternativa considerada | Decisão |
|---|---|---|---|
| Python 3.12 (`pyproject.toml`) | núcleo DDD/CQRS, ports & adapters | — | `AGENTS.md`, ADR 0002, 0007 |
| Chainlit 2.12 | UI conversacional, auth, starters, data layer | Streamlit, FastAPI custom | adapter inbound `chainlit.py` |
| LangChain (`langchain-openai` 1.x) structured output | planner → pydantic com retry de schema | tool-calling manual, Instructor | `adapters/outbound/langchain_llm.py`; `tests/test_langchain_llm_schema_errors.py` |
| pydantic 2 | schema do plano e do dataset de eval | dataclasses + validação manual | `interpretation_schema.py`, `src/eval/dataset.py` |
| ClickHouse | dados oficiais; agregação empurrada (`SUM`/`uniqExact`/`argMax`) | DuckDB local, Postgres | ADR 0003; `clickhouse_official_data.py`; `tests/test_clickhouse_parity.py` |
| MongoDB (opcional) | Conversation/Plan/Result/Artifact Store + outbox | Postgres, só memória | ADR 0010 |
| Qdrant (opcional) | RAG semântico, fallback BM25 próprio | pgvector, só BM25 | ADR 0014; `resilient_knowledge.py` |
| MinIO (opcional) | Value Object Store dos documentos aprovados | S3, filesystem | ADR 0014; gráficos ainda `derived://` (ADR 0005) |
| Langfuse v4 + OpenInference | 1 trace por turno, tokens, PII já redigida | LangSmith, OTel puro | `cross_cutting/observability.py` |
| Plotly | gráficos determinísticos do `AnalysisResult` | matplotlib | ADR 0005 |
| Oráculo em Python puro/`Decimal` | valores esperados fora do motor (não importa `src/`) | DuckDB/pandas (proposta do checklist) | ADR 0006; `utils/oracle_fixture.py`, `data/oracle/oracle_v1.yaml` |
| Faker pt_BR + `random.Random(seed)` | dados 100% sintéticos | numpy | `utils/generate_cantabria_data.py`; `tests/test_generator_determinism.py` |
| Docker Compose único com profiles | reprodutibilidade | vários composes | ADR 0008; CI `.github/workflows/ci.yml` |

## 4. Modelo

`gpt-4o-mini`, `temperature: 0.0`, endpoint OpenAI-compatível
(`config.example.yaml`). Papéis: planner (structured output), redator
(`insight/v3`), síntese documental (`documental/v1`); embeddings opcionais
para o Qdrant. **É o único modelo exercitado.** A comparação de ≥2 modelos
(acurácia/latência/custo por papel) tem protocolo pronto
(`python -m eval --layer planner --live`, ADR 0015) e **não foi executada**;
ver `docs/evaluation-report.md`.

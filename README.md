# Cantábria

Análise financeira em linguagem natural, **governada**. O problema: executivos
e analistas de um banco perguntam "qual segmento é mais rentável?" e a resposta
costuma depender de quem monta a query — média de taxas onde deveria ser
Σ margem ÷ Σ saldo, saldo somado entre meses, cliente individual exposto. O
Cantábria responde a essas perguntas sobre os dados oficiais (fictícios) do
Banco Cantábria sem deixar o modelo de linguagem tocar em número: **o modelo
propõe; código determinístico autoriza, executa e verifica.** O LLM interpreta
a pergunta e propõe planos estruturados; `validate_plan` os aprova contra um
catálogo semântico fechado; o motor calcula sobre o ClickHouse; o LLM explica
**apenas** números que existem no resultado, apoiado por documentos aprovados
(RAG). Vocabulário do negócio (Vinculação, Principalidade, rentabilidade,
saldo) em `docs/architecture/definitions.md`.

## Como funciona (1 minuto)

| Passo | O que acontece | Onde |
|---|---|---|
| 1. Pergunta | usuário autenticado escreve em português (até 2000 caracteres) | `user_interaction/adapters/inbound/chainlit.py` → `SubmitQuestionHandler` |
| 2. Guardrails de entrada | CPF/CNPJ/e-mail/telefone redigidos **antes** do LLM e do trace; campo físico (`ds_segm`), SQL e injeção recusados com código | `financial_analysis/domain/services/input_guard.py`; `tests/test_input_guard.py` |
| 3. Planner | LLM (gpt-4o-mini, temperature 0) devolve **structured output** pydantic: rota (`analytical` · `documental` · `capability` · `clarify` · `refuse`) + `CalculationPlan`s + `AnalysisPlan` | `application/commands/interpretation_schema.py`, `answer_question.py` |
| 4. `validate_plan` | catálogo fechado `data/catalogs/semantic_catalog_v3.yaml`; autorização por perfil **fora do LLM**, inclusive antes de esclarecer; 1 retry de schema e 1 semântico, depois recusa tipificada | `domain/services/validate_plan.py`; `tests/test_validate_plan.py`, `tests/test_create_plan_retry.py` |
| 5. Motor | agregação empurrada ao ClickHouse; `profitability` re-derivada em todo grão; ausência = `null`; small-cell k = 10 com supressão complementar | `financial_calculation/`, `domain/services/execute_analysis.py`; `tests/test_execute_analysis.py` |
| 6. Gate de lastro | todo número do texto do redator tem que existir no `AnalysisResult` (tolerância 0.006); 1 regeneração, depois só a tabela verificada | `execute_pipeline._grounded_insight`; `tests/test_execute_pipeline.py::test_insight_rejeitado_duas_vezes_entrega_a_tabela_verificada` |
| 7. Resposta | texto + gráfico determinístico do resultado (ADR 0005) + rodapé de proveniência legível (`_Fonte: … · protocolo CAN-XXXXXXXX_`) + bloco recolhível "Como calculei" gerado do plano validado (ADR 0016, superfície de resposta) | `domain/services/provenance.py`, `adapters/outbound/plotly_artifact_builder.py` |

O protocolo do rodapé são os 8 primeiros hex do `trace_id` do turno: é o que o
usuário cita num chamado e o que se busca no Langfuse. Detalhe do fluxo em
`docs/architecture/flow.md`; decisões em `docs/decisions.md`.

## Avaliação

```bash
make eval                 # engine + redteam offline (sem LLM), split dev
python -m eval --layer planner --split dev --live   # camadas generativas, exige config.yaml com LLM
```

Camadas do harness (`src/eval/`, ADR 0015): `engine` (motor × oráculo
independente `data/oracle/oracle_v1.yaml`, tolerância 1e-9), `redteam`
(`data/eval/redteam.yaml`, OWASP LLM Top 10), `planner`/`routing` (live) e
`explanation`/`e2e` (ainda stubs). Dataset: `data/eval/dev.yaml`, 80 casos.
Resultados, gaps e pendências: **`docs/evaluation-report.md`**.

## Documentação

| O que a banca procura | Arquivo |
|---|---|
| O enunciado do case | `docs/enunciado.md` |
| Como executar (passo a passo, troubleshooting) | `docs/como-usar.md` |
| Arquitetura (contextos, camadas) e fluxo ponta a ponta | `docs/architecture/architecture.md`, `docs/architecture/flow.md` |
| Definições de negócio (autoridade máxima) · schema dos planos · catálogo | `docs/architecture/definitions.md`, `docs/plans.md`, `docs/semantic-catalog.md` |
| Decisões e trade-offs (ADRs D-0001–D-0017) | `docs/decisions.md` |
| Justificativa tecnológica (alternativas, quando reconsiderar) | `docs/tech-justification.md` |
| Dados: 100% sintéticos, geração, versão, mercado | `docs/data-statement.md` |
| Avaliação: método, runs registrados, pendências | `docs/evaluation-report.md` |
| Ética, privacidade, LGPD, red team, limitações | `docs/responsible-ai.md` |
| Roteiro da apresentação (90 min), fallback e Q&A | `docs/demo.md` |
| Próximos passos · rastreabilidade enunciado → evidência | seções finais deste README |

## Quick start (one way to run it)

Requisitos: Docker + Docker Compose v2 e uma chave de um endpoint
OpenAI-compatível. Passo a passo completo em `docs/como-usar.md`.

```bash
git clone <repo> cantabria && cd cantabria
cp .env.example .env                 # senhas locais do ClickHouse/MinIO (os exemplos funcionam)
cp config.example.yaml config.yaml   # edite llm.api_key
make demo                            # Linux/macOS
```

Sem `make` (Windows/PowerShell), são os mesmos três comandos que o alvo roda:

```powershell
docker compose --profile core up -d --build
docker compose --profile seed run --rm seed
python scripts/preflight.py          # opcional: GO/NO-GO da demo
```

Abra http://localhost:8000. Há **um** `compose.yaml` (raiz) com os profiles
`core` (ClickHouse + app), `seed`, `stores` (MongoDB/Qdrant/MinIO — já
ligados na fiação com degradação graciosa: sem `MONGO_URL` os stores ficam em
memória, sem `QDRANT_URL`/`embeddings` a busca é lexical BM25; ADRs 0010 e
0014) e `observability` (Langfuse, opcional) — ver ADR 0008.

## Project Structure

```
cantabria/
├── compose.yaml            # ÚNICO compose: profiles core | seed | stores | observability
├── Dockerfile              # imagem do app e do seed
├── Makefile                # setup · data · test · eval · demo · preflight · stack · build
├── data/                   # catálogo semântico, prompts, capabilities, oráculo, .xlsm das hierarquias
├── docs/                   # enunciado, arquitetura, decisões (ADRs), avaliação, como-usar
├── infra/clickhouse/       # config.d, users.d e DDL (00_schema.sql) montados/aplicados pelo compose
├── infrastructure/         # templates de segredo do Langfuse (renderizados por scripts/langfuse_up.sh)
├── scripts/                # preflight.py, langfuse_up.sh, up.py, hooks
├── src/
│   ├── entrypoints/        # composition root (fiação + ambiente + /ready)
│   ├── contexts/
│   │   ├── financial_analysis/
│   │   ├── financial_calculation/
│   │   ├── user_interaction/
│   │   └── auth/
│   ├── cross_cutting/      # config, logging, observability, mongo, outbox (infra transversal)
│   ├── eval/               # harness de avaliação (python -m eval)
│   └── shared/             # kernel puro (operadores numéricos, redação de PII, eventos base; sem I/O)
├── tests/
└── utils/                  # gerador determinístico e seed do ClickHouse
```

## Code structure

### Contexts

auth
│
└── Quem pode fazer o quê?

user_interaction
│
└── Como o usuário conversa com o Cantábria?

financial_analysis
│
└── Como uma pergunta vira uma análise e uma resposta analítica?

financial_calculation
│
└── Como um CalculationPlan vira valores financeiros determinísticos?

### Ports & Adapters (por contexto)

Cada bounded context declara as próprias fronteiras, separando driving de driven:

```
contexts/<contexto>/
├── ports/
│   ├── inbound/      # driving: o que um adapter de entrada chama
│   └── outbound/     # driven: o que o contexto precisa do mundo externo
└── adapters/
    ├── inbound/      # driving: traduz eventos externos (ex.: Chainlit)
    └── outbound/     # driven: implementa um port (ex.: ClickHouse)
```

O ClickHouse é um adapter **outbound** de `financial_calculation`
(`adapters/outbound/clickhouse_official_data.py`), implementando o port
`ports/outbound/official_data_repository.py`. O adapter **empurra a agregação
para o banco** e devolve, via `fetch_aggregated`, apenas os componentes por
grupo/período — nenhuma linha de fato crua atravessa o Port. O core não conhece
SQL nem driver; a fiação vive em `src/entrypoints/composition.py`.

### Testes

```bash
python -m pytest tests                 # unitários (rápidos, sem Docker)
python -m pytest tests -m integration  # paridade com ClickHouse (Docker)
```

## Running the app

The supported path is the Quick start above (`make demo` or the equivalent
`docker compose` commands). Details — seed, demo script, pointing at a
customer database, troubleshooting — live in `docs/como-usar.md`.

The conversational UI is a Chainlit inbound adapter in the `user_interaction`
context, wired in `src/entrypoints/app.py`. For development with the app on
the host and only ClickHouse in Docker:

```bash
make setup                                # pip install -e . -r requirements.txt
docker compose up -d --wait clickhouse    # profile core, only the database
make seed                                 # python utils/seed_clickhouse.py
make run                                  # PYTHONPATH=src python -m entrypoints.app
```

Open http://localhost:8000 and send any message. The adapter calls the
`UserRequestPort` implemented by `SubmitQuestionHandler`
(`user_interaction/application/commands/submit_question.py`, a command: it
loads/saves the `Conversation` aggregate and publishes its events), which
delegates to the financial analysis `ProcessUserRequestPort` implemented by
`AnswerQuestionHandler`
(`financial_analysis/application/commands/answer_question.py`). That handler
proposes through the `LlmPort` (LangChain structured output against an
OpenAI-compatible endpoint), validates, runs the `AnalysisPipeline`, and the
`Text | Image | Dataframe | Plotly` contents it returns are rendered in the UI.

Logs are structured, human-readable console lines rendered by structlog,
emitted by per-module loggers (`entrypoints.app`, `contexts.user_interaction...`,
`chainlit`, `uvicorn`). The level comes from `logging.level` in `config.yaml`.
Startup prints one summary line and every request carries its trace context;
see Observability below.

In a container, set `CHAINLIT_HOST=0.0.0.0` (and `CHAINLIT_PORT` if needed).
The entrypoint is headless and owns the event loop: `Ctrl+C` (SIGINT) or
SIGTERM requests a graceful shutdown, and a second signal forces it.

The empty `chainlit.md` at the repo root keeps Chainlit's default readme
screen off. The first screen shows **starters** (suggested questions)
generated deterministically from the active semantic catalog
(`domain/services/describe_capabilities.py`; ADR 0016) — they never go through
the LLM, so the scope shown is exactly the scope the validator enforces.

## Configuration

Application settings live in `config.yaml` at the repo root (gitignored;
`config.example.yaml` is the committed template). Every key is required, and a
missing key, an unknown key or a missing file fails startup:

```yaml
llm:
  model: gpt-4o-mini
  base_url: https://api.openai.com/v1   # any OpenAI-compatible endpoint
  api_key: CHANGE_ME
  temperature: 0.0
  timeout: 60.0
  headers:
    User-Agent: cantabria/0.1.0         # identify the client, not the SDK
  session_header: ""                    # per-conversation session id header

auth:
  allowed_domains: []                   # empty accepts any verified identity
  local_login_enabled: false            # true shows the user/password screen
  users_file: data/auth/users.yaml      # demo credentials (committed, no real secrets)
  role_map: {}                          # SSO email -> roles; others use default_roles
  default_roles: []

logging:
  level: INFO

observability:
  enabled: false                          # off by default; true needs the Langfuse profile
  host: http://host.docker.internal:3000  # Langfuse stack, see below
  public_key: ""                          # LANGFUSE_INIT_PROJECT_* values
  secret_key: ""                          # from infrastructure/.env
  environment: local
  release: ""
```

`CONFIG_PATH` overrides the file location. The optional `data` block points
the governed files (catalogs, prompts, capabilities) elsewhere — every field
defaults to the checkout's `data/` and each one has a `CANTABRIA_*` env
override (see `docs/como-usar.md` §5.5). Chainlit's own settings
(`CHAINLIT_*`, `OAUTH_GOOGLE_*`, `CHAINLIT_AUTH_SECRET`) stay in the
environment/`.env` because the framework reads them directly.

`session_header` names the HTTP header that carries the per-conversation
session id sent to the model endpoint; leave it empty when the provider does
not need one. OpenCode Go requires `session_header: x-opencode-session` and a
client-specific `User-Agent` in `headers`.

## Observability (Langfuse)

LLM calls can be traced to a self-hosted Langfuse v4 stack, the
`observability` profile of the root `compose.yaml` (services `langfuse-web`,
`langfuse-worker`, `langfuse-clickhouse`, `langfuse-minio`, `langfuse-redis`,
`langfuse-postgres`, on their own network; the Langfuse ClickHouse publishes
no host port, so it never collides with the data ClickHouse on 8123/9000).
Tracing is **off by default** (`observability.enabled: false`), so the app
runs without this profile. The application uses the Langfuse SDK as its
OpenTelemetry backend and instruments LangChain with OpenInference, so every
`ChatOpenAI` call becomes a generation with model, prompt, response and token
usage, and each user turn becomes a single trace with the authenticated user
and the conversation session attached.

### 1. Start the stack (on the Docker host)

Secrets live in `infrastructure/.env` (gitignored;
`infrastructure/.env.example` is the committed template). The files under
`infrastructure/docker/` that carry secrets are committed only as
`*.example` templates and rendered from that `.env` by the script:

| Rendered file (gitignored) | Template |
| --- | --- |
| `docker/langfuse/common.env`, `docker/langfuse/web.env` | `common.env.example`, `web.env.example` |
| `docker/postgres/password.txt` | `password.txt.example` |
| `docker/minio/root_user`, `docker/minio/root_password` | `root_user.example`, `root_password.example` |
| `docker/redis/redis.conf` | `redis.conf.example` |
| `docker/clickhouse/users.d/01-langfuse-user.xml` | `01-langfuse-user.xml.example` |

The remaining files under `infrastructure/docker/` carry no secrets and are
committed verbatim. The root `compose.yaml` only wires services, ports,
volumes and healthchecks.

Run the script from a repository checkout on the Docker host, outside the
devcontainer, so the relative bind mounts resolve to paths the daemon can
see (the root `.env` must exist too, because compose interpolates the whole
file):

```bash
cp infrastructure/.env.example infrastructure/.env   # fill in the values
./scripts/langfuse_up.sh                             # render + docker compose --profile observability up -d
```

The first boot takes a couple of minutes. Generate fresh API keys and
passwords per environment; the old committed defaults are gone on purpose.

The application inside the devcontainer reaches the published port through
`host.docker.internal` (see the `observability` block above).

Langfuse is then at http://localhost:3000 and MinIO's console at
http://localhost:9091. The admin user and the project API keys are created on
first boot from the `LANGFUSE_INIT_*` values in `infrastructure/.env`.

### 2. Point the app at it

Both the compose `app` service (`extra_hosts`) and the devcontainer resolve
`host.docker.internal` to the host, so the app reaches the published Langfuse
port through it (see the `observability` block in the configuration above).
Copy the rendered `LANGFUSE_INIT_PROJECT_*` keys into
`observability.public_key/secret_key` in `config.yaml` and set `enabled:
true`: when enabled, empty host/keys fail startup loudly instead of tracing
silently into the void. With `enabled: false` (the default) tracing is a
no-op, the app logs a warning, and no Langfuse connections are made. Spans are batched
by the SDK and flushed on shutdown: `entrypoints.app` calls
`shutdown_observability` after the UI server stops.

### 3. Startup banner, request context and readiness

At startup the app logs one `Cantabria starting` line with the effective
configuration: server address, tracing on/off, catalog and prompt versions,
and the ClickHouse ping result. Every user message binds `trace_id`,
`session_id` and `user_id` into the structlog context, so all logs of that
turn carry them; the binding is released when the turn ends.

`GET /health` is Chainlit's own trivial liveness check (`{"status": "ok"}`).
`GET /ready` is the Cantábria readiness probe (`src/entrypoints/health.py`).
It reports `clickhouse`, `mongo` (`ok` | `disabled (in-memory)` | `error`),
`qdrant` (`ok` | `ok (lexical: embeddings off)` | `disabled (lexical BM25)` |
`error`), `minio` (`ok` | `disabled` | `error`), `catalog_version` (`v3`),
`prompt_version` (`interpretation=v1,insight=v3,documental=v1`) and
`tracing`. It answers 503 only when ClickHouse is unreachable; any other error
keeps 200 with `status: degraded`.

## Google SSO (optional)

Login is off by default: without the Google credentials below, every request is
treated as anonymous (local development keeps working). To enable SSO:

1. In Google Cloud Console, create an OAuth client (Web application) and add
   `{CHAINLIT_URL}/auth/oauth/google/callback` as an authorized redirect URI.
2. Set the environment:

```bash
OAUTH_GOOGLE_CLIENT_ID=...
OAUTH_GOOGLE_CLIENT_SECRET=...
CHAINLIT_AUTH_SECRET=...     # generate with `chainlit create-secret`
CHAINLIT_URL=http://localhost:8000
```

Chainlit performs the OAuth flow and hands the normalized identity to the
`AuthenticateUserPort` implemented by `AuthenticateUserQuery` (auth context),
which accepts only verified emails and, when `auth.allowed_domains` is set in
`config.yaml`, only identities whose Google Workspace domain matches. The
accepted actor is projected into the Chainlit session; rejected identities see
the login error. With login enabled `CHAINLIT_AUTH_SECRET` is mandatory and a
missing secret fails startup.

## Local login (demo)

For demonstrating authentication and authorization without Google SSO, enable
the local user/password screen backed by `data/auth/users.yaml`:

```yaml
# config.yaml
auth:
  local_login_enabled: true
  users_file: data/auth/users.yaml
```

Restart the app (`python -m entrypoints.app`) and the login screen appears.
Demo credentials (public, documented here — never put real secrets in that
file, it is versioned):

| User | Password | Roles | Access |
| --- | --- | --- | --- |
| `analista` | `cantabria123` | `analista` | restricted: no `profitability`, only product/total axes |
| `admin` | `cantabria123` | `admin` | full, like `default` |

The password callback verifies the SHA-256 hash from `users.yaml` and projects
the actor with its roles into the session; `User.roles` then reach the
capabilities adapter (`data/auth/capabilities.yaml`), where the `analista`
entry allowlists a subset of metrics and axes. Asking for a denied metric
(e.g. profitability by segment as `analista`) is refused with `unauthorized`
by `validate_plan`. With `local_login_enabled: false` (the default) nothing
changes: the app runs anonymous and all existing tests keep passing.

`role_map` / `default_roles` assign roles to Google SSO identities by email
when SSO is used; local users always take the roles listed in `users.yaml`.

## Data & Infrastructure

Os **dados oficiais** (clientes, produtos, contratos, rentabilidade) vivem no
**ClickHouse** (`infra/`), gerados deterministicamente por `utils/`. O motor
determinístico lê o banco via Port + Adapter outbound; o LLM nunca o acessa.

### Subir e popular (reprodutível)

É o mesmo caminho do Quick start — não há um compose separado para o banco:

```bash
cp .env.example .env                          # defina as senhas
docker compose up -d --wait clickhouse        # profile core: só o banco
docker compose --profile seed run --rm seed   # schema + seed determinístico, na imagem do app
```

Determinismo garantido por imagem pinada (`clickhouse-server:24.8`) + seed
fixa no gerador + DDL versionado (`infra/clickhouse/init/00_schema.sql`).
Decisões do ClickHouse (usuários, perfil `readonly`, partições):
`docs/como-usar.md` §3.1 e `data/clickhouse.md`. Estrutura dos dados
fictícios: `data/base-ficticia.md` e `docs/data-statement.md`. Stores
opcionais já ligados na fiação (`src/entrypoints/composition.py`): MongoDB
(Conversation/Plan/Result/Artifact Store + outbox de eventos; ADR 0010),
Qdrant (RAG semântico com fallback BM25; ADR 0014) e MinIO (documentos de
referência versionados via `make ingest`; ADR 0014). Profile `stores`;
compose único e profiles: ADR 0008.

## Próximos passos

Em ordem de valor para a avaliação. Tudo abaixo está **ausente ou não medido** hoje; nada é dado como pronto.

1. **Medir o planner ao vivo.** O harness existe (`python -m eval --layer all --split dev --live`), mas o run com credencial ainda não foi feito: não há número de acurácia de rota/plano do componente generativo.
2. **Rodar o baseline text-to-SQL** (`--layer baseline --live`) nas 8 armadilhas de agregação e colar a tabela lado a lado em `docs/evaluation-report.md` — é a evidência central de que "LLM sem catálogo erra em silêncio".
3. **Comparar ≥ 2 modelos** (acurácia, latência, tokens) e separar modelo do planner e do redator na configuração.
4. **Camadas `explanation` e `e2e` ao vivo**, p50/p95 e custo agregados, consistência pass^k.
5. **Split `test` held-out** (protegido; exige aprovação humana), casos multi-turn e o `manifesto_qualidade` de dados.
6. **Persistência que falta:** upload dos gráficos ao MinIO (hoje `derived://`), leitura de documentos do MinIO no caminho de resposta, `CalculationResult` no Mongo; relatório oficial fictício para reconciliação (ADR 0006, camada 2).
7. **Métricas derivadas** `spread`/`real_return` (rentabilidade − CDI) — fora do escopo atual.

Dívidas conhecidas: `uv.lock` desatualizado (gerar no Linux); 2 violações de arquitetura toleradas (`structlog` em `application/`); `AnalysisPlan.id` deveria ser `analysis_plan_id`; `/ready` ignora `CANTABRIA_CATALOGS_DIR` para `catalog_version`; small-cell conservador em séries (ADR 0009); sanitização de palavras comuns só entre crases (ADR 0016); `infra/` (ClickHouse do app) e `infrastructure/` (observabilidade) deveriam ser um só diretório.

## Rastreabilidade (enunciado → evidência)

✅ com artefato; ⚠️ com a lacuna nomeada.

| Exigência do enunciado | Evidência | Status |
|---|---|---|
| Modelos de IA resolvendo o problema | gpt-4o-mini t=0 como planner (`langchain_llm.py`), redator (`langchain_insight.py`, `insight/v3`) e síntese documental (`langchain_documental.py`) | ⚠️ comparação de ≥2 modelos não executada |
| Prompts + orquestração controlada | prompts versionados em `data/prompts/**`, versão em `/ready` e em `AnalysisResult.prompt_version`; structured output + 1 retry de schema + 1 semântico (`tests/test_create_plan_retry.py`) | ⚠️ acurácia live não medida |
| Dados fictícios gerados, armazenados, consumidos | `utils/generate_cantabria_data.py` (seed determinística, `tests/test_generator_determinism.py`), ClickHouse + DDL, `dataset_version` hash, `docs/data-statement.md` | ⚠️ `manifesto_qualidade` ausente |
| Estratégia de LM + avaliação | `docs/tech-justification.md`; harness `src/eval/` (engine × oráculo 37/37, redteam 16/16), `docs/evaluation-report.md`, ADR 0015 | ⚠️ baseline e `explanation`/`e2e` pendentes |
| Arquitetura com decisões e trade-offs | `docs/architecture/*.md`, `tests/test_architecture.py`, `docs/decisions.md` (D-0001–D-0017) | ⚠️ diagrama de sequência é textual |
| Ética, privacidade, IA responsável | `docs/responsible-ai.md` (LGPD × mecanismo × teste, OWASP → RT-01..16, k = 10 ADR 0009, `input_guard.py`) | ⚠️ falso positivo medido só em RT-06 |
| Funcional, empacotado, reprodutível | `Dockerfile`, `compose.yaml` com profiles (ADR 0008), `make demo|data|test|eval|preflight`, `.github/workflows/ci.yml` | ✅ |
| Documentação detalhada | este README + índice acima | ✅ |
| Escalável, seguro, eficiente | agregação no banco, cálculo ∥ RAG, histórico limitado (`tests/test_latency.py`); testes de segurança (`test_input_guard.py`, `test_chainlit_privacy.py`, redteam) | ⚠️ sem benchmark p50/p95 |
| Justificativa tecnológica com exemplos | `docs/tech-justification.md`; exemplos medidos: engine × oráculo, redteam | ⚠️ baseline medido pendente |
| Demo ao vivo + Q&A 90 min | `docs/demo.md` (casos `demo: true` de `data/eval/dev.yaml`, `make preflight`, fallback, Q&A) | ⚠️ sem gravação de fallback |

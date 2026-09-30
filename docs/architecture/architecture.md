# Architecture Overview

## O que mudou desde a versão original

Este documento foi escrito antes do código, com camadas "Presentation / DTOs /
Use Cases / Entities". O código real segue ports & adapters ao redor de um
núcleo DDD/CQRS (`AGENTS.md`, verificado por `tests/test_architecture.py`).
Diferenças, com a decisão correspondente:

| Tema | Versão original | Hoje | Decisão |
|---|---|---|---|
| Layout por contexto | `entities/`, `use_cases/`, `rules/` | `domain/` (agregados, VOs, `services/`) · `application/{commands,queries,policies}` · `ports/{inbound,outbound}` · `adapters/{inbound,outbound}` | ADR 0002 |
| Camadas transversais | "Infrastructure" | `src/shared/` (kernel puro, sem I/O) · `src/cross_cutting/` (config, logging, observability, mongo, outbox) · `src/entrypoints/` (composition root, `/ready`) | ADR 0002, ADR 0007 |
| Use cases | `create_plan`, `generate_insight`, `retrieve_conversation`… | handlers reais: `SubmitQuestionHandler` (user_interaction) → `AnswerQuestionHandler` + `AnalysisPipeline` (financial_analysis) → `ExecuteCalculationsHandler` (financial_calculation); policies `PersistResultsPolicy`, `BuildArtifactsPolicy` | ADR 0002 |
| Agregados e eventos | entidades "pequenas dataclasses" | `AnalysisRequest`, `Calculation`, `Conversation` emitem eventos de domínio; handlers só carregam, chamam, salvam e publicam (outbox Mongo) | ADR 0002, ADR 0010 |
| Métricas | 4 | 7 (`cdi_rate`, `selic_rate`, `inflation_ipca` como métricas macro, só grão total) | ADR 0013 |
| Nomes | `calculationplan_id`, `statisticalmethod` | `calculation_plan_id`, `statistical_method` (snake_case sempre) | `AGENTS.md` |
| Datastores | todos obrigatórios | ClickHouse obrigatório; Mongo/Qdrant/MinIO opcionais com degradação graciosa, reportados em `/ready` | ADR 0003, 0010, 0014 |
| Gráficos | não descritos | determinísticos do `AnalysisResult` (`PlotlyArtifactBuilder`), nunca tool-use livre | ADR 0005 |
| Fronteira generativa | "grounding / safety validation" | guardrails de entrada + `validate_plan` + gate de lastro programático e bloqueante + rodapé/"Como calculei" | ADR 0006, 0009, 0016 |

Layout real (copiado de `AGENTS.md`):

```
src/contexts/<context>/domain/        aggregates, entities, value objects, enums, domain events, errors, services/
src/contexts/<context>/application/   commands/  queries/  policies/
src/contexts/<context>/ports/         inbound/ (driving)  outbound/ (driven)
src/contexts/<context>/adapters/      inbound/ (driving)  outbound/ (driven)
src/shared/                           shared kernel: pure primitives + DomainEvent/AggregateRoot base. No I/O, no framework.
src/cross_cutting/                    cross-cutting infrastructure: config, logging, observability, resources, mongo
src/entrypoints/                      composition root (the only place that knows every context), CLIs, health
```

Leia "Presentation" como *adapters inbound* (`chainlit.py`), "Use Cases" como
*application/commands*, "Entities" como *domain* e "Bootstrapper" como
`src/entrypoints/composition.py` + `app.py`.

This document describes the application architecture used in this project. The system combines **Domain-Driven Design (DDD)** with the **Ports & Adapters (Hexagonal) Architecture**. DDD provides the strategic structure — the business domain is split into **Bounded Contexts** — while the hexagonal style isolates the business logic within each context from external technologies such as user interfaces, APIs, and databases. Together they also allow testability.

The core principle is simple: **the business logic does not depend on external technologies; external technologies depend on the business logic.** This is achieved through Ports (interfaces) and Adapters (implementations), all wired together by a central Bootstrapper.

The source code lives under `src/`, organized as `contexts/<bounded_context>/` plus the shared `shared/`, `entrypoints/` (composition root) and the per-context `ports/`/`adapters/` packages.

---

## Architectural Boundary and the Bootstrapper

The application is enclosed within a single boundary. Everything inside this boundary is **configured and connected by the Bootstrapper**.

The Bootstrapper is responsible for assembling the application at startup:

* It instantiates the internal components (Presentation, Use Cases, Infrastructure).
* It connects each Port to its corresponding Adapter.
* It performs dependency injection so that the business layer never instantiates concrete technologies directly.

The Bootstrapper is the only component that knows both the business layer and the infrastructure layer, keeping the rest of the system decoupled.

---

## External Interfaces (Outside the Boundary)

Two external entry points communicate with the application:

* **Web UI** — the graphical interface used directly by end users.
* **API** — the programmatic interface used by external systems and integrations.

Both interact with the application through the **Presentation** layer using bidirectional communication: they send requests in and receive responses back. They sit outside the boundary because they are consumers of the application, not part of its core.

---

## Internal Layers

### Presentation

The Presentation layer is the entry point into the application. It exposes the system to the Web UI and API.

Responsibilities:

* Receive and validate incoming requests
* Convert input into DTOs
* Invoke the appropriate Use Case
* Convert results back into response DTOs

The Presentation layer holds no business rules and no persistence logic.

### DTOs (Data Transfer Objects)

DTOs move data between the Presentation layer and the Use Cases layer.

* A **request DTO** flows downward (Presentation → Use Cases).
* A **response DTO** flows upward (Use Cases → Presentation).

DTOs standardize how data is transported between layers and prevent domain entities from being exposed directly to the outside world.

### Use Cases

The Use Cases layer is the center of the application and contains the business workflows (for example, *"Analyze the profitability dispersion across segments"*).

Responsibilities:

* Orchestrate business operations
* Manipulate domain Entities
* Request external capabilities exclusively through Ports

The Use Cases layer is unaware of which database, framework, or external service is used. It depends only on abstractions.

### Entities

Entities represent the core business concepts (for example: Calculation, Analysis, User).

Characteristics:

* They encapsulate business rules and invariants
* They have their own identity
* They are fully independent from external technologies

Entities are the most stable and protected part of the system, connected directly to the Use Cases layer.

---

## Bounded Contexts (Strategic DDD)

The application boundary is not a single monolithic model. Following DDD strategic design, the domain is partitioned into **Bounded Contexts**, each with its own ubiquitous language and its own hexagonal internals (`domain/`, `application/{commands,queries,policies}`, `ports/{inbound,outbound}`, `adapters/{inbound,outbound}`).

The implemented contexts (`src/contexts/`) are:

* **`auth`** — authentication and authorization. Determines which metrics, dimensions, analyses and datasets a user may query. Queries: `AuthenticateUserQuery`, `AuthenticateLocalUserQuery`, `AuthorizeQuery` (`application/queries/`); capabilities from `data/auth/capabilities.yaml` (`adapters/outbound/yaml_capabilities.py`).
* **`user_interaction`** — the conversational entry point. Receives the natural-language question, persists it, retrieves relevant conversation history, forwards the request to the analysis context, and turns the final result into a user-facing response. Command: `SubmitQuestionHandler` (`application/commands/submit_question.py`) owns the `Conversation` aggregate (history already PII-redacted) and publishes its events; inbound adapter: `adapters/inbound/chainlit.py`.
* **`financial_analysis`** — orchestrates the analytical workflow. It proposes and validates the plan, retrieves corporate knowledge (RAG), coordinates execution, and produces insights and the final `AnalysisResult`. Command: `AnswerQuestionHandler` (`application/commands/answer_question.py`: input guard → planner → `validate_plan` → route) delegating execution to `AnalysisPipeline` (`execute_pipeline.py`: calculation ∥ knowledge → `execute_analysis` → grounding gate → artifacts); domain services `input_guard`, `validate_plan`, `execute_analysis`, `describe_capabilities`, `provenance` (`domain/services/`); policies `PersistResultsPolicy`, `BuildArtifactsPolicy` (`application/policies/`). It hosts the reusable, deterministic **statistical methods** (`mean`, `std`, `dispersion`, `variation`, `correlation`, ...) and **operations** (`ranking`, `comparison`, ...).
* **`financial_calculation`** — deterministic financial execution. It runs validated `CalculationPlan`s and produces `CalculationResult`s. Command: `ExecuteCalculationsHandler` (`application/commands/execute_calculations.py`, inbound port `ExecuteCalculationsPort`) over the `Calculation` aggregate; reuse key in `domain/reuse_key.py`. The generic formulas (ratio, sum, distinct, latest, compound/annualize) live in the pure shared kernel (`src/shared/aggregation.py`); the 7 metric bindings (`profitability`, `outstanding_balance`, `contract_count`, `customer_count`, `cdi_rate`, `selic_rate`, `inflation_ipca`) live in `domain/metric_binding.py`. The ClickHouse adapter **pushes aggregation down** and returns only the components per group/period through the `fetch_aggregated` Port — no raw fact rows cross the boundary.

These contexts collaborate through their Use Cases and Ports; they never reach into each other's persistence or entities directly.

### Domain entities

The core plan entities are deliberately small dataclasses:

* `CalculationPlan(calculation_plan_id, metric, period)` — **one metric per plan**. `metric` carries the calculation rule (`rule_id`), the **breakdown** (`subjects`, each becoming one group-by column) and the optional **sample** (`sample` — the population that enters, a `WHERE` that creates no rows). The plan id **is** the series reference, so no separate metric id is needed; two plans may share the same window.
* `AnalysisPlan(id, statistical_method, operations, presentation)` — each `statistical_method` computes a number (`method`), reading either `calculation_plan_ids` (raw calculated values) or `statistic_refs` (the output of an earlier method); methods carry **no `params`**. `presentation` (optional, closed catalog `bar` · `line` · `ranking_bar` · `table`) drives the deterministic chart (ADR 0005). Known debt: the field is `id`, should be `analysis_plan_id` (`README.md` → "Próximos passos"). The optional `operations` then arrange the result (`ranking`, `comparison`, ...), and that is where `params` live.

The `AnalysisPlan` references the **calculation plans** by `calculation_plan_id`; it does not embed them. Because each plan carries exactly one metric, a plan reference is unambiguous — it points at one homogeneous series. See `plans.md` for the full field reference and `flow.md` for examples.

---

## Ports and Adapters

This is the defining mechanism of the architecture.

### Ports

Ports are **interfaces defined by the business layer**. They declare *what* the application needs (for example, "retrieve calculation data") without specifying *how* it is done. Use Cases depend only on Ports.

### Adapters

Adapters are the **concrete implementations of Ports**. Each Adapter connects a Port to a specific technology in the Infrastructure layer.

* The **Port** defines the contract.
* The **Adapter** fulfills that contract using a specific technology.

Because Use Cases depend only on Ports, a technology can be replaced simply by swapping its Adapter, with no changes to the business logic.

---

## Infrastructure

The Infrastructure layer contains all technical implementations required by the application, such as database access, external API calls, file handling, and integrations.

Responsibilities:

* Implement the Ports defined by the Use Cases
* Communicate with external systems and databases
* Handle all technical and persistence details

Infrastructure depends on the business layer, never the other way around.

---

## Datastores (Outside the Boundary)

Several datastores sit at the bottom, outside the application boundary, and are accessed only through Adapters. Each maps to a role described in `flow.md`:

* **MongoDB** (optional, `MONGO_URL`) — document database. Backs the **Conversation Store**, **Plan Store**, **Result Store**, **Artifact Store** (metadata only) and the **event outbox** (`events` collection) — `adapters/outbound/mongo_*_store.py`, `cross_cutting/event_outbox.py`, wired in `src/entrypoints/composition.py::build_event_wiring`. Without it every store is in-memory and `/ready` says `disabled (in-memory)` (ADR 0010). The calculation reuse store (`InMemoryCalculationStore`) is still in-memory even with Mongo.
* **ClickHouse** — analytical/columnar database holding the official source data (customers, segmentation, profitability) consulted by the deterministic calculation engine.
* **Qdrant** (optional, `QDRANT_URL` + `embeddings` config) — vector database storing one point per `##` section of the approved documents; `ResilientKnowledgeAdapter` falls back to local BM25 (`LocalKnowledgeAdapter` over `data/knowledge/*.md`) when Qdrant is absent, down or returns nothing (ADR 0014).
* **MinIO** (optional, `MINIO_ENDPOINT`) — object storage. Backs the **Value Object Store** for versioned approved documents (`MinioDocumentStoreAdapter`, written by `make ingest` / `utils/generate_reference_documents.py`; reported in `/ready`). Generated charts are **not** uploaded yet: the **Artifact Store** (MongoDB) keeps metadata with `location = derived://analysis-result/<artifact_id>`, meaning the artifact is reproducible from the `AnalysisResult` (ADR 0005, Evidência).

They are external technologies, which is why the business logic reaches them only through Ports and Adapters, never directly.

---

## End-to-End Data Flow

A typical request travels through the system as follows:

```text
Web UI / API
      ↓ request
Presentation
      ↓ DTO
Use Cases  ──────────→ Entities
      ↓ Port
Adapter
      ↓
Infrastructure
      ↓
MongoDB / ClickHouse / Qdrant / MinIO
      ↑
Infrastructure
      ↑
Adapter
      ↑
Use Cases
      ↑ DTO
Presentation
      ↑ response
Web UI / API
```

---

## The Dependency Rule

All dependencies point inward, toward the business core:

```text
Presentation → Use Cases → Entities
Infrastructure → Ports ← Use Cases
```

The business logic never depends on frameworks, databases, or external services.

---

## Benefits of This Architecture

* **Independence:** business logic is isolated from external technologies.
* **Testability:** Use Cases and Entities can be tested without databases or frameworks.
* **Flexibility:** technologies (e.g., swapping the object store or the vector database) can be replaced by changing only Adapters.
* **Maintainability:** clear separation of concerns and low coupling.
* **Scalability:** layers can evolve independently.

In summary, the diagram shows a system where external interfaces and databases live at the edges, the business logic lives protected at the center, and the Bootstrapper connects everything through Ports and Adapters.

---

## Deterministic Financial Execution and Generative AI

The hexagonal dependency rule also defines a strict AI boundary.

The LLM does not receive direct database execution capabilities and does not calculate authoritative financial figures.

The runtime path is:

```text
Natural-language question
        ↓
Financial Analysis orchestration
        ↓
LLM proposes structured semantic plan
        ↓
Deterministic plan validation
        ↓
Financial Calculation
        ↓
Generic deterministic calculation family
        ↓
CalculationResult
        ↓
Statistical methods → operations
        ↓
AnalysisResult
        ↓
LLM explanation over verified evidence
        ↓
Grounding / safety validation
        ↓
Response
```

The model proposes; deterministic application code authorizes and executes.

### Generic calculation families

Financial Calculation is intentionally implemented through a small registry of reusable metric bindings rather than one implementation for every natural-language question.

There is **one binding per metric, not per dimension**:

- `profitability` — ratio, weighted by outstanding balance
- `outstanding_balance` — stock
- `contract_count` — distinct count
- `customer_count` — distinct count
- `cdi_rate`, `selic_rate`, `inflation_ipca` — market reference rates (`compounded_rate` family, `macro: true`: only the `total` grain, no business axis, no sample; source BACEN/SGS with a versioned offline cache — ADR 0013)

The formula itself is a **pure, domain-agnostic operator** in the shared kernel (`src/shared/aggregation.py`): `ratio`, `sum_values`, `count_distinct`, `latest`, `compound_rate`, `annualize_rate`. The binding is business: which measures, unit, official source, and how the number rolls up in time (`ratio` | `stock` | `count`). This split keeps the formula reusable by other contexts (e.g. the analysis statistics) while the business semantics stay in `financial_calculation/domain`.

The dimension is carried by the plan's Subjects, which determine the base table, the join path and the group-by column. Splitting a binding per dimension would duplicate the same formula and multiply the registry with every new axis.

The ClickHouse adapter **compiles the requested aggregation to SQL** and executes it in the warehouse: `SUM`/`uniqExact`/`argMax` run in ClickHouse, and the adapter returns only the components (`{numerator, denominator}`, `{value}`) at the requested grain. The core combines those components with the shared operators and applies the absence policy (`null` for an empty eligible population — never `0.0`). A group with no eligible balance is therefore `null`, not a plausible-but-wrong zero.

A `CalculationPlan` selects the family through `rule_id` and details the request through governed breakdown subjects, hierarchy levels, period semantics, and an optional sample.

The selected family remains responsible for deterministic financial semantics such as source ownership, historical alignment, compatibility, data-quality eligibility, and aggregation — including **how the metric rolls up across periods**, which differs per family and is the one place where a wrong number would pass silently.

### Generic analysis functions

Financial Analysis similarly uses reusable deterministic methods and operations, such as:

- methods (`statistical_method`): `null`, `mean`, `median`, `mode`, `std`, `dispersion`, `variation`, `trend`, `share`, `correlation`, `outlier` (closed catalog — `tests/test_invariants.py::test_catalogo_de_metodos_e_operacoes_e_fechado`; `distribution` was removed and `decomposition` is an operation)
- operations: `ranking`, `comparison`, `cumulative_share`, `selection`, `pivot`, `decomposition`

The `AnalysisPlan` orchestrates them: each `statistical_method` computes a number over the calculated values (or over an earlier method's output), and the optional `operations` arrange that result. Methods carry no `params`; operations do (`order`, `top_n`, `axis`, `cutoff`).

Analysis functions receive verified `CalculationResult` values only. They do not query source systems or redefine the eligible financial population.

### Semantic catalogs as an adapter-controlled governance boundary

Canonical IDs used by the business/application layers are independent from regional physical source names.

For example:

```text
customer_segmentation.segment
        ↓ semantic catalog / source adapter
Brazil: ds_segm
Future region: region-specific source mapping
```

This allows Banco Cantábria to expand globally without embedding Brazilian physical schemas into the business core.

The sample follows the same rule. Because the sample catalog is the axis catalog, it resolves through the very same mapping:

```text
customer_principality.principality_depth = high
        ↓ governed semantic resolution
Brazil: principalidade = alta
```

The physical mapping is an infrastructure concern. The business plan carries only canonical governed meaning.


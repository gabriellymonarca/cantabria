# DDD approach

This project follows DDD principles because Banco Cantábria's core problem requires business integration and semantic reconciliation across financial domains.

## Domains and subdomains

### Core Domains

#### Financial Calculation

- Execution of deterministic operations across financial entities.
- Semantic integration of data silos.
- Enforcement of declared compatibility, historical alignment, calculation rules, and source ownership.

#### Financial Analysis

- Interpretation of the user's question.
- Selection of the deterministic analysis to apply to verified calculation results.
- Interpretation and explanation of deterministic financial and statistical results.

### Support Domain

#### User Interaction

- Management of conversations.
- Presentation of financial analysis.

### Generic Domain

#### Auth

- Management of identities and permissions.

## Context mapping

- Financial Analysis conforms to Auth and Financial Calculation via OHS.
- User Interaction conforms to Financial Analysis and Auth via OHS.

## MVP hypothesis

If executives and analysts can query Customer, Product, and Profitability data using natural language—including semantically controlled combinations across those domains—they will obtain analyses that currently require querying and reconciling data across different sources or business areas.

### Acceptance examples

1. Analyze the Profitability dispersion across Segments.
2. How are Products distributed across Segments?
3. Are Customers with higher Vinculação more profitable?
4. Which Product is the most profitable among Customers with High Principalidade?

These are acceptance scenarios for generic orchestration. They are not hard-coded intents and they do not define the complete set of questions Cantábria may answer.

---

# Bounded contexts

## Financial Calculation

`Calculation` is an entity formed by:

- `id` — unique Calculation identifier.
- `status` — processing status.
- `plan` — the governed description of what must be calculated.
- `results` — the verified values produced by deterministic execution.

### CalculationPlan

`CalculationPlan` is a value object from `Calculation` and answers:

> **What must be calculated?**

The MVP contract is intentionally small:

```yaml
CalculationPlan:
  calculation_plan_id: <plan identifier — the series and the window>

  metric:
    id: <optional readable label>
    rule_id: <generic deterministic calculation family>

    subjects:
      - type: <canonical subject type>
        level: <canonical governed level>

    # optional — the population that enters (WHERE, creates no rows)
    sample:
      - type: <canonical subject type>
        level: <canonical governed level>
        value_id: <canonical governed value>

  period:
    start: <date>
    end: <date>
    type: <series | snapshot>
    grain: <month | quarter | year | total>
```

`grain: total` collapses the **whole window** into one value per group, re-derived by the family (ratio → Σnumerator ÷ Σdenominator; stock → end-of-period reading; count → point-in-time at the window end). It is how "one number per entity for the period" is expressed — the analysis layer never averages a series of rates.

A plan carries **exactly one Metric**, and each Metric carries **one or more Subjects** plus an optional **sample**. Several metrics are expressed as **several plans sharing the same window**.

- the Metric — *what* to measure;
- its Subjects — *by which dimensions* the metric is broken down, producing the **joint** distribution rather than independent marginals;
- its sample — *who enters*, a narrowing that creates no rows.

#### The plan is the series and the window

Because a plan carries a single metric, its `id` **is** the series reference — there is no separate metric handle. `period` is the window; two metrics on the same window are two plans, and that is legitimate.

Within a plan the window is shared **structurally** (there is only one `period` field). Between plans that guarantee does not exist, so `validate_plan` checks the topology when plans are read together (e.g. by `variation`).

### Metric

A Metric is **the series**: one metric, one unit, one axis, one population. It is the unit the analysis reads. Since the plan carries exactly one metric, the plan id is the series reference.

- `id` — an optional readable label (e.g. `m_prof`). It is **not** a reference key.
- `rule_id` — the calculation family that executes it. This is the closed catalog.

A plan cannot mix units because it cannot carry more than one metric: a reference to `calculation_plan_id` always points at one homogeneous series. Two metrics of different units are two plans, and an analysis that reads them does so through two methods.

Each `rule_id` is the value Cantábria must calculate or deterministically aggregate.

| `id` | Aggregation shape | Formula | `unit` |
|---|---|---|---|
| `profitability` | ratio | Σ Margin ÷ Σ Outstanding Balance (already annual) | `decimal_rate` |
| `outstanding_balance` | stock | Σ Outstanding Balance | `currency` |
| `contract_count` | distinct count | distinct active Contracts | `count` |
| `customer_count` | distinct count | distinct Customers holding an active Contract | `count` |

`outstanding_balance` is the single canonical name for the live portfolio. "Carteira", "saldo" and "estoque" are **synonyms resolved by the semantic catalog**, never alternative ids inside a plan.

Cantábria never recreates a source-owned authoritative value such as contract-level Profitability. It may only apply the approved deterministic downstream aggregation defined for that metric.

#### Stock, not flow

The MVP models **stock**, not **flow**. Origination/disbursement ("produção"), net production and in-period terminations are defined business concepts with **no calculation family**: the data model has no flow grain. Such requests are refused by scope, not treated as errors.

### Subject

A `Subject` defines **what the metric is analyzed by**.

Each Subject has:

- `type` — the canonical business dimension/type. It determines **which base table and join path** are used.
- `level` — the governed granularity inside that type. It determines **which column** is grouped by.

The governed axes:

| `type` | `level` |
|---|---|
| `customer_segmentation` | `person_type`, `segment_group`, `segment`, `subsegment_group`, `subsegment` |
| `customer_relationship` | `relationship_depth` (Vinculação) |
| `customer_principality` | `principality_depth` (Principalidade) |
| `product` | `product_group`, `product`, `subproduct` |
| `total` | `total` (no grouping — aggregate series) |

Physical Brazilian source fields such as `ds_segm`, `ds_produto`, `principalidade_score`, and `vinculacao_score` do **not** appear in the `CalculationPlan`. They are resolved through the active semantic catalog and source adapter; the governed depth (`high`/`medium`/`low`) is derived from the raw score by the adapter.

**Each Subject becomes exactly one group-by column.** The engine never infers a level: two levels of the same type require two Subjects (e.g. `segment` + `subsegment` for a drill-down).

There is **no individual Customer grain**. Customer identifiers are join keys, never group-by columns, and never appear in a result.

### Sample

The **sample** is the metric's population: who enters the calculation. It is a `WHERE`, **not** a `GROUP BY` — it shrinks who is counted without producing rows in the result. It lives at the metric level, not inside a Subject, because it applies to the whole metric.

**The sample catalog is the axis catalog.** Any `(type, level)` valid as a Subject is valid as a sample condition — a condition is structurally a Subject plus a value.

```yaml
sample:
  - type: customer_principality
    level: principality_depth
    value_id: high
```

This means:

> Use only observations belonging to Customers whose source-reported Principalidade is High for the applicable historical month.

The same governed classification may act as an **axis** or as a **sample**, depending on the question:

| Question | Role of Principalidade | Result |
|---|---|---|
| Profitability **by** Principalidade | axis (Subject) | one row per level |
| Most profitable Product **among high** Principalidade | sample | Principalidade absent from the result |
| Profitability by Product **and** Principalidade | both are axes | one row per pair |

A sample is **not**:

- a free-form query filter;
- arbitrary SQL;
- a new calculation formula;
- an LLM-invented condition.

It must resolve through the active semantic catalog. Its physical source field, source value, temporal semantics, and compatibility with the selected calculation family are deterministic and governed.

The MVP supports **a single equality per condition**, without operators, `AND`/`OR`, negation, multi-value `IN`, `HAVING` or percentile populations. The list allows more than one condition; the restriction is structural, not by field name.

### Multiple subjects

A Metric may carry one or more Subjects.

This is required for cross-dimensional calculations such as Product by Customer:

```yaml
subjects:
  - type: customer_segmentation
    level: segment

  - type: product
    level: product
```

Two Subjects on **one** Metric produce the **joint** distribution — one cell per pair. This is not the same as two Metrics with one Subject each, which would produce two independent **marginals** (contracts per segment *and* contracts per product), from which the joint cannot be recovered.

### Generic calculation families

The MVP does **not** implement one calculation class/function for every natural-language question.

There is **one family per Metric, not per dimension**. The dimension is already carried by the Subjects, which determine the base table, the join path and the group-by column. A `profitability_by_customer` / `profitability_by_product` split would be the same formula duplicated, and every new dimension would multiply the registry.

The registry:

1. `profitability`
2. `outstanding_balance`
3. `contract_count`
4. `customer_count`
5. `cdi_rate`
6. `selic_rate`
7. `inflation_ipca`

A `rule_id` outside the registry is an error — the engine never invents a calculation.
Families 5–7 are **market references** (`macro: true` in the catalog): they share one aggregation kind, `compounded_rate`, and exist only at the `total` grain.

The family owns the deterministic business execution semantics: source ownership, historical alignment, data-quality eligibility and aggregation. The plan only selects among governed possibilities. Each family must preserve the metric's authoritative semantics and use the historically correct Customer classification where applicable.

#### Aggregation has two directions

Aggregation happens along two independent axes, and the rules differ:

- **across groups** — many rows of the same period collapse into one;
- **across periods** — many periods collapse into one (`grain` coarser than the source grain).

A metric may be summable in one direction and nonsense in the other: a portfolio of R$ 200 held for three months is still R$ 200, not R$ 600. Getting this wrong returns a **plausible but wrong number, silently** — no error, no null.

| Family | Across groups | Across periods |
|---|---|---|
| `profitability` | not summable (ratio) | not summable (ratio) |
| `outstanding_balance` | summable | **not summable** — stock |
| `contract_count` | summable (disjoint groups) | **not summable** — point in time |
| `customer_count` | only if groups are disjoint | **not summable** — point in time |
| `cdi_rate`, `selic_rate`, `inflation_ipca` | not applicable — no business axis | **compounded**, never mean nor sum |

A distinct count is only summable across groups when each counted entity belongs to **exactly one** group. A Contract has one Product and one Customer, so it is summable across both. A Customer has one Segment but may hold several Products, so `customer_count` is summable across Segment and **not** across Product.

**The governing rule:** the engine never aggregates an already-aggregated result. Every result row is recomputed from the fact tables directly at the requested grain. With `grain: quarter` the three monthly results are not combined — the engine returns to the facts, filters the three months and computes once. With `grain: total` the same rule applies to the entire window: one row per group, computed once from the facts.

#### `profitability`

Profitability is a **ratio**, weighted by eligible Outstanding Balance. It is never the simple average of rates.

At a coarser grain the ratio must be **re-derived** at that grain:

- correct — `Σ Margin(3 months) ÷ Σ Outstanding Balance(3 months)`;
- wrong — the mean of the three monthly rates.

The two only coincide when the balance is constant, and diverge the more it varies within the period. This is precisely why the source stores Margin and Outstanding Balance in currency rather than the rate. Weighting is owned by the family and is **never** a plan choice; an unweighted variant is not offered because it is a wrong number. The analysis layer reflects this: `mean` and `dispersion` are forbidden on `profitability`, and the window rate is obtained through `grain: total` with `method: null`.

#### `outstanding_balance`

The live portfolio. Additive across contracts and groups, **never across periods** — summing three months would triple the stock. At a coarser grain the declared rule applies: end-of-period value (default) or mean of the periods.

#### `contract_count` and `customer_count`

Distinct counts of active Contracts and of Customers holding an active Contract. A Contract is active at a reference date when it started on or before that date and has either no termination date or one on or after it. At a coarser grain these are a point-in-time reading at the end of the period, never a sum.

Product distribution across Customers — the UC2 acceptance scenario — is `contract_count` with two Subjects, not a dedicated family.

#### `cdi_rate`, `selic_rate` and `inflation_ipca` — market references

Monthly rates published by the Central Bank (SGS series), ingested offline and read from the warehouse like any other metric: the model never fetches or recomputes a rate (ADR 0013).

- **Grain.** These are single national series: they have no Segment, Product, Customer or Vinculação. The only valid Subject is `total.total`, with no `sample`; any business axis is `not_expressible`.
- **Across periods.** The rate of a window is the **compounded** rate of its months, `R = Π(1 + rᵢ) − 1` — never the mean, never the sum.
- **Annualization.** The metric value is always the **annual-equivalent rate**, `(1 + R)^(12 / n) − 1`, where `n` is the number of months observed in the bucket. This is the same annual basis as `profitability` (whose margin is already annualized), so the two can be placed side by side. A 12-month window is the fixed point (annualized = accumulated); **a single month is also annualized**, `(1 + r)^12 − 1` — the published monthly rate is never shown as the metric value.
- **Absence.** An empty bucket or a monthly rate ≤ −100% is `null` with a reason, never `0`.
- **Provenance.** Every point carries source, series code and extraction date; those are physical boundary fields and never leave the adapters.

### CalculationPlan examples

#### UC1 — Profitability dispersion across Segments

```yaml
CalculationPlan:
  calculation_plan_id: calc1

  metric:
    id: m_prof_seg
    rule_id: profitability
    subjects:
      - type: customer_segmentation
        level: segment

  period:
    start: 2026-05-31
    end: 2026-08-31
    type: series
    grain: month
```

#### UC2 — Product distribution across Segments

Two Subjects on the metric: the joint distribution, one cell per (Segment, Product) pair.

```yaml
CalculationPlan:
  calculation_plan_id: calc2

  metric:
    id: m_count_seg_prod
    rule_id: contract_count
    subjects:
      - type: customer_segmentation
        level: segment
      - type: product
        level: product

  period:
    start: 2026-08-31
    end: 2026-08-31
    type: snapshot
    grain: month
```

#### UC3 — Profitability by Vinculação

```yaml
CalculationPlan:
  calculation_plan_id: calc3

  metric:
    id: m_prof_vinc
    rule_id: profitability
    subjects:
      - type: customer_relationship
        level: relationship_depth

  period:
    start: 2026-05-31
    end: 2026-08-31
    type: series
    grain: month
```

#### UC4 — Product Profitability among High Principalidade Customers

Principalidade narrows the population; it does not appear in the result.

```yaml
CalculationPlan:
  calculation_plan_id: calc4

  metric:
    id: m_prof_prod_high
    rule_id: profitability
    subjects:
      - type: product
        level: product
    sample:
      - type: customer_principality
        level: principality_depth
        value_id: high

  period:
    start: 2026-08-01
    end: 2026-08-31
    type: series
    grain: month
```

#### One metric per plan

Several metrics are several plans sharing one window. This is what a trend question reads — the analysis layer compares the series across plans.

```yaml
# three plans, same window
CalculationPlan: { calculation_plan_id: calc_prof_total, metric: {rule_id: profitability,       subjects: [{type: total, level: total}]}, period: {start: 2025-09-30, end: 2026-08-31, type: series, grain: month} }
CalculationPlan: { calculation_plan_id: calc_bal_total,  metric: {rule_id: outstanding_balance, subjects: [{type: total, level: total}]}, period: {start: 2025-09-30, end: 2026-08-31, type: series, grain: month} }
CalculationPlan: { calculation_plan_id: calc_cust_total, metric: {rule_id: customer_count,      subjects: [{type: total, level: total}]}, period: {start: 2025-09-30, end: 2026-08-31, type: series, grain: month} }
```

### CalculationResult

`CalculationResult` is a value object from `Calculation` and answers:

> **What verified values were obtained?**

Example. Each row is keyed by the combination of Subjects, each qualified by `type.level`. A sample never appears as a key: it shrank the population, it did not create rows. Because the plan carries one metric, `calculation_plan_id` identifies the series — no separate `metric_ref` is needed.

```yaml
CalculationResult:
  calculation_plan_id: calc1
  rule_id: profitability
  unit: decimal_rate
  values:
    - subjects: {customer_segmentation.segment: Varejo PF}
      period: 2026-06-30
      value: 0.132
    - subjects: {customer_segmentation.segment: Varejo PF}
      period: 2026-07-31
      value: 0.128
```

A cross-dimensional result (UC2) carries one row per pair:

```yaml
    - subjects: {customer_segmentation.segment: Varejo PF, product.product: Cartão}
      period: 2026-08-31
      value: 18432
```

#### Identities per row

`calculation_plan_id` links the row to the plan. `rule_id`, together with the Subjects, period and catalog version, forms the **reuse key** that makes a stored result recognizable across packages (see § Persistence in `flow.md`).

The result must also be traceable to its deterministic rule, source owners, source fields, temporal resolution, catalog version, and data-quality eligibility decisions.

---

## Financial Analysis

`Analysis` is an entity formed by:

- `id` — unique Analysis identifier.
- `status` — processing status.
- `plan`.
- `results`.
- `question`.

### AnalysisPlan

`AnalysisPlan` answers:

> **How should the verified CalculationResult be mathematically/statistically analyzed?**

It does **not** embed the `CalculationPlan`s — it references them by `calculation_plan_id` — and it has two parts:

- **`statistical_method`** — *which quantity to compute*. Each method reads either `calculation_plan_ids` (raw calculated values) or `statistic_refs` (the output of an earlier method declared above). Methods carry **no `params`**: the method name decides the quantity and its output unit.
- **`operations`** — *what to do with the computed number*. Optional, and where `params` live.

Methods and operations form a **closed, enumerable** catalog — validation is a membership check, and anything outside it is refused as `not_expressible`. A method may only reference a method declared **before** it (no cycle).

```yaml
AnalysisPlan:
  analysis_plan_id: plan1
  statistical_method:
    - id: s1
      method: std
      calculation_plan_ids: [calc_prof_seg]
  operations:
    - id: o1
      type: ranking
      refs: [s1]
      params:
        order: desc
        axis: entity
```

#### Methods (`statistical_method`)

| `method` | Produces |
|---|---|
| `null` | the verified values, unsummarized |
| `mean` | mean of the series per entity (forbidden on `profitability`: the mean of monthly rates is not the window rate) |
| `median` | median of the series per entity |
| `mode` | most frequent value of the series (`null` when no value repeats) |
| `std` | standard deviation per entity (volatility) |
| `dispersion` | the full pack: `mean, median, std, variance, min, max, q1, q3, iqr` (forbidden on `profitability`) |
| `variation` | difference between **two** collapsed calculations: absolute (p.p. for a rate) and percent |
| `trend` | slope per entity over the ordered axis (time series, or an ordinal level encoded as rank) |
| `share` | part ÷ total (summable metric, collapsed result) |
| `correlation` | Pearson between **two** results, same entities, n ≥ 3 |
| `outlier` | atypical points of the result (IQR 1.5, at least 4 points) |

#### Operations (`operations`)

| `type` | Does | `params` |
|---|---|---|
| `ranking` | orders the result | `order`, `top_n`, `axis`: `entity`/`period` (always required) |
| `comparison` | shows values **side by side** | `across`: `entity`/`result` |
| `cumulative_share` | cumulative participation (Pareto) | `cutoff` |
| `selection` | keeps rows by condition relative to the result | `rule`, `value` |
| `pivot` | crosses two axes into a table | `rows`, `columns` |
| `decomposition` | each group's contribution to the total variation | `refs`: `[variation, share]`; contribution = `share_base × Δrate`; the sum closes against the total rate effect |

`ranking.axis` is **always required**: "which segment is the most profitable" orders **entities** while "which month was the best" orders **periods**; there is no inference.

`comparison` does not compute: it only puts values side by side. Direction is `trend`; "best/worst" is `ranking` with `top_n: 1`.

`decomposition` is the only operation that reads **two** methods: the variation and the share. It returns each group's **rate-effect** contribution (`share_base × Δrate`); the contributions sum to the total rate effect. A mix residual would require the shares of both windows — a future extension.

#### Comparing periods

`period` belongs to the `CalculationPlan`. Every period-against-period question is therefore expressed as **two `CalculationPlan`s sharing the same breakdown with different `period`s**, read together by a single `variation` method.

```yaml
# "Was August 2026 better than August 2025?"
statistical_method:
  - id: s1
    method: variation
    calculation_plan_ids: [calc_prof_2025_08, calc_prof_2026_08]
```

`variation` returns both the absolute difference (for a rate, already p.p.) and the percent change; there is no direction or mode to declare. Comparing two **method results** is `correlation` (which reads `statistic_refs`), not `variation`.

#### Temporal topology

Because the window is only guaranteed *within* a plan, comparing across plans requires four independent conditions — each one, on its own, produces a different wrong number:

| condition | what breaks without it |
|---|---|
| **disjoint** windows | overlapping ranges measure the period partly against itself; the variation comes out damped, always understated |
| **equal duration** | 3 months against 12 compares things of different nature |
| same **`grain`** and **`period.type`** | a quarter against a month, or a snapshot against a series, compares a point to a distribution |
| **chronological order** | getting the direction wrong inverts the **sign** — the answer becomes the opposite of the truth |

A *gap* between the windows is legitimate and is not checked: August 2025 vs. August 2026 skips eleven months and that is precisely what YoY means.

These analyses operate **only on verified CalculationResult values**.

They do not:

- query source databases;
- choose the eligible financial population;
- apply Customer or Product business classifications;
- calculate source-owned financial facts.

Population qualification and historical alignment belong to Financial Calculation.

### AnalysisResult

`AnalysisResult` answers:

> **What deterministic mathematical/statistical result was obtained?**

It **mirrors the shape of the `AnalysisPlan`**: every method comes back with its number, and every operation with its output. Each entry keeps the `id` and the `method`/`type` declared in the plan, which is what makes result and plan auditable against each other. It also carries its **provenance**: `catalog_version`, `dataset_version` and `trace_id`.

```yaml
AnalysisResult:
  analysis_plan_id: plan1
  catalog_version: v2
  dataset_version: <hash>
  trace_id: <id>
  statistical_method:
    - id: s1
      method: std
      value:
        - subjects: {customer_segmentation.segment: Atacado PJ}
          value: 0.052
        - subjects: {customer_segmentation.segment: Varejo PF}
          value: 0.031
  operations:
    - id: o1
      type: ranking
      refs: [s1]
      value:
        - rank: 1
          subjects: {customer_segmentation.segment: Atacado PJ}
          value: 0.052
        - rank: 2
          subjects: {customer_segmentation.segment: Varejo PF}
          value: 0.031
```

The row identity is the same `subjects` dictionary as the calculation — one breakdown (segment) or a crossing (segment × product). `variation` returns both terms per entity:

```yaml
  statistical_method:
    - id: s1
      method: variation
      value:
        - subjects: {customer_segmentation.segment: Atacado PJ}
          absolute: -0.007
          percent: -0.0558
```

A `dispersion` method returns the full pack in a single entry:

```yaml
  statistical_method:
    - id: s1
      method: dispersion
      value:
        - subjects: {customer_segmentation.segment: Varejo PF}
          mean: 0.137
          median: 0.134
          std: 0.031
          variance: 0.00096
          min: 0.081
          max: 0.213
          q1: 0.115
          q3: 0.156
          iqr: 0.041
```

Values that cannot be computed (`n < 3`, zero variance, fewer than 4 points, no repeated mode) come back as `null` with a reason — never `0`. A cell below the small-cell threshold (`k = 10`) is suppressed with an explicit reason, and companion cells are suppressed too so the cell cannot be recovered by subtraction.

The fixed fields are `analysis_plan_id`, `catalog_version`, `dataset_version`, `trace_id`, `statistical_method` and `operations`. The shape of each `value` varies according to the declared method; `operations` is absent when the plan declares none.

### Generative boundary

The LLM may:

- interpret the user's question;
- propose a structured CalculationPlan and AnalysisPlan;
- ask for clarification;
- explain verified results;
- synthesize retrieved approved knowledge.

The LLM never:

- defines authoritative business rules;
- invents official financial numbers;
- performs authoritative financial calculations;
- bypasses semantic compatibility rules.

The LLM receives deterministic `CalculationResult` and `AnalysisResult` values and explains them.

---

## User Interaction

`Conversation` is an entity formed by:

- `id`
- `messages`
- `participants`

`Message` is an entity formed by:

- `id`
- `sender_id`
- `text`
- `attachments`

`Participant` is an entity formed by:

- `id`
- `type`
- `user_id`

`Attachment` is a value object from Message and represents a file sent as part of a message.

The `Conversation` entity maintains the interaction history between users and agents. User Interaction is responsible only for capturing and presenting interactions. It does not perform calculations, financial analyses, or authentication.

---

## Auth

`User` is an entity formed by:

- `id`
- `name`
- `email`
- authentication credential reference
- `roles`
- `permissions`

`Role` is a value object from User and represents a business responsibility assigned to a User.

`Permission` is a value object from User and represents an authorized action.

Auth is responsible for authentication and authorization. Financial Calculation and Financial Analysis consume the authenticated/authorized actor context while remaining independent from authentication technology and rules.
'
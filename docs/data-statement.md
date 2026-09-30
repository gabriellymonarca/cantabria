# Data statement

## 1. O que é o dado

**100% sintético.** Nenhum registro vem de pessoa ou empresa real. O gerador
`utils/generate_cantabria_data.py` produz clientes, produtos, contratos e
rentabilidade do "Banco Cantábria" a partir de `random.Random(seed)` +
`Faker("pt_BR")` com `Faker.seed(seed)`; `--seed` (default 42) e `--clientes`
(default 10 000). Mesma seed → mesmo dataset
(`tests/test_generator_determinism.py`).

| Campo | Como é gerado | Por que não confundir com real |
|---|---|---|
| `id_cliente` | UUID v4 | chave técnica sem significado |
| `cpf_cnpj` | `fake.cpf()` / `fake.cnpj()` | número aleatório com dígito verificador válido, **não** vinculado a pessoa; existe para exercitar a redação de PII (`shared/redaction.py`) |
| `nm_cliente`, `ds_email`, `nr_telefone` | Faker pt_BR | cosméticos; nunca chegam ao LLM, ao resultado ou ao log |
| `vl_saldo`, `vl_margem` | distribuições por segmento/produto | únicos números "oficiais"; a taxa é **derivada** (Σ margem ÷ Σ saldo), nunca persistida |

Formato das bases: `data/base-ficticia.md`. Hierarquia de produtos e segmentos
lida **só** de `data/data-generation/produtos_segmentos.xlsm`.

## 2. Janela e versão

- Janela oficial: 2024-09-01 a 2026-08-31 (24 meses); **snapshot de referência 31/08/2026**.
- `dataset_version = <data>#sha256:<digest>` gravado em todo `AnalysisResult`
  (`src/shared/dataset_version.py`, `HashedSnapshotVersionAdapter`,
  fingerprint Python ↔ ClickHouse idêntico). Aparece no trace; o rodapé
  mostra a data de fechamento e o protocolo do turno.

## 3. Dados de mercado (reais, públicos)

CDI (SGS 4391), SELIC (4390) e IPCA (433) do BACEN — os únicos dados **reais**,
públicos e agregados. Ingestão `utils/ingest_market_data.py` com cache
versionado `data/market/bacen_sgs.csv` (seed e preflight funcionam offline);
tabela `mercado_indicadores`; métricas `macro` só no grão total
(`tests/test_market_ingest.py`; ADR 0013; `definitions.md` ratificado em
2026-09-30).

## 4. Fluxo

```
gerador (seed) → raw (tabelas de negócio + mercado_indicadores) → ClickHouse (DDL infra/clickhouse/init/00_schema.sql)
   → catálogo semântico v3 + adapter (nomes físicos ficam aqui)
   → motor (agregação no banco, componentes por célula)
   → AnalysisResult (dataset_version, catalog_version, prompt_version, trace_id) → resposta
```

O que **nunca sai dos adapters**: `ds_segm`, `vl_margem`, `id_cliente`…
(`tests/test_invariants.py`; RT-01).

## 5. Pendências

- `manifesto_qualidade` (issues de qualidade injetadas e logadas por chave) **não existe**; casos Q01/Q02 do `dev.yaml` marcam o caminho.
- Hash do dataset full nos relatórios de eval; hoje o oráculo usa o fixture mínimo `parity-tiny-v1`.

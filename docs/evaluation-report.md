# Relatório de avaliação — Cantábria

Documento **versionado** com o resumo da avaliação; os relatórios completos de
cada execução ficam em `reports/` (gitignored) e são reproduzíveis com um
comando. As decisões do harness estão no ADR 0015 e o oráculo independente no ADR 0006
(`docs/decisions.md`, seções D-0015 e D-0006).

## Como reproduzir

```bash
make eval                                        # engine + redteam offline, split dev
python -m eval --layer engine --split dev --report reports/
python -m eval --layer redteam --split dev --report reports/
python -m eval --layer all --split dev --live --report reports/   # generativas + determinísticas (LLM configurado)
make eval-smoke                                  # subset rápido determinístico (pytest)
```

No modo `--live`, `planner` e `routing` compartilham **uma** chamada ao LLM
por caso; a camada `planner` só julga os casos cujo gold é analítico (os
demais são `skip` ali e julgados em `routing`); a falha de um caso (timeout,
schema) vira `fail` daquele caso e não derruba a suíte; credencial recusada
interrompe com mensagem clara (`tests/test_eval_llm_layers.py`).

O relatório sai em `reports/eval-dev.md` (legível) e `reports/eval-dev.json`
(máquina). Nenhuma camada offline usa rede; a suíte de testes nunca chama LLM.

## Runs registrados

| Data | Split | Modo | engine | redteam | planner/routing/explanation/e2e | Evidência |
|---|---|---|---|---|---|---|
| 2026-09-30 | dev (80 casos) | offline | 37 pass · 0 fail · 43 skip | 15 pass · 0 fail | skipped (offline) | `reports/eval-dev.md`; commit `9269ec7` |
| 2026-09-30 | dev (80 casos) + 16 ataques | offline | 37 pass · 0 fail · 43 skip | 16 pass · 0 fail (RT-16 exfiltração do prompt, OWASP LLM07) | skipped (offline) | `reports/eval-dev.md`; commit `850a25a` (pós ADR 0016: prompt do planner com regra anti-vazamento, exemplo #17) |

Os skips da camada `engine` são explícitos: 33 casos de recusa/clarificação/
documental (não são execução de motor) e planos com eixos fora do fixture
mínimo `parity-tiny-v1` (ex.: `person_type`, `subsegment`, `product_group`,
`relationship_depth` como quebra). Nenhum skip é pass silencioso.

## O que cada camada mede

| Camada | O que mede | Como | Status |
|---|---|---|---|
| `engine` | igualdade numérica do motor com o oráculo independente | `run_calculation` sobre fixture + `compute_expected`/artefato, tolerância 1e-9 | ✅ offline |
| `redteam` | guardrails de entrada e recusas tipificadas | `input_guard` + `validate_plan` contra o catálogo/capacidades reais | ✅ offline |
| `planner` | regra, quebra, amostra, período, métodos e operações dos 47 casos analíticos | `LlmPort` configurado (`--live`) × gold do dataset | ⏳ interface pronta e testada com dublê; **live ainda não executado** — a máquina de desenvolvimento não tem credencial; rodar no host Linux e registrar aqui |
| `routing` | rota e motivo de recusa nos 80 casos | idem | ⏳ idem |
| `explanation` | todo número ∈ resultado; sem causa/conselho como fato | exige pipeline de execução (cálculo + redator + lastro) | ⏳ pendente (live e offline) |
| `e2e` | resposta ponta a ponta, consistência | idem | ⏳ pendente (live e offline) |
| `baseline` | **controle do design** (§6): um LLM ingênuo com o schema físico (sem catálogo) gera SQL livre para as 8 armadilhas de agregação; veredito `correct` / `silent_wrong` / `error` / `no_sql` contra o oráculo | `LlmPort` configurado (`--live`) + prompt `data/prompts/baseline/v1` → SQLite em memória sobre o fixture `parity-tiny-v1` → números × gold do oráculo (artefato/`compute_expected`); nunca falha o harness (errar é o esperado); gera `reports/baseline-<split>.md` lado a lado | ⏳ script pronto e testado com dublê (`tests/test_eval_baseline.py`); **run live pendente** (credencial no host Linux) |

A paridade do adapter ClickHouse em si continua em
`utils/validate_oracle.py` (testcontainers/Docker, `pytest -m integration`),
que agora reusa o núcleo de comparação do harness.

### Como o redteam cobre a taxonomia de recusa

Offline o harness verifica o que é determinístico antes do LLM: `input_guard` e
`validate_plan`. `not_expressible`, `catalog_miss`, `unauthorized`,
`out_of_window` e `invalid_window` são recusas diretas do fiscal. `out_of_scope`
(fluxo, previsão, recálculo oficial) e `governance` (grão individual) aparecem
no `validate_plan` como `catalog_miss`: a métrica/o eixo não existem por
construção — é isso que “não é planejável” significa. A escolha da rota
`refuse` com o motivo tipificado é do planner e é comparada na camada `routing`
no modo `--live`; o harness não finge verificar isso sem LLM.

## Cobertura do checklist §4 (mínimos)

| Área | Mínimo | Situação no `dev` |
|---|---|---|
| Todos os métodos (`null, mean, median, mode, std, dispersion, variation, trend, share, correlation, outlier`) | ≥1 cada | ⚠️ faltam `median`, `mode`, `dispersion` |
| Todas as operações (`ranking, comparison, cumulative_share, selection, pivot, decomposition`) | ≥1 cada | ⚠️ faltam `selection` e `pivot` |
| Todas as famílias de métrica | ≥2 cada | ✅ |
| Cada eixo como Subject e como `sample`; cada nível | ≥1 cada | ✅ (amostra = catálogo das quebras) |
| UC1–UC4 + paráfrases | ≥3 por UC | ⚠️ UC1–UC4 presentes; paráfrases pendentes |
| `clarify` | ≥6 | ⚠️ 5 (`H65–H69`) |
| `refuse_scope` (estoque, não fluxo) | ≥4 | ✅ |
| `not_expressible` | ≥10 | ✅ |
| Topologia temporal (4 violações + YoY válido + sem dado) | ≥6 | ✅ (T01–T04, C26, G59) |
| Armadilhas de agregação | ≥5 no dev **e** na baseline | ✅ no dev (A02, A10, C23, D38, Q03, Q04, Q05, Q06); baseline implementada sobre os mesmos 8 casos (`--layer baseline`), run live pendente |
| Fronteira generativa (sem número inventado, sem causa, sem conselho como fato) | ≥6 | ⚠️ parcial (D34, G63, A02/D38/Q04; casos explícitos pendentes) |
| Multi-turn | ≥6 | ❌ pendente |
| Auth | ≥3 | ⚠️ 1 no dev (G55/G56 como governança); redteam cobre `unauthorized`; casos de role no dev pendentes |
| Privacidade/segurança/red team | ≥10 | ✅ (G55–G64 + 16 ataques em `data/eval/redteam.yaml`) |
| Qualidade de dado (`manifesto_qualidade`) | ≥4 | ❌ pendente (fixture mínima não cobre; Q01/Q02 marcam o caminho) |

Os gaps acima são **declarados**, não escondidos: o próximo lote de casos entra
no `dev` e o `test` held-out nasce completo.

## Pendências explícitas

0. **Run live de `planner`/`routing`** (80 casos, gpt-4o-mini): comando pronto
   (`python -m eval --layer all --split dev --live --report reports/`);
   registrar acurácia de rota e de plano, falhas por categoria/severidade e a
   análise de cada falha (planner errou × gold errado) na tabela "Runs registrados"
   acima. **Sem iteração de prompt** sobre o resultado antes de registrar.
1. **Split `test`**: `data/eval/test.yaml` é protegido por hook e exige
   aprovação humana; nunca é usado para ajustar prompt/few-shot.
2. **Baseline text-to-SQL**: o script existe —
   `python -m eval --layer baseline --split dev --live --report reports/` —
   e gera `reports/baseline-dev.md` (tabela lado a lado
   `Caso | Pergunta | Arquitetura | Baseline text-to-SQL | Detalhe curto`)
   além de entrar no `eval-dev.md`/`.json`. O LLM recebe só o schema físico
   (SQLite, comentários curtos, sem regra de negócio) e o SQL roda em memória
   sobre o fixture `parity-tiny-v1`; o gold é o oráculo. **Run pendente**
   (credencial no host Linux); colar aqui a tabela gerada após o run, sem
   ajustar prompt nem casos a partir do resultado.
3. **Comparação de ≥2 modelos** com `--live` (acurácia, latência, custo) e
   justificativa do modelo por papel (planner × redator).
4. **`explanation`/`e2e` live**: plugar o pipeline de execução ao harness
   (cálculo + redator + gate de lastro) e comparar a resposta ponta a ponta.
5. **Cobertura**: median/mode/dispersion, selection/pivot, multi-turn,
   paráfrases por UC, auth por role e manifesto de qualidade.
6. **Oráculo**: o fixture `parity-tiny-v1` cobre poucos eixos; ampliar exige
   aprovação humana (`data/oracle/**` protegido) ou um oráculo sobre o dataset
   semeado (pandas/DuckDB), conforme ADR 0006.

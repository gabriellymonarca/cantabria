# Planos — CalculationPlan e AnalysisPlan

Os planos são as duas entidades que o LLM propõe a partir da pergunta. Cada uma tem um papel distinto:

- **CalculationPlan** — *o que calcular*: quais elementos guiam a query determinística no ClickHouse.
- **AnalysisPlan** — *como associar os números*: quais métodos estatísticos rodar, de onde vêm os valores e o que fazer com eles.

O roteiro que transforma a pergunta nesses planos está na seção 4.

---

## 1. Estrutura geral

Um `CalculationPlan` tem **uma métrica**. Logo o `id` do plano **é** a referência da série: não existe um id separado para a métrica. O `AnalysisPlan` referencia os planos pelo `calculation_plan_id`.

```text
pergunta
  │
  ├─ CalculationPlan (1..N)  ──gera──▶  CalculationResult (1..N)
  │        ▲
  │        │ calculation_plan_ids
  └─ AnalysisPlan (1)        ──gera──▶  AnalysisResult (1)
```

```yaml
# CalculationPlan — 1 por métrica
CalculationPlan:
    calculation_plan_id: calc_prof_prod_high
    metric:
        id: m_prof
        rule_id: profitability
        subjects:                       # a quebra (vira linha)
            - type: product
              level: product
        sample:                         # quem entra (não vira linha) — opcional
            - type: customer_principality
              level: principality_depth
              value_id: high
    period:
        start: 2026-05-31
        end: 2026-08-31
        type: series
        grain: month
```

```yaml
# AnalysisPlan — 1 por pergunta
AnalysisPlan:
    analysis_plan_id: plan1
    statistical_method:
        - id: s1
          method: mean
          calculation_plan_ids: [calc_prof_prod_high]
    operations:
        - id: o1
          type: ranking
          refs: [s1]
          params:
              order: desc
              top_n: 5
              axis: entity
    presentation:            # opcional: a forma, nunca os números
        type: ranking_bar
        axis: entity
        title: Produtos mais rentáveis
```

Regras de referência:

- `calculation_plan_id` é único no **pacote inteiro** (todos os planos juntos).
- `statistical_method[].id` e `operations[].id` são únicos **dentro do AnalysisPlan**.
- Dois planos podem compartilhar a mesma janela (ex.: duas métricas no mesmo período). O que não se repete é `calculation_plan_id`.
- **Só a rota `analytical` gera planos** (seção 4, passo 6). `documental`, `clarify`, `refuse` e `default` não têm CalculationPlan nem AnalysisPlan.

---

## 2. AnalysisPlan — como associar os números

O AnalysisPlan tem **duas partes** (mais uma apresentação opcional):

- **`statistical_method`** — calcula o número (`mean`, `std`, `variation`, `correlation`, ...).
- **`operations`** — o que fazer com o número pronto (`ranking`, comparação). É opcional.
- **`presentation`** — como mostrar o resultado. É opcional e não contém número.

### `statistical_method[]`

| campo | obrigatório | papel | valores |
|---|---|---|---|
| `id` | sim | nome local, para a operação referenciar | string única no plano |
| `method` | sim | a função que calcula | ver catálogo abaixo; `null` = sem cálculo |
| `calculation_plan_ids` | condicional | planos que entregam os valores | lista de `calculation_plan_id` |
| `statistic_refs` | condicional | resultado de um método declarado antes | lista de `id` de método |

Cada método diz de onde vêm seus valores — **um dos dois**, nunca os dois:

- `calculation_plan_ids` — valores vindos direto do cálculo.
- `statistic_refs` — resultado de um método já declarado acima.

Um método só pode referenciar um método **declarado antes** dele (sem ciclo).

**Método não tem `params`.** O nome do método diz *qual quantidade* ele produz, e cada um tem uma unidade de saída documentada. Se duas variantes dão números ou unidades diferentes, são **métodos diferentes**.

| `method` | o que produz | unidade de saída |
|---|---|---|
| `null` | os valores vindos do cálculo, sem nenhum tratamento | a do cálculo |
| `mean` | média da série por entidade (proibida em `profitability`: média de taxas não é a taxa da janela) | a do cálculo |
| `median` | mediana da série por entidade | a do cálculo |
| `mode` | valor mais frequente da série (`null` sem repetição ou com empate) | a do cálculo |
| `std` | desvio-padrão por entidade (volatilidade) | a do cálculo |
| `dispersion` | pacote: `mean, median, std, variance, min, max, q1, q3, iqr` (proibido em `profitability`) | a do cálculo |
| `variation` | diferença entre **dois** cálculos colapsados: a absoluta (numa taxa, já é p.p.) e a percentual | a do cálculo + `percent` |
| `trend` | inclinação por entidade no eixo ordenado (série temporal ou nível ordinal) | a do cálculo por período/nível |
| `share` | parte ÷ todo (métrica somável, resultado colapsado) | `ratio` (0..1) |
| `correlation` | Pearson entre **dois** resultados, mesmas entidades, n >= 3 | coeficiente (-1 a 1) |
| `outlier` | pontos atípicos do resultado (IQR 1.5, mínimo 4 pontos) | a do cálculo |

A "unidade do cálculo" vem da métrica: `profitability` → `decimal_rate`, `outstanding_balance` → `currency`, `contract_count`/`customer_count` → `count`.

**Como obter "a taxa da janela".** Não existe média de taxas na oferta. Para um número por entidade na janela, use `grain: total` com `method: null`; o motor re-deriva `Σnumerador ÷ Σdenominador`. Os métodos de série respondem outra pergunta: como a taxa se comportou (desvio, mediana, tendência, atípicos).

### `operations[]`

Não calculam número: só olham o resultado (de um método ou os valores brutos) e o organizam. Aqui **existe `params`**, porque os valores são abertos.

| campo | obrigatório | papel | valores |
|---|---|---|---|
| `id` | sim | nome local | string única no plano |
| `type` | sim | o que fazer com o resultado | ver catálogo abaixo |
| `refs` | sim | de onde vêm os valores | `id` de `statistical_method` |
| `params` | não | **como** a operação roda | depende do `type` |

| `type` | o que faz | `params` |
|---|---|---|
| `ranking` | ordena o resultado | `order`: `asc`/`desc`, `top_n`: inteiro opcional, `axis`: `entity`/`period` (**sempre obrigatório**) |
| `comparison` | mostra valores **lado a lado** (não calcula) | `across`: `entity` / `result` (result exige 2 refs) |
| `cumulative_share` | participação acumulada sobre o resultado ordenado (Pareto) | `cutoff`: float em (0, 1] |
| `selection` | pega linhas por condição relativa ao resultado | `rule`: `above_mean` / `below_mean` / `top_percent`, `value`: número |
| `pivot` | cruza dois eixos numa tabela | `rows`, `columns` |
| `decomposition` | contribuição de **efeito-taxa** de cada grupo (`share_base × Δtaxa`) | refs: `[variation, share]`; a soma fecha com o efeito-total |

`decomposition` é a única operação que lê **dois métodos**. O resíduo de mix exigiria a share das duas janelas — extensão futura.

`comparison` não calcula: só põe valores lado a lado. Quem mede direção/inclinação é o método `trend`. "Melhor/pior" é `ranking` com `top_n: 1`.

### `presentation` — como mostrar o resultado (opcional)

A apresentação escolhe a **forma** da resposta; os números continuam vindo só do resultado verificado. Catálogo fechado:

| campo | obrigatório | papel | valores |
|---|---|---|---|
| `type` | sim | a forma | `bar`, `line`, `ranking_bar`, `table` |
| `axis` | sim | o que vai na horizontal | `entity` (categorias) ou `period` (tempo) |
| `title` | não | frase curta ao usuário, em pt-BR, sem ids internos | string |

- `line` exige `axis: period` (série temporal); `ranking_bar` acompanha o `axis` do `ranking`.
- A apresentação é proposta pelo planner e conferida em `validate_plan`: `line` sem série, `ranking_bar` sem ranking ou `bar` sem entidade **degradam para `table`** — a forma nunca derruba os números. Tipo ou eixo fora do catálogo também degradam, não recusam.
- Sem `presentation`, a rota analítica devolve o texto, o rodapé de procedência legível e a nota recolhível "Como calculei" (`MethodNote`, ADR 0016); com ela, os blocos `Dataframe`/`Plotly` são montados deterministicamente do `AnalysisResult` (linhas `undefined` não são plotadas).

### Sem estatística — só a busca na base

`method: null` deixa os valores passarem direto. Aí a operação rankeia/compara, ou não há operação e os valores já são a resposta.

```yaml
statistical_method:
    - id: s1
      method: null
      calculation_plan_ids: [calc_prof_seg]
operations:
    - id: o1
      type: ranking
      refs: [s1]
      params:
          order: desc
          top_n: 5
```

### `variation` — diferença e percentual de uma vez

A variação devolve **os dois números**: a diferença absoluta (numa taxa, já em p.p.) e a percentual.

```yaml
- id: s1
  method: variation
  calculation_plan_ids: [calc_prof_2025_08, calc_prof_2026_08]
```

Para `0.128 → 0.121`: diferença `-0.007` (`-0,7 p.p.`) e percentual `-5,47%`.

Não há escolha a fazer na hora do plano. Quem decide qual mostrar é o texto da resposta — então "cresceu mais?" não fica ambígua.

### `params` de operação — exemplos

**`ranking`** — ordenar e cortar:

```yaml
- id: o1
  type: ranking
  refs: [s1]
  params:
      order: desc
      top_n: 5
      axis: entity
```

### `axis` — precisa ou não?

`axis` diz se a ordenação é por **entidade** (segmento, produto) ou por **período** (mês, trimestre).

- Se o resultado só tiver uma das duas dimensões, dá pra inferir.
- Se tiver as duas (valores por segmento **e** por mês), fica ambíguo: "qual segmento é o mais rentável?" e "qual mês foi o melhor?" são a mesma função em eixos diferentes.

Então só é obrigatório quando o resultado tem mais de um eixo. Para simplificar, pode ser sempre declarado.

### Como os valores são associados

Cada valor que volta do cálculo vem identificado pelo seu `subjects` (e pelo `period`, quando se comparam janelas):

```yaml
- subjects: {customer_segmentation.segment: Varejo PF}
  period: 2025-08-31
  value: 0.128
```

Para casar valores de **mais de um plano**, o processo usa esses rótulos. Por isso, todos os `calculation_plan_ids` de um mesmo método precisam ter os **mesmos `subjects`**:

```text
calc_prof_2025_08:  Varejo PF = 0.128   Corporate = 0.150
calc_prof_2026_08:  Varejo PF = 0.121   Corporate = 0.140   → casam
                              ↓
variation:          Varejo PF = -0.007  Corporate = -0.010
```

Se um plano for por segmento e o outro por produto, nenhum rótulo casa:

```text
calc_prof_seg:   Varejo PF = 0.128
calc_prof_prod:  Cartão   = 0.20      ← nenhum rótulo em comum
```

Essa checagem é feita **antes de executar**, olhando só os planos. Se os eixos não baterem, o plano é recusado.

A mesma regra vale quando um método combina **dois resultados** (`correlation`) ou quando uma `comparison across: result` põe dois lado a lado: os dois lados precisam estar sobre os **mesmos sujeitos**. Correlacionar rentabilidade por segmento com contratos por produto é ruído com coeficiente.

---

## 3. CalculationPlan — quais elementos para o cálculo

| campo | obrigatório | papel | valores |
|---|---|---|---|
| `calculation_plan_id` | sim | identidade da série | string única no pacote |
| `metric` | sim | a métrica calculada | objeto (abaixo) |
| `period` | sim | a janela de tempo | objeto (abaixo) |

### `metric`

A métrica diz **o que medir** e **sobre quem medir**:

- `rule_id` — a regra de cálculo: **como** a métrica é calculada (a fórmula, e eventuais regras de elegibilidade que a família já embute).
- `subjects` — a **quebra**: sobre quem a métrica é medida. Cada sujeito vira uma linha do resultado.
- `sample` — o **campo amostral**: quem entra na conta. Não vira linha.

| campo | obrigatório | papel | valores |
|---|---|---|---|
| `id` | não | rótulo legível da métrica | string (ex.: `m_prof`) |
| `rule_id` | sim | a regra de cálculo (catálogo fechado) | `profitability`, `outstanding_balance`, `contract_count`, `customer_count` |
| `subjects` | sim | a quebra (GROUP BY) | lista não-vazia; sem quebra = `total.total` |
| `sample` | não | quem entra na conta (WHERE) | lista de condições (abaixo) |

`rule_id` é **só sobre a métrica calculada** pelo motor. Métricas de referência (principalidade, vinculação) não entram aqui — no máximo como condição de `sample`. Se a pergunta quiser uma delas **como número** (ex.: "principalidade média por segmento"), é gap de escopo: o negócio calcula, o motor não.

Exemplo: "rentabilidade por produto de clientes de alta principalidade" → `rule_id: profitability`; a quebra é `product`; o campo amostral é `customer_principality.principality_depth = high`.

### `metric.subjects[]`

Os sujeitos são as entidades que a métrica mede — segmentos, produtos, níveis. Cada subject vira **exatamente uma coluna** no `GROUP BY`. Dois subjects = cruzamento (uma célula por par), não duas marginais.

| campo | obrigatório | papel | valores |
|---|---|---|---|
| `type` | sim | dimensão semântica | `customer_segmentation`, `customer_relationship`, `customer_principality`, `product`, `total` |
| `level` | sim | grão dentro da dimensão | ver tabela abaixo |

| `type` | `level` permitidos |
|---|---|
| `customer_segmentation` | `person_type`, `segment_group`, `segment`, `subsegment_group`, `subsegment` |
| `customer_relationship` | `relationship_depth` |
| `customer_principality` | `principality_depth` |
| `product` | `product_group`, `product`, `subproduct` |
| `total` | `total` |

### `metric.sample`

O campo amostral encolhe quem entra na conta e **não** aparece como linha no resultado. É o `WHERE`, não o `GROUP BY`.

| campo | obrigatório | papel | valores |
|---|---|---|---|
| `type` | sim | dimensão do recorte | mesmo catálogo dos subjects |
| `level` | sim | grão dentro da dimensão | mesmo catálogo dos subjects |
| `value_id` | sim | valor governado | pertence ao conjunto daquela versão do catálogo (ex.: `high`/`medium`/`low` para profundidades) |

Regras: uma igualdade por condição, sem operador, sem multivalor, sem negação. A lista permite mais de uma condição. A condição não repete o `(type, level)` da quebra que ela restringe (agrupar por produto e recortar um único produto daria uma linha só).

### `period`

A janela e o seu colapso:

| campo | obrigatório | papel | valores |
|---|---|---|---|
| `start`, `end` | sim | intervalo da janela | datas ISO |
| `type` | sim | forma do resultado | `series` (um valor por bucket) ou `snapshot` (start == end) |
| `grain` | sim | tamanho do bucket | `month`, `quarter`, `year` ou `total` |

`grain: total` colapsa a janela inteira em **uma linha por grupo**, recalculada do fato: ratio → `Σnumerador ÷ Σdenominador`; stock → leitura do fim do período; count → contagem na data final. É o grão de "um número por entidade no período".

---

## 4. Roteiro de leitura da pergunta

Como o LLM sai da pergunta e chega nos planos:

1. **Achar o par métrica + sujeito** — *o que medir* e *sobre quem*. Vira `metric.rule_id` + `subjects`. Pode haver mais de um par (duas métricas = dois planos).
2. **Achar o campo amostral** — *em que universo*:
   - **quando** → `period` (janela + grão). Mais de uma janela = mais de um plano.
   - **quem entra** → `sample`.
3. **Traduzir o campo amostral para termos governados** — o "quem entra" vira condição de `sample` (ex.: principalidade = `high`).
4. **Achar o método** — quando a pergunta pede um tratamento: "volátil" → `std`; "dispersão" → `dispersion`; "subiu/caiu" → `trend`; "variação/YoY" → `variation`; "participação" → `share`.
5. **Achar a operação** — quando pede arranjo: "mais/menos", "top N" → `ranking`; "lado a lado" → `comparison`; "80% / Pareto" → `cumulative_share`.
6. **Fechar as faltas** — decide a rota:
   - `analytical` — tem o essencial → **gera os planos**.
   - `clarify` — falta algo recuperável ("de quando?").
   - `refuse` — proibido por governança ou fora de escopo.
   - `documental` — não é cálculo (RAG puro).
   - `default` — só um ponto de partida, sempre ecoado ao usuário.

Exemplos:

**"Qual produto é mais rentável entre clientes de alta principalidade?"**
1. rentabilidade + produto
2. campo amostral: clientes de alta principalidade; período **ausente** → default de série, ecoado em `assumptions`
3. `sample: principalidade = high`
4. "mais rentável" pede **um número por entidade na janela** → `grain: total` + `method: null`
5. `ranking(axis: entity, top_n: 1)`
6. `analytical`

**"Qual segmento foi o mais volátil no trimestre?"**
1. rentabilidade + segmento
2. campo amostral: trimestre → `period`
3. não tem
4. "volátil" → `std`
5. `ranking(axis: entity)`
6. `analytical`

**"Como estão os clientes?"**
1. sem par métrica + sujeito
6. `default` — propor uma análise e perguntar se quer seguir nessa linha.

---

## 5. Pendências

1. **Vocabulário do `sample`.** Hoje a condição usa `type`/`level` (dimensão). Se principalidade e vinculação são **métricas de referência** (não levels), a condição precisa poder referenciar uma métrica. Decisão em aberto.
2. **Nomes.** `subjects[].type` guarda a dimensão (`customer_segmentation`, `product`), mas na fala de negócio isso é o **segmento** (`cliente`, `produto`). Renomear para `segment` deixaria o vocabulário alinhado.

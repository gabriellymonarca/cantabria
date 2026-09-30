# Semantic Catalog — como o catálogo é construído

O catálogo semântico é a **lista oficial e fechada** de tudo que um plano pode usar: métricas, eixos, valores, janelas, defaults e compatibilidades. Ele é a **única autoridade** sobre o que existe.

> **O catálogo determina. O RAG explica.**

Um termo que não está no catálogo não vira "o mais parecido": vira recusa (`catalog_miss`) ou pedido de esclarecimento.

---

## 1. O que é (e o que não é)

| É | Não é |
|---|---|
| allowlist de métricas, eixos, valores e janelas | documento oficial (isso é o RAG) |
| regras de compatibilidade entre análise e métrica | dado (isso é o ClickHouse) |
| o contrato que o prompt e a validação compartilham | fórmula de método (isso é código, na family) |
| dado versionado de governança | plano ou resultado |

Duas coisas consomem o mesmo catálogo:

- **`create_plan`** — renderiza o catálogo como texto e o LLM escolhe **entre** as opções.
- **`validate_plan`** — checa o plano **contra** o catálogo, de forma determinística.

Se o prompt e a validação lessem fontes diferentes, o que o LLM pode propor e o que o sistema aceita divergiriam. Uma fonte só elimina essa deriva.

---

## 2. Onde mora e como é versionado

- Arquivo: `data/catalogs/semantic_catalog_<versão>.yaml` — **fora de `src/`**, porque dado versionado não mora no núcleo.
- O catálogo é **imutável**. Mudar o catálogo é publicar uma **nova versão** (v2, v3…), nunca editar a viva.
- Cada registro de plano/resultado é selado com a **versão do catálogo** usada, para auditoria e reprodutibilidade.
- A **v2** é a versão de implementação do módulo de análise: traz `shape` nas métricas, `kind` nos eixos, a matriz `compatibility` completa e a cobertura de níveis/valores dos casos. A v1 permanece legível, mas não é editada.

### Cabeçalho

| campo | papel |
|---|---|
| `catalog_version` | versão (`v1`, `v2`…) |
| `locale` | superfície localizada (sinônimos/labels); os ids são neutros |
| `valid_from` / `valid_until` | vigência da versão |
| `source` | quem aprovou (área de negócio) |
| `reference_date` | as-of do negócio; **fallback** quando o dado oficial não está acessível |
| `window` | recorte temporal disponível; fora dele é `out_of_window` |

A `reference_date` em runtime vem do **dado oficial** (`max(mes_ref)`); o valor no YAML é só o fallback. As janelas nomeadas são derivadas dela por código (`domain/windows.py`), nunca escritas à mão.

---

## 3. As partes do arquivo

### 3.1 Métricas (`metrics`)

O que pode ser **medido**. Cada `rule_id` fecha o par com uma family implementada em `financial_calculation`.

| campo | papel |
|---|---|
| `rule_id` | id canônico da métrica |
| `shape` | forma: `ratio` (não somável) / `stock` / `count` |
| `unit` | unidade de saída: `decimal_rate` / `currency` / `count` |
| `synonyms` | como o negócio chama a métrica |

### 3.2 Eixos (`axes`)

O que pode ser **quebra** (vira linha) ou **recorte** (vira `WHERE`). O catálogo do recorte **é** o catálogo dos eixos.

| campo | papel |
|---|---|
| `type` | dimensão (`customer_segmentation`, `product`…) |
| `level` | grão dentro da dimensão (`segment`, `product`…) |
| `kind` | `nominal` (sem ordem) ou `ordinal` (tem ordem — ex.: profundidade) |
| `synonyms` | como o negócio chama o eixo |
| `parent` | nível imediatamente acima, para drill-down (opcional) |

O catálogo declara **significado governado**, não a coluna física. O mapeamento `(type, level, value_id)` → coluna/faixa/tabela é do **adapter de cálculo** (§4).

### 3.3 Valores (`values`)

Os `value_id` que um recorte pode usar. Só existe para eixos **enumeráveis**.

| campo | papel |
|---|---|
| `type` / `level` | a que eixo o valor pertence |
| `value_id` | id canônico (`high`, `varejo_pf`…) |
| `labels` | como o negócio escreve o valor |

O valor físico correspondente (label gravado, faixa de score) é resolvido pelo **adapter de cálculo**, não pelo catálogo.

Um `value_id` pertence a **uma** versão do catálogo. Fora dela, `not_expressible` ou `catalog_miss`.

### 3.4 Janelas (`windows`)

As janelas nomeadas. O catálogo declara a **definição** (âncora/offset); o código deriva as datas concretas de `reference_date`.

| campo | papel |
|---|---|
| `id` | id canônico (`last_12_months`…) |
| `kind` | `snapshot_at_reference` / `trailing_months` / `year_to_date` / `previous_year` |
| `months` | quantos meses, quando `trailing_months` |
| `type` | `series` ou `snapshot` |
| `grain` | `month` / `quarter` / `year` / `total` |
| `labels` | como o negócio nomeia a janela |

A janela define o **intervalo** e um grão de referência; o plano pode colapsar a janela com `grain: total` (uma linha por grupo, re-derivada pelo motor). É o grão usado quando a pergunta pede "um número por entidade no período".

### 3.5 Defaults (`period_defaults`)

Aplicados quando a pergunta **não traz período**, e sempre ecoados em `assumptions`:

```yaml
period_defaults:
  series: last_12_months
  snapshot: reference_snapshot
```

Pergunta que exige série (volatilidade, tendência, variação) usa o default de série; pergunta pontual usa o de snapshot. Default silencioso não existe.

### 3.6 Compatibilidade (`compatibility`)

A matriz que liga a análise à forma da métrica. É o que `validate_plan` consulta para dizer se o método combina com o que foi pedido.

| campo | papel |
|---|---|
| `method` / `operation` | método (estágio 1) ou operação (estágio 2) do `AnalysisPlan` |
| `requires_metric_shape` | formas de métrica aceitas (`share` exige somável; `mean`/`dispersion`/`selection.above_mean`/`below_mean` são proibidos em `ratio`) |
| `requires` | exigências estruturais: `series` (>1 período), `collapsed_result` (snapshot ou `grain: total`), `ordinal_axis`, `min_points` |
| `reads` | `calculation_plan_ids` ou `statistic_refs` |
| `count` | quantas fontes exige (`variation` = 2; `correlation` = 2; `decomposition` = 2) |
| `same` | o que as fontes precisam ter em comum (`rule_id`, `subjects`, `sample`) |
| `windows` | exigência temporal (`disjoint_equal_duration`, …) |

Regras que a matriz precisa cobrir: `variation`/`share`/`correlation`/`decomposition` exigem resultado colapsado; `correlation` é Pearson com `n ≥ 3` e variância não nula; `trend` ordinal exige `grain: total` e ≥ 3 níveis; `outlier` exige ≥ 4 pontos.

### 3.7 Confusões (`not_confuse`)

Pares de termos parecidos que **não** são sinônimos (ex.: principalidade × vinculação). Servem de gatilho para esclarecimento e para a validação não tratar um como o outro.

Quando a pergunta usa um termo que pertence ao par sem desambiguar, a rota é `clarify` — o prompt recebe o par e a pergunta de volta pede a distinção.

---

## 4. Semântico × físico

O plano carrega apenas **significado governado**. O mapeamento para o banco brasileiro é infraestrutura e mora no **adapter de cálculo** (§5).

```text
customer_principality.principality_depth = high
        ↓ adapter de cálculo
fato_cliente.principalidade_score >= 70        (faixa)

customer_segmentation.segment = varejo_pf
        ↓ adapter de cálculo
fato_cliente.ds_segm = "Varejo PF"             (coluna)
```

Trocar de região é publicar outro catálogo (outro `locale`) **e** apontar o adapter para o mapeamento físico correspondente. O **plano não muda** — ele nunca contém `ds_segm` nem `principalidade_score`.

---

## 5. Quem lê o catálogo

| consumidor | o que faz com ele |
|---|---|
| `create_plan` | renderiza sinônimos, labels, janelas, defaults e compatibilidade no prompt |
| `validate_plan` | verifica pertencimento: métrica existe? eixo existe? `value_id` pertence ao eixo? data está na janela? método é compatível? |
| adapter de cálculo | traduz `(type, level, value_id)` para coluna, tabela e faixa — **é dono do mapeamento físico** |

---

## 6. Regras duras

1. **Id canônico, label localizado.** `profitability` é id; "rentabilidade" é sinônimo. O `locale` nunca muda um id.
2. **Um termo → um objeto.** Se um termo aponta para dois objetos, não é sinônimo: é ambiguidade (vira `not_confuse` + clarify).
3. **Fechado.** O que não está no catálogo não entra no plano. Não existe "vizinho mais parecido".
4. **Fórmula não mora aqui.** O catálogo declara que a métrica existe; a family implementa a fórmula. Métrica só entra quando a family existe.
5. **Versão, não edição.** Mudança = nova versão com `source`, `valid_from` e evidência.
6. **Nenhum parâmetro de plano nasce de documento.** O RAG explica; não define eixo, valor nem data.
7. **Comportamento muda só em nova versão.** Em execução, o catálogo é determinístico.

---

## 7. Esqueleto do arquivo

```yaml
catalog_version: v2
locale: pt-BR
valid_from: "2024-09-01"
valid_until: null
source: "area-negocios-financas (ficticio)"

reference_date: "2026-08-31"       # fallback; runtime vem do dado
window:
  start: "2024-09-01"
  end: "2026-08-31"

metrics:
  - rule_id: profitability
    shape: ratio
    unit: decimal_rate
    synonyms: ["rentabilidade"]
  - rule_id: outstanding_balance
    shape: stock
    unit: currency
    synonyms: ["carteira", "saldo", "estoque"]
  - rule_id: contract_count
    shape: count
    unit: count
    synonyms: ["contratos"]
  - rule_id: customer_count
    shape: count
    unit: count
    synonyms: ["clientes", "base de clientes"]

axes:
  - {type: customer_segmentation, level: person_type, kind: nominal, synonyms: ["tipo de pessoa"]}
  - {type: customer_segmentation, level: segment, kind: nominal, synonyms: ["segmento"]}
  - {type: customer_segmentation, level: subsegment, kind: nominal, synonyms: ["subsegmento"]}
  - {type: customer_relationship, level: relationship_depth, kind: ordinal, synonyms: ["vinculação"]}
  - {type: customer_principality, level: principality_depth, kind: ordinal, synonyms: ["principalidade"]}
  - {type: product, level: product_group, kind: nominal, synonyms: ["grupo de produto"]}
  - {type: product, level: product, kind: nominal, synonyms: ["produto"]}
  - {type: product, level: subproduct, kind: nominal, synonyms: ["subproduto"]}
  - {type: total, level: total, kind: nominal, synonyms: []}

values:                              # eixos enumeráveis; labels + value_id
  - {type: customer_segmentation, level: segment, value_id: varejo_pf,
     labels: ["Varejo PF", "varejo pf"]}
  - {type: customer_principality, level: principality_depth, value_id: high,
     labels: ["alta principalidade", "alta"]}

windows:
  - {id: reference_snapshot, kind: snapshot_at_reference, type: snapshot, grain: month,
     labels: ["hoje", "posição atual"]}
  - {id: last_12_months, kind: trailing_months, months: 12, type: series, grain: month,
     labels: ["últimos 12 meses", "último ano"]}

period_defaults:
  series: last_12_months
  snapshot: reference_snapshot

compatibility:
  methods:
    - {method: share, requires_metric_shape: [stock, count], requires: [collapsed_result]}
    - {method: mean, forbids_metric_shape: [ratio], requires: [series]}
    - {method: dispersion, forbids_metric_shape: [ratio], requires: [series]}
    - {method: median, requires: [series]}
    - {method: std, requires: [series]}
    - {method: variation, reads: calculation_plan_ids, count: 2,
       requires: [collapsed_result], same: [rule_id, subjects, sample],
       windows: disjoint_equal_duration}
    - {method: correlation, reads: statistic_refs, count: 2,
       requires: [collapsed_result], same: [subjects], min_points: 3}
    - {method: trend, requires: [series_or_ordinal_total], min_levels: 3}
    - {method: outlier, requires: [series], min_points: 4}
  operations:
    - {operation: ranking, requires_params: [axis]}
    - {operation: comparison, params_when: {across: result}, count: 2}
    - {operation: cumulative_share, requires_source: [share]}
    - {operation: selection, forbids_metric_shape: [ratio],
       when_rule: [above_mean, below_mean]}
    - {operation: decomposition, reads: statistic_refs, count: 2,
       requires_source: [variation, share]}

not_confuse:
  - term_a: customer_principality.principality_depth
    term_b: customer_relationship.relationship_depth
```

---

## 8. Como o catálogo cresce

O catálogo **não** cresce em tempo de execução. Um termo que não resolve vira **telemetria** (`catalog_miss`), e a mudança segue um processo em lote:

```text
telemetria + documentos  →  propostas  →  aprovação humana  →  nova versão  →  testes (data/eval/dev.yaml)
```

Regra: **o documento pode propor; o catálogo decide; a pessoa aprova.** Nada disso roda no caminho da pergunta.

---

## 9. O tipo de domínio e o port

O catálogo não deve ser lido como texto solto: vira um objeto tipado no domínio, atrás de um port.

```python
@dataclass(frozen=True)
class SemanticCatalog:
    catalog_version: str
    locale: str
    reference_date: date
    window: ResolvedWindow
    metrics: tuple[MetricEntry, ...]
    axes: tuple[AxisEntry, ...]
    values: tuple[ValueEntry, ...]
    windows: tuple[WindowEntry, ...]
    period_defaults: Mapping[str, str]
    compatibility: ...
    not_confuse: ...
```

O port devolve a **versão ativa** e permite **fixar uma versão** para replay e auditoria; o adapter concreto lê o YAML (e, na expansão, pode ler Postgres/Qdrant sem tocar no núcleo).

```text
domain:  SemanticCatalog (regras de pertencimento e compatibilidade)
ports:   SemanticCatalogPort.load_active() -> SemanticCatalog
         SemanticCatalogPort.load(catalog_version) -> SemanticCatalog
adapter: YamlSemanticCatalogAdapter (lê data/catalogs/*.yaml)
```

Assim, `create_plan` e `validate_plan` consomem **o mesmo** objeto. O adapter de prompt continua montando o texto; a validação usa os mesmos dados de forma determinística. Internamente, esse objeto é um **grafo** (§10): resolver e validar viram travessias, não buscas em listas.

---

## 10. O catálogo como grafo

O catálogo **já é um grafo**: as partes da §3 não são listas soltas, são nós ligados por arestas. Tornar isso explícito — em vez de deixar as relações implícitas no YAML — é o que dá validação multi-hop, explicação do caminho e auditoria.

### 10.1 Nós e arestas

| Nó | O que é |
|---|---|
| `Metric` | uma métrica (`profitability`) |
| `Axis` | uma dimensão (`customer_segmentation`) |
| `Level` | um grão dentro do eixo (`segment`) |
| `Value` | um `value_id` (`varejo_pf`) |
| `Window` | uma janela nomeada (`last_12_months`) |
| `Physical` | coluna, faixa ou tabela de destino — resolvida pelo **adapter de cálculo**, fora do arquivo do catálogo |

| Aresta | Liga | Significa |
|---|---|---|
| `has_level` | Axis → Level | o eixo tem esse grão |
| `has_value` | Level → Value | o grão aceita esse valor |
| `synonym_of` | termo → nó | "carteira" aponta para `outstanding_balance` |
| `maps_to` | Level/Value → Physical | o mapeamento físico (adapter, não catálogo) |
| `compatible_with` | Metric → Method | a matriz de compatibilidade |
| `drill_down` | Level → Level | hierarquia (segment → subsegment) |
| `not_confuse` | nó ↔ nó | termos parecidos que **não** são o mesmo |

### 10.2 O que o grafo destrava

- **Validação multi-hop.** "Este plano é válido?" vira um **caminho**: `profitability` existe → `customer_segmentation` tem o nível `segment` → o `value_id` pertence ao nível → a data está na janela. Qualquer aresta faltando = recusa.
- **Explicabilidade.** O caminho percorrido **é** a justificativa do plano, mostrável ao usuário e registrável para auditoria.
- **Prompt como subgrafo.** Em vez de despejar o catálogo inteiro no prompt, renderiza-se só o subgrafo relevante à pergunta.
- **Auditoria.** O resultado fica rastreável até o caminho (e a versão do catálogo) que o autorizou.

### 10.3 Diagrama

```text
                    synonym_of
   "rentabilidade" ─────────────▶ (Metric: profitability)
                                        │ compatible_with
                                        ▼
                                     (Method: std)

( Axis: customer_segmentation )
        │ has_level
        ▼
   ( Level: segment )
        │ has_value            maps_to (adapter)
        ▼                       ─────▶ ( Physical: ds_segm )
   ( Value: varejo_pf )
        │ drill_down
        ▼
   ( Level: subsegment )
```

### 10.4 Três estágios

| estágio | o que é | custo |
|---|---|---|
| **1 — grafo em memória (agora)** | o YAML é a fonte; o adapter compila para um grafo tipado no domínio. Sem banco de grafo. | baixo |
| **2 — constraints (opcional)** | regras de compatibilidade como constraints formais (estilo SHACL), validadas em CI. | médio |
| **3 — GraphRAG (grafo separado)** | grafo das **entidades dos documentos**, híbrido com o Qdrant, para explicação multi-hop. | alto |

O estágio 1 é o que se implementa agora. O estágio 3 é **outro** grafo, não o catálogo.

### 10.5 Por que em memória (e quando migrar)

O grafo do catálogo é **pequeno, imutável e versionado**: carrega no start e é lido no caminho quente da validação. Em memória não é limitação — é a escolha certa para esse formato.

- **Nenhum banco do stack é grafo:** Qdrant é vetorial, ClickHouse é colunar, Mongo é documento — nenhum faz travessia de arestas nativa.
- **Um banco novo custa caro** para o benefício: driver, operação, backup, auth e um round-trip de rede em cada validação.
- **É o padrão de mercado:** o dbt MetricFlow compila o YAML em um grafo semântico **em tempo de query**, não mantém um grafo vivo.

E, o mais importante: o grafo fica atrás do `SemanticCatalogPort`. Trocar o adapter (YAML em memória → Neo4j/Memgraph) **não toca no domínio** — a decisão é reversível.

Um banco de grafo passa a compensar quando o catálogo fica grande/dinâmico, é compartilhado por vários serviços, ou exige lineage/impacto em escala. Isso vale sobretudo para o **grafo dos documentos** (estágio 3), que é grande e muda a cada ingestão — aí a ferramenta é justificada; no catálogo, seria ouro de tolo.

### 10.6 Precedente e evidência

- **dbt MetricFlow** (semantic layer de mercado) já compila um **grafo semântico** — modelos = nós, entidades = arestas — para resolver joins e gerar SQL; as definições continuam em YAML versionado.
- **AWS Prescriptive Guidance** recomenda ontologia + *virtual knowledge graph* + **Metric Store** validado por SHACL, com métricas resolvidas de forma determinística.
- **Sequeda et al. (2023)**: 16,7% → 54,2% de acurácia nas mesmas perguntas com ontologia vs. schema cru. Benchmark dbt (2026): semantic layer ~98–100% vs. text-to-SQL ~84–90%.

### 10.7 A fronteira que não muda

O **grafo do catálogo** é **fechado e determinístico**: o LLM não o percorre livremente — quem percorre é o `validate_plan`. O **grafo dos documentos** (estágio 3) é **fuzzy** e alimenta só a explicação. Confundir os dois reintroduz exatamente o risco que o catálogo existe para eliminar.

---

## 11. O que fica de fora

- **Documentos** (metodologias, glossários): são o RAG.
- **Dados oficiais**: ficam no ClickHouse.
- **Fórmula dos métodos e families**: é código, testado à parte.
- **Planos e resultados**: são produzidos pela execução, não governados pelo catálogo.

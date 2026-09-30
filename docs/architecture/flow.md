# Fluxo Textual do Cantábria

## O que mudou desde a versão original

Este fluxo foi escrito antes do código. O esqueleto (planos → validação →
motor → explicação) continua igual; o que mudou, com a decisão que mudou:

| Tema | Versão original | Hoje | Decisão |
|---|---|---|---|
| Guardrails de entrada | não havia | PII redigida e campo físico/SQL/injeção recusados **antes** de qualquer LLM (`domain/services/input_guard.py`) | ADR 0009 |
| Rotas do planner | `analytical`/`documental` | 5 rotas: `analytical` · `documental` · `capability` (texto do catálogo, sem LLM na resposta) · `clarify` · `refuse` com motivo tipificado (`domain/interpretation.py`) | ADR 0011 |
| Autorização | "usuário possui autorização?" (§5) | `validate_plan` cruza plano × capacidades do perfil; na rota `clarify`, `_authorize_clarification` nega antes de esclarecer | checklist §2 |
| Retry | não descrito | 1 retry de schema (→ `clarify` fixo) e 1 retry semântico (→ recusa tipificada), em `answer_question.py` | ADR 0008 |
| Gate de lastro | "validação final" genérica (§11 item 27) | programático e **bloqueante**: número do texto ∉ `AnalysisResult` → regenera 1× → só a tabela verificada (`execute_pipeline._grounded_insight`) | ADR 0009 |
| Small-cell | não havia | k = 10 clientes por célula × período, com supressão complementar | ADR 0009 |
| Artefatos (§10–§11) | "o Agente de IA gera artefatos" | gráficos **determinísticos** do `AnalysisResult` (`PlotlyArtifactBuilder`), catálogo fechado `bar/line/ranking_bar/table`; `artifact_location` = `derived://analysis-result/...` (upload real ao MinIO pendente) | ADR 0005 |
| Resposta ao usuário | "insights" | texto + gráfico + rodapé de proveniência legível (`_Fonte: … · protocolo CAN-XXXXXXXX_`) + bloco recolhível "Como calculei" gerado do plano validado; starters gerados do catálogo na abertura | ADR 0006, ADR 0016 (superfície de resposta) |
| Persistência | Mongo "Analysis/Calculation Store" | Mongo opcional: Conversation/Plan/Result/Artifact Store + **outbox** de eventos de domínio (coleção `events`); sem `MONGO_URL`, em memória (`src/entrypoints/composition.py`) | ADR 0002, ADR 0010 |
| RAG | MinIO + Qdrant obrigatórios | 20 docs `approved` em `data/knowledge/`, BM25 offline; Qdrant opcional com fallback (`resilient_knowledge.py`); síntese cita documentos pelo título | ADR 0012, ADR 0014 |
| Métricas | 4 | 7: `profitability`, `outstanding_balance`, `contract_count`, `customer_count`, `cdi_rate`, `selic_rate`, `inflation_ipca` (macro: só grão total) — catálogo `v3` | ADR 0013 |
| Versão do dado | `<hash>` | `dataset_version = <data>#sha256:<digest>` no `AnalysisResult`; `prompt_version` também gravado | ADR 0006 |

Os passos numerados abaixo descrevem a intenção; onde o texto original diz
"Agente gera", leia "código determinístico gera a partir do resultado".

## 1. Autenticação e Autorização

1. O usuário autentica-se na aplicação.
2. O sistema valida suas permissões de acesso.
3. O sistema determina quais métricas, dimensões, análises e conjuntos de dados o usuário está autorizado a consultar.

---

## 2. Interação Inicial

4. O usuário envia uma pergunta em linguagem natural.
5. A pergunta é armazenada no Conversation Store. O banco de conversation store é um `MongoDB`.
6. O histórico relevante da conversa é recuperado.
7. A pergunta e o contexto da conversa são enviados ao LLM.

---

## 3. Recuperação de Contexto Corporativo

8. Assim que a pergunta é recebida, o sistema inicia em paralelo o processo de recuperação de conhecimento corporativo.

9. O mecanismo de recuperação recebe:

- pergunta original;
- contexto relevante da conversa;
- informações de autorização do usuário.

10. São consultados:

### Value Object Store

Documentos oficiais disponibilizados pelas áreas de negócio e são armazenados em um value object database, o MinIO (opcional; a fonte da verdade versionada é `data/knowledge/*.md`, ingerida por `make ingest` — ADR 0014).

Exemplos:

- metodologias;
- glossários;
- definições;
- políticas;
- regras de negócio.

### Vector Database

Embeddings derivados dos documentos oficiais são armazenados em um banco de dados vetorial, o Qdrant (opcional: sem `QDRANT_URL`/`embeddings`, ou com resultado vazio, a busca cai para BM25 lexical local — `adapters/outbound/resilient_knowledge.py`).

11. O mecanismo de recuperação retorna os trechos mais relevantes para a pergunta do usuário.

12. Os documentos recuperados permanecem disponíveis durante toda a execução e serão utilizados posteriormente pelo LLM na geração da resposta final.

A recuperação de conhecimento ocorre em paralelo à:

- geração dos planos;
- validação semântica;
- persistência dos planos;
- execução dos cálculos;
- execução das análises.

O objetivo é reduzir latência e garantir que o contexto documental já esteja disponível quando os resultados analíticos forem produzidos.

---

## 4. Construção do Plano Analítico

13. O LLM interpreta a intenção do usuário.

14. O LLM propõe dois tipos de plano estruturados, que são **entidades separadas** e se referenciam por `id`:

- **CalculationPlan** — descreve *o que calcular*: uma métrica, a quebra e o campo amostral, para um período;
- **AnalysisPlan** — descreve *o que fazer com os cálculos*: os métodos estatísticos e as operações.

### CalculationPlan

Um `CalculationPlan` tem **uma métrica**. O `id` do plano é a referência da série — a métrica não tem id próprio de referência. A métrica traz a regra de cálculo (`rule_id`), a **quebra** (`subjects`) e o **campo amostral** (`sample`); o plano traz o `period`.

O `period` é a **janela**. Dois planos podem ter a mesma janela (ex.: duas métricas no mesmo período); o que não se repete é o `calculation_plan_id`.

```yaml
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

### AnalysisPlan

O `AnalysisPlan` **não contém** os `CalculationPlans`: ele referencia os planos pelo `calculation_plan_id`. Tem duas partes:

- **`statistical_method`** — calcula o número. Cada método lê os `calculation_plan_ids` (valores direto do cálculo) **ou** os `statistic_refs` (resultado de um método declarado antes). Método **não tem `params`**: o nome do método diz qual quantidade sai.
- **`operations`** — o que fazer com o número pronto (`ranking`, `comparison`). É opcional, e é onde existem `params` (`order`, `top_n`, `axis`, ...).

#### Métodos (`statistical_method`)

Catálogo **fechado e enumerável** — validar é verificar pertencimento, e o que está fora é recusado como `not_expressible`.

| `method` | O que produz |
|---|---|
| `null` | os valores verificados, sem tratamento |
| `mean` | média da série por entidade (proibida em `profitability`) |
| `median` | mediana da série por entidade |
| `mode` | valor mais frequente da série (`null` sem repetição) |
| `std` | desvio-padrão por entidade (volatilidade) |
| `dispersion` | pacote: `mean, median, std, variance, min, max, q1, q3, iqr` (proibido em `profitability`) |
| `variation` | diferença entre **dois** cálculos colapsados: a absoluta (numa taxa, já é p.p.) e a percentual |
| `trend` | inclinação por entidade no eixo ordenado (série temporal ou nível ordinal) |
| `share` | parte ÷ todo (métrica somável, resultado colapsado) |
| `correlation` | Pearson entre **dois** resultados, mesmas entidades, n >= 3 |
| `outlier` | pontos atípicos do resultado (IQR 1.5, mínimo 4 pontos) |

Um método só pode referenciar um método **declarado antes** dele (sem ciclo).

#### Operações (`operations`)

Não calculam número: organizam o resultado. Aqui existem `params`.

| `type` | O que faz | `params` |
|---|---|---|
| `ranking` | ordena o resultado | `order`, `top_n`, `axis`: `entity`/`period` (sempre obrigatório) |
| `comparison` | mostra valores **lado a lado** | `across`: `entity`/`result` |
| `cumulative_share` | participação acumulada (Pareto) | `cutoff` |
| `selection` | pega linhas por condição relativa ao resultado | `rule`, `value` |
| `pivot` | cruza dois eixos numa tabela | `rows`, `columns` |
| `decomposition` | contribuição de cada grupo para a variação total | `refs`: `[variation, share]`; contribuição = `share_base × Δtaxa`; a soma fecha com o efeito-taxa total |

`ranking.axis` é **sempre obrigatório**: "qual segmento é mais rentável" ordena **entidades** enquanto "qual mês foi o melhor" ordena **períodos**; não há inferência.

`comparison` não calcula: só põe valores lado a lado. Quem mede direção/inclinação é `trend`; "melhor/pior" é `ranking` com `top_n: 1`.

`decomposition` é a única operação que lê **dois** métodos (a variação e a participação) e devolve a contribuição de **efeito-taxa** de cada grupo; a soma fecha com o efeito-taxa total. O resíduo de mix exigiria a share das duas janelas (extensão futura).

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

Exemplo simples — quando o resumo já é a resposta (sem operação):

```yaml
AnalysisPlan:
    analysis_plan_id: plan2
    statistical_method:
        - id: s1
          method: mean
          calculation_plan_ids: [calc_prof_seg]
    operations: []
```

#### Comparação entre períodos

`period` pertence ao `CalculationPlan`. Por isso toda pergunta período-contra-período é expressa como **dois `CalculationPlans` com a mesma quebra e períodos diferentes**, lidos por um único método `variation`.

```yaml
# "Agosto/2026 foi melhor que agosto/2025?"
statistical_method:
    - id: s1
      method: variation
      calculation_plan_ids: [calc_prof_2025_08, calc_prof_2026_08]
```

`variation` devolve a diferença absoluta (numa taxa, já é p.p.) e a percentual — não há escolha a declarar no plano.

O papel do LLM é apenas interpretar a pergunta e propor os planos. O LLM não executa cálculos nem produz valores financeiros.

---

## 5. Semantic Graph Validation

15. O plano é enviado para validação determinística.

São verificadas as seguintes regras:

### Segurança

- usuário possui autorização para acessar os dados?

### Grafo Semântico de Conhecimento

- métrica existe?
- dimensão existe?
- período é suportado?
- regra existe?
- caminho de integração é válido?

### Compatibilidade Analítica

- método estatístico é suportado?
- operação é suportada?
- combinação de métrica, quebra e campo amostral é permitida?
- método/operação é compatível com a métrica?

Um grafo semântico de conhecimento atua como camada de governança responsável por impedir combinações inválidas ou não suportadas.

---

## 6. Persistência dos Planos

16. Os planos validados são armazenados em um banco `MongoDB` de armazenamento de planos e resultados.

Existem apenas dois stores lógicos: **Analysis Store** e **Calculation Store**. Planos e resultados são mantidos como registros separados, diferenciados pelo campo `type` (`plan` ou `result`).

### Analysis Store

```yaml
Plan:
    - plan_id                     # analysis_plan_id
    - calculation_plan_ids         # os planos que este AnalysisPlan consome
    - type: plan
    - plan_dsc
    - timestamp
```

### Calculation Store

```yaml
Plan:
    - plan_id                     # calculation_plan_id
    - type: plan
    - plan_dsc
    - timestamp
```

O vínculo vive no `AnalysisPlan` (`calculation_plan_ids`); repetir `analysis_plan_id` no lado do cálculo seria uma segunda fonte para o mesmo dado.

O objetivo é auditoria e reprodutibilidade.

---

## 7. Execução Determinística

17. O motor de execução recebe os planos validados.

18. O motor consulta os dados oficiais que estão armazenados em um banco `Clickhouse`.

Exemplos:

- clientes;
- segmentação;
- rentabilidade.

19. O motor executa deterministicamente:

- filtros;
- joins declarados;
- alinhamento temporal;
- agregações permitidas.

Nenhum cálculo financeiro é realizado pelo LLM.

---

## 8. Geração dos Resultados

20. O motor produz um CalculationResult para cada CalculationPlan e um AnalysisResult para o AnalysisPlan.

Primeiro os motores determinísticos produzem os `CalculationResults` (valores por sujeito e período). Em seguida a análise consome esses valores, executando os `statistical_method` e, se houver, as `operations`.

### CalculationResult

```yaml
CalculationResult:
    calculation_plan_id: calc_prof_seg
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

O `calculation_plan_id` é a série: como o plano tem uma métrica, não há `metric_ref` separado.

### AnalysisResult

O `AnalysisResult` espelha a estrutura do `AnalysisPlan`: cada método traz o número produzido e cada operação traz a saída (ausente quando `operations` é vazio).

```yaml
AnalysisResult:
    analysis_plan_id: plan1
    catalog_version: v3
    dataset_version: 2026-08-31#sha256:<digest>   # HashedSnapshotVersionAdapter
    prompt_version: interpretation=v1,insight=v3,documental=v1
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
    insights: NULL
```

A identidade de cada linha é o dicionário `subjects` qualificado por `type.level`; valor não calculável vem como `null` com motivo, nunca `0`.

21. O resultado calculado é armazenado no Calculation Store e o resultado analítico é armazenado no Analysis Store.

O resultado permanece rastreável ao:

- plano utilizado;
- snapshot consultado;
- regras utilizadas.

---

## 9. Persistência dos Resultados

Os resultados são acrescentados como novos registros (`type: result`) nos mesmos stores lógicos, mantidos separados dos planos.

### Analysis Store

```yaml
Result:
    - result_id
    - plan_id
    - type: result
    - result_dsc
    - timestamp
```

### Calculation Store

```yaml
Result:
    - result_id
    - plan_id
    - type: result
    - result_dsc
    - timestamp
```

O objetivo é auditoria, reprodutibilidade e reutilização dos resultados.

---

## 10. Geração dos Insights

22. Após a execução analítica, o Agente de IA recebe:

- pergunta original;
- contexto da conversa;
- `AnalysisResult` e `CalculationResult`(s) — números já verificados;
- documentos recuperados pelo mecanismo de recuperação de conhecimento;
- as ressalvas da resposta (período, ponderação, supressão small-cell, amostra vazia).

23. O Agente **não recalcula, não consulta dado e não roda estatística complementar**: qualquer número novo seria um número não verificado. Ele interpreta apenas o que os motores determinísticos produziram e o que os documentos aprovados explicam.

24. O Agente **não elege causa** nem "qual variável explica melhor": associação e contribuição não são causalidade. Pergunta causal recebe o número verificado e a recusa parcial.

25. O redator (LLM, prompt `data/prompts/insight/v3`) gera **só o texto**; e o texto passa pelo **gate de lastro** (`execute_pipeline._grounded_insight`, ADR 0009): qualquer número que não exista no `AnalysisResult` (tolerância 0.006) força uma regeneração; na segunda falha o usuário recebe a ressalva fixa e a **tabela verificada**. Os artefatos de apresentação **não** são gerados pelo LLM: `PlotlyArtifactBuilder` os constrói deterministicamente do `AnalysisResult` conforme `AnalysisPlan.presentation` (`bar` · `line` · `ranking_bar` · `table`, degradado para `table` quando incompatível — ADR 0005). Assim a resposta tem:

- insights (texto);
- artefatos de **apresentação** (gráficos, tabelas), construídos exclusivamente sobre os números verificados;
- rodapé de proveniência legível (`_Fonte: rentabilidade (Σ margem ÷ Σ saldo), dados oficiais fechados em 31/08/2026 · protocolo CAN-XXXXXXXX_`; protocolo = 8 primeiros hex do `trace_id`) e o bloco recolhível **"Como calculei"**, gerado deterministicamente do plano validado (ADR 0006, ADR 0016 — superfície de resposta).

Neste ponto o Agente interpreta resultados já verificados, mas não produz valores financeiros novos nem altera resultados calculados pelos motores determinísticos.

---

## 11. Construção do AnalysisResult Final

26. Os insights e artefatos produzidos pelo Agente são incorporados ao AnalysisResult.

Exemplo:

```yaml
AnalysisResult:

    analysis_result_id: AnalysisResult1
    analysis_plan_id: plan1
    catalog_version: v3
    dataset_version: 2026-08-31#sha256:<digest>   # HashedSnapshotVersionAdapter
    prompt_version: interpretation=v1,insight=v3,documental=v1
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

    insights: |
        O segmento Atacado PJ apresentou a maior volatilidade
        de rentabilidade no período (desvio de 5,2%).

        O segmento Varejo PF foi o mais estável (desvio de 3,1%).

    artifacts:
        - ART-001
```

O AnalysisResult contém apenas referências (`artifact_id`) para os artefatos. Os arquivos de **apresentação** (gráficos, tabelas exportadas, imagens, relatórios) NÃO ficam no banco relacional: eles são armazenados em um **Object Store**, enquanto o **Artifact Store** guarda apenas metadados e rastreabilidade.

### Artifact Store

```yaml
Artifact:

    artifact_id: ART-001

    analysis_plan_id: AnalysisPlan1

    analysis_result_id: AnalysisResult1

    artifact_name:
        profitability_dispersion_chart.png

    artifact_location:
        derived://analysis-result/<artifact_id>   # hoje: reproduzível do AnalysisResult; upload ao MinIO pendente (ADR 0005, Evidência)

    timestamp:
        2026-09-11T15:00:00
```

### Responsabilidade de Cada Camada

```text
AnalysisResult
    ↓ artifact_id

Artifact Store
    ↓ artifact_location

Object Store
    ↓

Arquivo gerado
```

Onde:

- AnalysisResult contém apenas referências para os artefatos;
- Artifact Store contém metadados e rastreabilidade;
- Object Store contém o arquivo real.

Benefícios da decisão:

- auditoria;
- rastreabilidade;
- reprodutibilidade;
- recuperação de artefatos em conversas futuras;
- separação entre metadados e arquivos binários;
- alinhamento com arquiteturas corporativas reais.

27. O AnalysisResult Final é submetido à validação final.

São verificadas:

- integridade estrutural;
- consistência do schema;
- associação correta entre plano e resultado;
- conformidade com as regras de apresentação.

O objetivo desta validação é garantir que o Agente apenas complemente os resultados com explicações e artefatos, sem alterar informações produzidas pelos motores determinísticos.

---

## 12. Persistência e Entrega

28. O AnalysisResult Final é armazenado no Analysis Store.

29. A resposta final é armazenada no Conversation Store.

30. O usuário recebe:

- resultados calculados;
- resultados analíticos;
- insights produzidos pela IA;
- artefatos de apresentação construídos sobre os números verificados.

31. A execução é encerrada.

---

## 13. Regra de Governança

Este documento — "Fluxo Textual do Cantábria" — passa a ser a referência arquitetural vigente.

Em caso de conflito:

```text
Fluxo Textual do Cantábria
        >
documentos anteriores
```

Os demais documentos deverão ser atualizados posteriormente para refletir as decisões registradas neste fluxo.
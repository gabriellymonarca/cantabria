# Registro de decisões (ADRs)

Cada decisão segue o mesmo caminho: **contexto → decisão → trade-off → evidência**.
Alternativas rejeitadas ficam em meia linha dentro da decisão. A numeração
0001–0017 é estável: "ADR 00NN" no resto do repositório aponta para `D-00NN` aqui.

| # | Título | Data | Área |
|---|---|---|---|
| D-0001 | Agentes de código orquestrados por skills e perfis | 2026-09-29 | docs |
| D-0002 | DDD completo: agregados emitem eventos, outbox, policies | 2026-09-29 | ddd |
| D-0003 | Stack de persistência: MongoDB, Qdrant e MinIO ao lado do ClickHouse | 2026-09-29 | infra |
| D-0004 | Ordem de entrega: bloqueadores de demo antes de IA, DDD e docs | 2026-09-29 | produto |
| D-0005 | Gráficos determinísticos a partir do resultado verificado | 2026-09-29 | ia |
| D-0006 | Verificação dos números: oráculo independente e proveniência | 2026-09-29 | ia |
| D-0007 | Regras de dependência por teste com allow-list que só encolhe | 2026-09-29 | ddd |
| D-0008 | Compose único com profiles e seed em container | 2026-09-29 | infra |
| D-0009 | Guardrails de entrada, small-cell por período e gate de lastro | 2026-09-29 | ia |
| D-0010 | MongoDB na fiação: histórico, auditoria, barra lateral e outbox | 2026-09-29 | infra |
| D-0011 | Rota `capability` gerada do catálogo | 2026-09-29 | ia |
| D-0012 | Síntese da rota documental com contrato de prompt próprio | 2026-09-29 | ia |
| D-0013 | Dados de mercado como métricas de referência (CDI/SELIC/IPCA) | 2026-09-29 | dados |
| D-0014 | RAG semântico (Qdrant) + documentos no MinIO com fallback BM25 | 2026-09-29 | infra / ia |
| D-0015 | Harness de avaliação offline-first (`python -m eval`) | 2026-09-30 | ia |
| D-0016 | Superfície de resposta: rodapé legível, "Como calculei", starters | 2026-09-30 | produto / ia |
| D-0017 | Decisões fundadoras do módulo de análise (consolidação) | 2026-09-30 | ddd / ia |

## D-0001 — Agentes de código orquestrados por skills e perfis

- **Contexto.** Projeto solo em duas máquinas (Windows sem Docker, Linux com Docker). Três auditorias
  mostraram regras bem escritas em `AGENTS.md` que o código não cumpria (agregados sem eventos,
  efeitos colaterais em `queries/`, small-cell testada mas desligada). Regra só em prosa não se sustenta.
- **Decisão.** `AGENTS.md` curto e comum às duas ferramentas; conteúdo canônico em `.devin/`
  (perfis `ddd-architect`, `ai-engineer`, `infra-devops`, `reviewer`, `test-runner`, `docs-writer`;
  skills `audit`, `implement`, `ddd-review`, `adr`, `dod`, `eval`, `preflight`; hooks que bloqueiam
  caminhos protegidos). `.opencode/` são espelhos finos. Quem escreve nunca revisa.
  Rejeitadas: só `AGENTS.md` longo (já falhou); só hooks/CI (reprova, não orienta).
- **Trade-offs.** Formato do opencode confirmado por conhecimento prévio, não por doc ao vivo;
  bloqueio de caminhos no opencode é só por instrução + permissão.
- **Evidência.** `AGENTS.md`, `.devin/**`, `.opencode/**`, `opencode.json`,
  `scripts/hooks/protect_paths.py`, `tests/test_architecture.py`.

## D-0002 — DDD completo: agregados emitem eventos, outbox, policies

- **Contexto.** A auditoria de `src/` achou zero `DomainEvent`, entidades sem comportamento, nenhum
  `policies/`, o fluxo com efeitos colaterais em `application/queries/` e regras duplicadas em dois
  contextos. O `flow.md` exige auditoria e reprodutibilidade — exatamente onde eventos têm valor.
- **Decisão.** DDD completo: shared kernel `DomainEvent`/`AggregateRoot`; agregados `Conversation`,
  `AnalysisRequest`, `Calculation`; `ProcessUserRequestQuery` → `AnswerQuestionCommand`;
  `validate_plan`/`execute_analysis` como domain services; policies reativas; `shared/{config,
  logging,observability}` → `src/cross_cutting/`. Rejeitadas: alinhar o doc ao código (perde a
  trilha de auditoria); agregado mínimo só onde há persistência (duas formas de fazer o mesmo).
- **Trade-offs.** Refatoração grande perto da entrega; mitigada pelo teste de arquitetura (D-0007),
  passos pequenos e revisor independente.
- **Evidência.** `user_interaction/domain/conversation.py`, `financial_analysis/domain/analysis_request.py`,
  `financial_calculation/domain/calculation.py` (`AggregateRoot`); `financial_analysis/application/policies/`;
  `tests/test_architecture.py` (teto de 2 violações conhecidas).

## D-0003 — Stack de persistência: MongoDB, Qdrant e MinIO ao lado do ClickHouse

- **Contexto.** `flow.md` descrevia quatro armazenamentos, mas só o ClickHouse existia; histórico
  vivia na sessão do Chainlit, planos/resultados em memória, RAG só BM25. O usuário pediu barra
  lateral de sessões e documentos de referência guardados.
- **Decisão.** MongoDB (stores + outbox + `data_layer`), MinIO (documentos versionados, artefatos) e
  Qdrant (trechos aprovados), todos com **degradação graciosa**: fora do ar, a aplicação sobe com
  adapters em memória/locais e aviso. Rejeitadas: só documentar a stack real (sem auditoria);
  só MongoDB (RAG continua léxico, documentos sem lugar).
- **Trade-offs.** Três serviços a mais na demo; embeddings dependem do endpoint (BM25 cobre).
- **Evidência.** Implementação em D-0010 (Mongo) e D-0014 (Qdrant/MinIO); fiação em
  `src/entrypoints/composition.py`; `/ready` reporta cada store.

## D-0004 — Ordem de entrega: bloqueadores de demo antes de IA, DDD e docs

- **Contexto.** A banca precisa **rodar** o projeto em 90 min. A auditoria achou `docker build`
  quebrado em clone limpo, três composes colidindo, Langfuse obrigatório por padrão, sem CI, sem `make demo`.
- **Decisão.** Fases: (1) demo, (2) IA de alto risco, (3) DDD + persistência, (4) avaliação,
  (5) documentação. Rejeitadas: IA primeiro (banca pode nem rodar); DDD primeiro (atrasa evidência).
- **Trade-offs.** A Fase 3 retoca código das Fases 1–2; se o tempo apertar, Qdrant/MinIO caem
  para roadmap antes de cortar eval ou docs.
- **Evidência.** Fases 0–5 fechadas em 2026-09-30 (`.devin/checklist.md` §14).

## D-0005 — Gráficos determinísticos a partir do resultado verificado

- **Contexto.** O usuário quer gráficos e sugeriu "tools para o agente". Uma tool `plot(values=...)`
  devolve o modelo à posição de fonte de número — o furo que a arquitetura existe para fechar.
- **Decisão.** O LLM escolhe só a **apresentação** (`presentation`: `bar` · `line` · `ranking_bar`
  · `table`, catálogo fechado, validado como o resto do plano); `PlotlyArtifactBuilder` renderiza
  **só** valores do `AnalysisResult`, sem agregação nem arredondamento; proposta inválida degrada
  para `table`. Rejeitadas: tool-use livre (número não verificável); só tabela (usuário pediu gráfico).
- **Trade-offs.** Menos flexibilidade visual; ainda **não há upload ao MinIO** — `location` é
  `derived://analysis-result/<artifact_id>`, nunca um `s3://` inventado (roadmap).
- **Evidência.** `tests/test_artifact_builder.py`, `tests/test_execute_pipeline.py`;
  `adapters/outbound/plotly_artifact_builder.py`.

## D-0006 — Verificação dos números: oráculo independente e proveniência

- **Contexto.** "Como sei que o número que o LLM reporta está certo?" São duas perguntas:
  (1) o motor calculou certo? (2) o LLM reportou o que o motor calculou? Havia um oráculo para
  10 casos e uma checagem de números que só logava.
- **Decisão.** Três camadas: (1) oráculo independente (`Decimal`, sem importar `src/`) comparado
  célula a célula, tolerância 1e-9; (2) relatório oficial fictício gerado no seed; (3) gate de
  lastro programático + rodapé de proveniência. Rejeitadas: confiar nos testes do motor; oráculo sem
  cruzamento externo.
- **Trade-offs.** Todo "oficial" aqui é sintético — o valor é o **mecanismo**, não a verdade contábil.
  **Estado real:** camadas 1 e 3 implementadas; a camada 2 (`relatorio_oficial_mensal`)
  **não foi implementada** — roadmap.
- **Evidência.** `data/oracle/oracle_v1.yaml` + `python -m eval --layer engine` (D-0015);
  `utils/validate_oracle.py` (paridade ClickHouse, integração); gate e rodapé em D-0009/D-0016.

## D-0007 — Regras de dependência por teste com allow-list que só encolhe

- **Contexto.** Regras hexagonais em prosa foram violadas 32 vezes sem ninguém notar
  (`financial_analysis` importando domínio alheio, `structlog` em `application/`).
- **Decisão.** `tests/test_architecture.py` com `KNOWN_VIOLATIONS` explícita: falha em violação
  nova, falha se uma entrada deixou de ser violação, teto numérico que só baixa; folhas (`auth`,
  `financial_calculation`) não importam outro contexto. Rejeitadas: `import-linter` (dependência
  nova, sem noção de dívida conhecida); hook do agente (não roda no CI).
- **Trade-offs.** `ast` não vê imports dinâmicos (não há no projeto). Adicionar entrada exige ADR.
- **Evidência.** `tests/test_architecture.py`: de 32 violações (2026-09-29) para teto `<= 2`
  (structlog em dois módulos de `application/`).

## D-0008 — Compose único com profiles e seed em container

- **Contexto.** Clone limpo não subia: `Dockerfile` copiava `.chainlit/` ignorado; três composes
  com o mesmo `name` e ClickHouse nas mesmas portas; seed só no host; `config.example.yaml`
  exigia Langfuse.
- **Decisão.** Um `compose.yaml` na raiz com profiles `core | seed | stores | observability`;
  seed na mesma imagem do app; imagem só com arquivos em `git ls-files`; `.dockerignore`;
  `requirements.lock` opcional (`ARG USE_LOCK`); Langfuse desligado por padrão; um caminho
  documentado (`make demo`). Rejeitadas: três composes documentados (colisão continua);
  `include:` por diretório (três lugares para editar).
- **Trade-offs.** `.env` da raiz obrigatório até para o Langfuse; `docker compose down` sem
  profile não derruba tudo (`make stack-down`).
- **Evidência.** Job `docker-build` e `integration` em `.github/workflows/ci.yml`;
  `scripts/preflight.py` (GO/NO-GO); `docker compose config` com os 4 profiles.

## D-0009 — Guardrails de entrada, small-cell por período e gate de lastro

- **Contexto.** Três furos na fronteira generativa: small-cell k = 10 implementada mas nunca
  acionada (o port não devolvia população); grounding só logava; nenhum filtro de entrada
  (CPF ia ao provedor e ao trace; SQL e injeção só barrados se o LLM quisesse).
- **Decisão.** A mesma query agregada devolve `population` (`uniqExact`); supressão por
  **célula × período**, menor população vence, complementar obrigatória; texto sem lastro
  regenera **uma** vez e depois entrega só a tabela verificada; pré-filtro determinístico antes
  do LLM (CPF/CNPJ com dígitos verificadores, e-mail, telefone → redigir; campo físico, SQL,
  marcador de injeção → recusar com código); PII redigida no adapter antes do span.
  Rejeitadas: segunda query de `COUNT DISTINCT`; supressão por célula ignorando período; confiar no prompt.
- **Trade-offs.** Série com um mês pequeno perde a estatística da série (conservador); regeneração
  dobra o custo em casos raros; guardrail léxico tem falsos positivos possíveis.
- **Evidência.** `tests/test_execute_pipeline.py::test_small_cell_e_suprimida_no_pipeline_com_complementar`,
  `::test_insight_rejeitado_duas_vezes_entrega_a_tabela_verificada`; `tests/test_execute_analysis.py::test_small_cell_e_julgada_por_periodo`;
  `tests/test_input_guard.py`, `tests/test_redaction.py`, `tests/test_chainlit_privacy.py`, `tests/test_provenance.py`.

## D-0010 — MongoDB na fiação: histórico, auditoria, barra lateral e outbox

- **Contexto.** Agregados já emitiam eventos, mas os stores eram em memória: conversa sumia ao
  recarregar, planos/resultados sem auditoria, sem barra lateral. `mongodb` já estava no compose sem uso.
- **Decisão.** `MONGO_URL` + ping no boot ligam os adapters Mongo (`conversations`, `analysis_store`
  com `type: plan|result`, `calculation_store`, `artifacts`, `events`); sem Mongo, memória + aviso e
  `/ready` reporta (`disabled (in-memory)`), sem 503. `Decimal` → `Decimal128`. Data layer do
  Chainlit lê a mesma coleção. Outbox é best-effort; stores de plano/resultado falham alto.
  Rejeitadas: seguir em memória; Mongo obrigatório (demo morre).
- **Trade-offs.** Ping custa ~1,5 s com servidor fora; dois caminhos de fiação para testar;
  `CalculationResult` segue em memória (port não carrega os dois).
- **Evidência.** `tests/test_mongo_stores.py` (mongomock), `tests/test_mongo_parity.py` (`-m integration`).

## D-0011 — Rota `capability` gerada do catálogo

- **Contexto.** Perguntas meta ("o que você faz?") caíam em `documental` (RAG respondia "não
  encontrei") ou `refuse`. O catálogo já era a lista autoritativa do que se pode perguntar.
- **Decisão.** `InterpretationRoute.CAPABILITY`; resposta = `describe_capabilities(catálogo ativo)`,
  determinística, sem plano, sem gate de lastro (não há número). Rejeitadas: deixar em `documental`
  (depende do acervo); LLM redigir o escopo (prometeria o que não existe).
- **Trade-offs.** Mesmo texto para qualquer perfil (descreve produto, não dado); depende do planner
  acertar a rota.
- **Evidência.** `tests/test_capability_route.py`, `tests/test_describe_capabilities.py`,
  `tests/test_prompt_examples.py`.

## D-0012 — Síntese da rota documental com contrato de prompt próprio

- **Contexto.** A rota `documental` despejava trechos BM25 concatenados: repetidos, sem citação,
  sem enfrentar a pergunta. Aqui não há `AnalysisResult`, então o risco é outro: inventar fora dos
  trechos e vazar `document_id`.
- **Decisão.** Port `DocumentalSynthesisPort` opcional no pipeline; adapter LangChain com prompt
  versionado `data/prompts/documental/v1`; falha ou texto vazio → concatenação antiga (rota nunca
  fica muda); citar **por título**, nunca por id. Rejeitadas: manter concatenação; síntese dentro do
  adapter de conhecimento (mistura retrieval e geração).
- **Trade-offs.** Um round-trip de LLM a mais; "somente os trechos" é regra de prompt, não programática
  (programático é só o `sanitize_user_text`).
- **Evidência.** `tests/test_documental_synthesis.py` (9 casos), `tests/test_local_knowledge.py`,
  `/ready` reporta `documental=v1`.

## D-0013 — Dados de mercado como métricas de referência (CDI/SELIC/IPCA)

- **Contexto.** Rentabilidade × CDI exige séries macro. Uma tool de API do BACEN em tempo de
  resposta quebraria a demo offline e o gate de lastro (número fora do `CalculationResult`).
- **Decisão.** Séries SGS 4390 (SELIC), 4391 (CDI), 433 (IPCA) ingeridas **offline**
  (`utils/ingest_market_data.py` → `data/market/bacen_sgs.csv` com proveniência) e semeadas em
  `cantabria.mercado_indicadores`; catálogo `v3` com `cdi_rate`, `selic_rate`, `inflation_ipca`
  (`macro: true`, só `total.total`); agregação `compounded_rate`: `R = Π(1+rᵢ) − 1`, anualizada
  `(1+R)^(12/n) − 1` na mesma base de `profitability`; taxa ≤ −100% ou janela vazia → `null`.
  Rejeitadas: tool em tempo de resposta; port `MarketDataRepository` novo (multiplica portas).
  `definitions.md` ratificado pelo humano em 2026-09-30.
- **Trade-offs.** Valor sempre anualizado (a taxa mensal publicada não aparece como resultado);
  anualização pelos meses observados; `spread`/`real_return` (6b) ficam fora.
- **Evidência.** `tests/test_shared_aggregation.py`, `tests/test_market_ingest.py`,
  `tests/test_semantic_catalog.py`, `tests/test_clickhouse_parity.py` (3 casos de mercado);
  seed: 72 pontos; CDI `total` 2025-09..2026-08 = `0.146273753776876111419883876`.

## D-0014 — RAG semântico (Qdrant) + documentos no MinIO com fallback BM25

- **Contexto.** Acervo `data/knowledge/*.md` recuperado só por BM25 (sem sinônimos). D-0003 já
  decidira a stack; faltava ligar Qdrant (trechos) e MinIO (arquivo oficial versionado).
- **Decisão.** `DocumentStorePort` + `MinioDocumentStoreAdapter` (chave determinística, idempotente);
  `QdrantKnowledgeAdapter` (coleção `knowledge`, um ponto por seção `##`, filtro `status: approved`,
  `score_threshold` 0.35); `ResilientKnowledgeAdapter(primário, BM25)` cai no fallback em exceção
  ou vazio. Ingestão offline (`utils/ingest_documents.py`); embeddings de documento nunca em tempo
  de resposta. Rejeitadas: só BM25; Qdrant sem fallback (viola degradação graciosa).
- **Trade-offs.** 0.35 é chute a recalibrar com o harness; o app ainda não **lê** documento do
  MinIO no caminho de resposta (só ingestão grava); ingestão não poda órfãos.
- **Evidência.** `tests/test_minio_document_store.py`, `tests/test_qdrant_knowledge.py`,
  `tests/test_local_knowledge.py`, `tests/test_architecture.py` sem entradas novas.

## D-0015 — Harness de avaliação offline-first (`python -m eval`)

- **Contexto.** A rubrica pede splits dev/test (60–80 casos) e avaliação por camada com relatório.
  Havia só pytest + `utils/validate_oracle.py` (exige Docker, sem relatório).
- **Decisão.** Pacote `src/eval` com CLI `--layer planner|routing|engine|explanation|e2e|redteam|baseline|all
  --split dev --report reports/ [--live]`; dataset `data/eval/dev.yaml` (80 casos) e
  `data/eval/redteam.yaml`; `engine` e `redteam` offline (fixture `parity-tiny-v1`, tolerância 1e-9);
  generativas só com `--live`; relatório `reports/eval-dev.{md,json}`, resumo versionado em
  `docs/evaluation-report.md`. **Adendo:** camada `baseline` — LLM ingênuo com schema físico gera
  SQL executado em SQLite só-leitura sobre o fixture; veredito `correct | silent_wrong | error |
  no_sql`; errar é o esperado, nunca falha o harness. Rejeitadas: mais scripts em `utils/`;
  harness externo (promptfoo etc.).
- **Trade-offs.** Fixture replica a semântica do ClickHouse em Python (paridade real segue no
  `validate_oracle.py`); `--live` não roda na suíte; `test` protegido aguarda aprovação humana.
- **Evidência.** `python -m eval --layer engine --split dev` → 37 pass · 0 fail · 43 skip;
  `--layer redteam` → 16/16; `tests/test_eval_dataset.py`, `tests/test_eval_engine.py`,
  `tests/test_eval_redteam.py`, `tests/test_eval_cli.py`, `tests/test_eval_baseline.py` (16).

## D-0016 — Superfície de resposta: rodapé legível, "Como calculei", starters

- **Contexto.** Teste com usuário de negócio: rodapé com ids opacos (`rule_id`, hash, `trace_id`);
  "que gráficos você faz?" vazava `ranking_bar` do system prompt (OWASP LLM07); welcome como
  mensagem em vez de starters; resposta dizia o quê, não **como** foi calculado.
- **Decisão.** Rodapé `_Fonte: rentabilidade (Σ margem ÷ Σ saldo), dados oficiais fechados em
  31/08/2026 · protocolo CAN-XXXXXXXX_` (8 hex do `trace_id`; hash/catálogo ficam no trace);
  anti-vazamento em camadas (prompt + `capability` cobre formatos + `sanitize_user_text` só entre
  crases/underscore + RT-16); nota **"Como calculei"** determinística (`describe_method`) como
  `cl.Step` recolhível; starters do catálogo; `prompt_version` no `AnalysisResult`;
  `MAX_REQUEST_CHARS = 2000` (`too_long`). Rejeitadas: manter ids; remover rodapé; LLM explicar o
  método; só sanitizar palavras comuns.
- **Trade-offs.** Usuário não vê hash/versão (auditoria via protocolo); palavra comum sem crases
  ainda vaza; nota depende de `cot != "hidden"`; 2000 conta caracteres, não tokens.
- **Evidência.** `tests/test_provenance.py`, `tests/test_describe_method.py`,
  `tests/test_chainlit_welcome.py`, `tests/test_insight_presentation.py`,
  `tests/test_input_guard_wiring.py`, `tests/test_eval_redteam.py` (16/16). Suíte: 792 testes em 2026-09-30.

## D-0017 — Decisões fundadoras do módulo de análise (consolidação)

Decisões da rodada de congelamento do `financial_analysis` que não tinham ADR próprio
(as demais daquela rodada — small-cell, stubs, snake_case, `AnalysisResult`, `dataset_version`,
oráculo — estão em D-0006, D-0009 e D-0015). Uma linha por decisão: contexto → decisão → trade-off.
Evidência comum: `tests/test_validate_plan.py`, `tests/test_execute_analysis.py`,
`tests/test_execute_calculation.py`, `tests/test_semantic_catalog.py`, `tests/test_create_plan_retry.py`.

| # | Decisão |
|---|---|
| 1 | Média simples de taxas mensais não é a rentabilidade da janela → `mean`, `dispersion`, `selection.above_mean/below_mean` **proibidos em ratio** → perde a média "intuitiva"; acaba o número plausível e errado. |
| 2 | `variation`, `share` e ranking precisavam de um número por entidade na janela → `grain: total` re-deriva no motor (ratio `Σnum ÷ Σden`; stock/count no fim do período) → mexe no `financial_calculation`, destrava as análises sem média de taxas. |
| 3 | `decomposition` era método mas só organiza resultados → vira **operação** com `refs: [variation, share]` → separa cálculo de organização; exigiu alinhar `definitions.md`, prompt e casos. |
| 4 | `distribution` e `share` tinham definições idênticas → unificados em `share` → perde um nome; elimina duplicidade. |
| 5 | Período ausente gerava `clarify` em perguntas claras → **default declarado no catálogo** (`snapshot`; `series`; `series` + `grain: total`) sempre **ecoado em `assumptions`**; `clarify` só quando a escolha muda a resposta → menos idas e vindas; assume em vez de perguntar. |
| 6 | Prompt e validação liam fontes diferentes → catálogo **versionado e imutável** (v1 → v2 com `shape`, `kind`, `compatibility`; hoje v3) → publicar nova versão em vez de editar; replay possível. |
| 7 | Nomes físicos (`ds_segm`) vazavam para o catálogo → mapeamento físico **só no adapter**; catálogo puramente semântico → troca de fonte mexe só no adapter. |
| 8 | Autorização dependia do LLM → **ampla + fina por métrica/eixo** via port do `auth`, decidida antes de esclarecer/executar → exige configurar capacidades; nega fora do LLM. |
| 9 | Planner erra de forma recuperável → **um** retry com erro tipificado, depois `refuse` → um round-trip a mais; robusto a deslize. |
| 10 | "Data fora do histórico" e "janelas mal formadas" viravam a mesma mensagem → `invalid_window` (topologia) separado de `out_of_window` (data) → um motivo a mais; mensagem certa para cada problema. |
| 12 | Associação entre métricas → `correlation` = Pearson, exatamente 2 métodos, n ≥ 3, variância > 0; senão `null` → simples e auditável; não cobre relações não lineares. |
| 13 | "Rentabilidade cresce com a vinculação?" → `trend` sobre **eixo ordinal**: regressão do valor no rank do nível, ≥ 3 níveis, `grain: total`; eixo nominal recusado → determinístico; não infere ordem. |
| 14 | Ranking de períodos × de entidades era ambíguo → `ranking.axis` **sempre obrigatório** → um campo a mais no plano; zero inferência. |
| 15 | Percentil de clientes é grão individual (proibido) → `selection.top_percent` é sobre **entidades** do resultado (qualquer métrica); `above_mean/below_mean` só em somável → não colide com grão individual. |
| 19 | `mode`/`outlier` sem definição em amostras pequenas → `null` **com motivo** (`UndefinedReason`), nunca 0 → nunca um zero fingindo medição. |
| 20 | Estoque e contagem não se somam no tempo → no `grain: total` valem o **fim do período** → coerente com semântica de estoque. |

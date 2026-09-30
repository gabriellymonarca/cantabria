# Como usar o Cantábria

Guia para subir a solução do zero na sua máquina (ou na base do cliente),
popular o banco, rodar a demo e configurar tudo. Arquitetura e decisões
continuam em `data/base-ficticia.md`, `data/clickhouse.md` e `docs/decisions.md`
(ADR 0003 para os stores, ADR 0008 para o compose único).

## 1. Pré-requisitos

| Item | Versão / detalhe |
|---|---|
| Docker + Docker Compose v2 | é o único requisito para rodar a demo |
| Endpoint de LLM OpenAI-compatível | URL + chave (ex.: OpenAI, ou gateway local) |
| Python 3.12 | só para rodar testes/lint no host ou o app fora do Docker |
| `make` | opcional (Linux/macOS); os comandos equivalentes estão em §2.2 |

Portas usadas no host (todas em `127.0.0.1`, exceto o app e a UI do Langfuse):

| Porta | Serviço | Profile |
|---|---|---|
| `8000` | app (Chainlit) | `core` |
| `8123` / `9000` | ClickHouse dos dados oficiais (HTTP / nativo) | `core` |
| `27017` · `6333` · `9002`/`9003` | MongoDB · Qdrant · MinIO API/console | `stores` (opcional; o app degrada sem eles) |
| `3000` · `3030` · `9090`/`9091` · `6379` · `5432` | Langfuse web · worker · MinIO · Redis · Postgres | `observability` (opcional) |

## 2. Subir do zero — há UM caminho

Há um único `compose.yaml` na raiz, organizado em *profiles* (grupos de
serviços que só sobem quando pedidos). Tudo parte de dois arquivos que você
copia dos templates versionados:

```bash
git clone <repo> cantabria && cd cantabria

cp .env.example .env                 # senhas do ClickHouse/MinIO; os valores de exemplo funcionam localmente
cp config.example.yaml config.yaml   # edite llm.api_key (e base_url/model se não for OpenAI)
```

O `.env` é carregado **antes** do `config.yaml`, então `CONFIG_PATH` pode morar
no `.env`. Variáveis já exportadas no shell têm precedência sobre o `.env`.

### 2.1. Linux / macOS

```bash
make demo
```

`make demo` faz, nesta ordem: `docker compose --profile core up -d --build`
(ClickHouse + app) → espera o ClickHouse ficar *healthy* → roda o seed **dentro
de um container** com a mesma imagem do app (`--profile seed run --rm seed`) →
`python scripts/preflight.py` → imprime `http://localhost:8000`.

### 2.2. Windows (PowerShell) ou sem `make`

São exatamente os mesmos comandos que o `make demo` executa:

```powershell
docker compose --profile core up -d --build
docker compose --profile seed run --rm seed     # espera o ClickHouse healthy, aplica o DDL e carrega
python scripts/preflight.py                     # opcional; só biblioteca padrão
```

Abra http://localhost:8000 e fale com o app.

Como funciona por dentro: o serviço `app` monta `./config.yaml` (somente
leitura) e lê o `.env`; dentro da rede do compose o banco se chama
`clickhouse`, e o compose já sobrescreve `CLICKHOUSE_HOST`. O `app` também
resolve `host.docker.internal` (útil para um LLM local ou o Langfuse). O
tracing Langfuse fica **desligado por padrão** (`observability.enabled:
false`); para ligá-lo, veja §2.4.

### 2.3. Desenvolver com o app no host (opcional)

Só o banco no Docker; app, testes e lint com o Python local:

```bash
make setup                                # pip install -e . -r requirements.txt
docker compose up -d --wait clickhouse    # só o banco (profile core)
make seed                                 # seed pelo host, via 127.0.0.1:8123
make run                                  # PYTHONPATH=src python -m entrypoints.app
```

Para expor fora do host (container/devcontainer), use `CHAINLIT_HOST=0.0.0.0`
(no devcontainer isso já vem configurado).

### 2.4. Profiles opcionais

```bash
make stores          # docker compose --profile stores up -d  (MongoDB, Qdrant, MinIO)
make observability   # ./scripts/langfuse_up.sh  (renderiza segredos + profile observability)
make stack-down      # derruba TODOS os profiles (down --remove-orphans)
```

- `stores` sobe os serviços da Fase 3 (ADR 0003/0010/0014). Com eles de pé, o
  app persiste histórico/auditoria no MongoDB e usa RAG semântico no Qdrant
  (documentos no MinIO, ingeridos por `make ingest`); sem eles — ou sem a
  seção `embeddings` no `config.yaml` — a busca continua lexical (BM25), o
  histórico fica em memória e a demo não cai. As variáveis
  (`MONGO_URL`, `QDRANT_URL`, `MINIO_ENDPOINT`, `MINIO_BUCKET`,
  `MINIO_ROOT_*`) estão no `.env.example`.
- `observability` exige `cp infrastructure/.env.example infrastructure/.env`
  preenchido; o script renderiza os arquivos de segredo em
  `infrastructure/docker/**` e sobe o Langfuse. Depois, no `config.yaml`,
  ponha `observability.enabled: true` e as chaves `LANGFUSE_INIT_PROJECT_*`
  (ver `README.md` § Observability).

### 2.5. Base de conhecimento no Qdrant (`make ingest`)

Com o profile `stores` de pé e a seção `embeddings` preenchida no `config.yaml`
(mesmo endpoint OpenAI-compatível do `llm` quando `base_url`/`api_key` ficam
vazios):

```bash
make ingest   # gera data/reference/*.docx|pptx (gitignored) e indexa no Qdrant
```

A geração é determinística a partir de `data/knowledge/*.md` (só `approved`);
a ingestão é idempotente (ids estáveis por documento + seção). O caminho de
resposta não fala com o MinIO nem reindexa nada: ele apenas consulta o Qdrant
e, se o resultado semântico vier vazio ou o store estiver fora do ar, cai na
busca lexical (BM25).

### Targets do `make`

| Target | O que faz |
|---|---|
| `make demo` | stack `core` → espera healthy → seed no container → preflight → URL |
| `make preflight` | `python scripts/preflight.py` (GO/NO-GO da demo) |
| `make stack` / `make stack-down` / `make logs` | `--profile core up -d --build` / derruba todos os profiles / logs do app |
| `make stores` / `make observability` | profiles opcionais (§2.4) |
| `make ingest` | gera os documentos de referência e ingere no Qdrant (§2.5) |
| `make seed` | seed pelo host (`python utils/seed_clickhouse.py`) |
| `make data` | gera o Parquet em `data/dataset/` (gitignored) com a seed padrão |
| `make setup` | instala o pacote + dependências de seed/teste |
| `make run` | app local (`PYTHONPATH=src python -m entrypoints.app`) |
| `make test` / `make test-integration` | unitários (sem Docker) / paridade com ClickHouse (Docker) |
| `make eval` / `make eval-smoke` | subset determinístico de avaliação (oráculo, casos, exemplos dos prompts) |
| `make lint` / `make format` | `ruff check` / `ruff format` em `src tests utils scripts` |
| `make lock` | exporta `uv.lock` → `requirements.lock` (pinado) para o Dockerfile |
| `make build` | só constrói a imagem `cantabria` |

## 3. Seed e verificação

O seed é determinístico e idempotente (pode rodar N vezes): recria as 7
tabelas a partir do DDL versionado em `infra/clickhouse/init/00_schema.sql`
(fonte única de verdade) e insere o dataset gerado com seed fixa — bit a bit
o mesmo resultado a cada execução. Usa a credencial de escrita
(`CLICKHOUSE_SEED_*`); o app só lê (`CLICKHOUSE_USER`, perfil `readonly`).

```bash
docker compose --profile seed run --rm seed                    # no container (padrão)
python utils/seed_clickhouse.py --clientes 10000 --seed 42     # pelo host
python utils/seed_clickhouse.py --export data/dataset          # Parquet opcional p/ inspeção
```

Verificação rápida com o usuário de aplicação (somente leitura):

```bash
docker exec -it cantabria-clickhouse clickhouse-client \
  --user cantabria_app --password "$CLICKHOUSE_PASSWORD" \
  --query "SELECT ds_segm, count() FROM cantabria.fato_cliente GROUP BY ds_segm ORDER BY 2 DESC"
```

Ou `make preflight`, que conta as linhas de cada tabela e confere config,
`.env`, serviços e o endpoint do LLM.

### 3.1. Decisões do ClickHouse (`infra/clickhouse/`)

| Decisão | Por quê |
|---|---|
| Imagem **pinada** `clickhouse-server:24.8` | Reprodutibilidade — nunca `latest`. |
| Portas publicadas só em `127.0.0.1` | O banco não fica exposto à rede local. |
| **Dois usuários** (`cantabria_app`, `cantabria_seed`) | Menor privilégio: runtime só lê; escrita isolada no seed. |
| Acesso do app pelo **perfil** `readonly=1` | Usuários de `users.xml` não aceitam `GRANT` SQL (storage `users_xml` é read-only); o perfil é o controle de acesso. |
| `default` restrito a loopback | Não aceita conexão remota; senha própria. |
| Senhas via `from_env` | Nenhum segredo no XML versionado; `.env` fora do git. |
| `MergeTree` + `LowCardinality` + `Decimal(18,2)` | Coluna eficiente, group-by rápido, precisão monetária. |
| `PARTITION BY toYYYYMM(mes_ref)` nos fatos de rentabilidade | Todo recorte temporal poda partições inteiras. |
| Duas tabelas de rentabilidade, um grão cada | Cliente e contrato×produto nunca se somam. |
| DDL versionado, aplicado pelo seed | O ClickHouse não roda `initdb.d` como o Postgres; um único artefato recria o banco. |

> **Nota sobre grants:** `GRANT SELECT ... TO cantabria_app` falha com
> `ACCESS_STORAGE_READONLY`, porque usuários definidos em `users.d/*.xml` vivem
> num storage de ACL *read-only*. O controle de privilégio do app é o
> **perfil** (`<readonly>1</readonly>`) no XML.

## 4. Demo passo a passo

Com o app aberto em http://localhost:8000, siga nesta ordem:

1. **Métrica simples:** "Qual a rentabilidade do Varejo em 2025?"
   Esperado: um número (Σ margem ÷ Σ saldo) com o período assumido explícito.
2. **Quebra por eixo:** "Quanto cada segmento contribuiu para a queda da
   rentabilidade total?"
   Esperado: decomposição da variação entre segmentos.
3. **Série temporal:** "Como evoluiu a carteira (saldo) mês a mês em 2025?"
   Esperado: série mensal de `outstanding_balance`.
4. **Recusa governada:** "Crie a métrica spread e calcule por gerente."
   Esperado: recusa — métrica fora do catálogo não é inventada.

Se algum passo falhar, veja o §6 antes de reinstalar qualquer coisa.

## 5. Como apontar para a base do cliente

Tudo que varia por cliente mora em arquivos versionados; nenhum exige mudar o
núcleo (`domain/`). A ordem abaixo vai do obrigatório ao opcional.

### 5.1. Banco (obrigatório)

1. Ajuste o DDL em `infra/clickhouse/init/00_schema.sql` — ele é a fonte única
   de verdade; o seed o reaplica a cada execução.
2. Ajuste o gerador/seed (`utils/generate_cantabria_data.py`,
   `utils/seed_clickhouse.py`) ou carregue os dados reais com o usuário
   `cantabria_seed`.
3. Espelhe o mapeamento físico no adapter
   `src/contexts/financial_calculation/adapters/outbound/clickhouse_official_data.py`:
   `DIMENSION_EXPRESSIONS` (eixo → coluna SQL), `VALUE_TRANSLATION`
   (`value_id` → valor gravado), `MEASURE_COLUMNS` (medida → coluna) e os nomes
   de tabelas nos `_compile_*`. Identificadores vêm desses mapas, nunca do
   texto do usuário.
4. Conexão via ambiente: `CLICKHOUSE_HOST/PORT/DB/USER/PASSWORD`
   (aplicação, somente leitura) e `CLICKHOUSE_SEED_USER/PASSWORD` (seed).

### 5.2. Catálogo semântico (obrigatório)

`data/catalogs/semantic_catalog_vN.yaml`. A versão ativa é a de maior número;
arquivos com schema anterior à v2 são tratados como histórico (não compilam).
Para um novo país/locale, copie a v2, troque `locale`, métricas, eixos, valores
e `compatibility`, e suba o número da versão. O contrato dos prompts não muda.

### 5.3. Prompts (obrigatório ao trocar de locale)

- Interpretação: `data/prompts/interpretation/v1/` — `base.md` (contrato
  neutro), `examples.{locale}.md` e `messages.{locale}.md` (superfície
  localizada).
- Insight final: `data/prompts/insight/v3/base.md` — redige em Markdown
  (manchete, pontos, tabela por entidade, ressalvas) sobre o resultado já
  calculado, com taxas sempre em percentual rotulado; nunca recebe dado cru.
- Síntese documental: `data/prompts/documental/v1/base.md` — responde a
  perguntas conceituais usando somente os trechos aprovados, citando os
  documentos pelo título.
- A versão padrão de cada contrato fica em `src/cross_cutting/config.py`
  (`_INTERPRETATION_PROMPT_VERSION`, `_INSIGHT_PROMPT_VERSION`,
  `_DOCUMENTAL_PROMPT_VERSION`) e pode ser sobreposta por `data.*_prompts_dir`
  no `config.yaml` ou por `CANTABRIA_*_PROMPTS_DIR`; `/ready` reporta as versões
  efetivas (`prompt_version: interpretation=v1,insight=v3,documental=v1`).
  Mudar um prompt é criar um novo diretório `vN`, não editar o anterior.

### 5.4. Autorização (obrigatório)

- `data/auth/capabilities.yaml`: mapa `role → {can_use_financial_analysis,
  metrics, axes}`. Acrescentar algo ao catálogo **não** concede acesso sozinho.
- `auth.allowed_domains` no `config.yaml`: domínios Google Workspace aceitos
  (vazio aceita qualquer identidade verificada; sem OAuth, tudo é anônimo).

### 5.5. Onde configurar os caminhos

Bloco `data` do `config.yaml` (tudo opcional; `null` = padrão). Caminhos
relativos resolvem contra o diretório do `config.yaml`:

```yaml
data:
  data_dir: null
  catalogs_dir: null
  interpretation_prompts_dir: null
  insight_prompts_dir: null
  capabilities_file: null
```

Overrides por ambiente (vencem o arquivo, um campo por vez):

| Variável | Campo |
|---|---|
| `CANTABRIA_DATA_DIR` | `data_dir` |
| `CANTABRIA_CATALOGS_DIR` | `catalogs_dir` |
| `CANTABRIA_INTERPRETATION_PROMPTS_DIR` | `interpretation_prompts_dir` |
| `CANTABRIA_INSIGHT_PROMPTS_DIR` | `insight_prompts_dir` |
| `CANTABRIA_CAPABILITIES_FILE` | `capabilities_file` |

A imagem Docker copia `data/` para `/app/data` e já fixa `CANTABRIA_DATA_DIR`.
Num `pip install` fora do checkout, aponte `CANTABRIA_DATA_DIR` para uma cópia
dos dados — o pacote Python não embute `data/`.

## 6. Troubleshooting

| Sintoma | Causa provável | Ação |
|---|---|---|
| `Configuration file not found` | `config.yaml` não existe ou `CONFIG_PATH` errado | `cp config.example.yaml config.yaml`; confira `CONFIG_PATH` no `.env` |
| `Invalid configuration` no startup | chave faltando/estranha (tudo é obrigatório, exceto `data`) | compare com `config.example.yaml` |
| `diretório de catálogos não encontrado` / `Arquivo de prompt não encontrado` | `data/` fora do lugar ou `CANTABRIA_*` errado | confira §5.5; no checkout, deixe vazio |
| `arquivo de capacidades não encontrado` | idem, para `capabilities_file` | idem |
| `docker compose` reclama `defina CLICKHOUSE_PASSWORD no .env` (ou `MINIO_ROOT_*`) | `.env` ausente ou desatualizado — o compose interpola o arquivo inteiro, mesmo para profiles que não subiram | `cp .env.example .env` (ou copie as chaves novas do template) |
| `docker build` falha em `COPY .chainlit/config.toml` | arquivo fora do git (clone antigo) | `git pull`; o `config.toml` é versionado e `git ls-files .chainlit` deve listá-lo |
| App não conecta no ClickHouse | banco fora do ar ou senha divergente | `docker compose ps` (healthy?); senhas do `.env` batem com o container? `make preflight` |
| `seed` termina com `Connection refused` | rodou o seed pelo host com `CLICKHOUSE_HOST=clickhouse` (ou no container com `localhost`) | no host use `localhost`; o serviço `seed` do compose já força `clickhouse` |
| Tabelas com 0 linhas no preflight | seed não rodou ou falhou | `docker compose --profile seed run --rm seed` e leia a saída |
| `ACCESS_STORAGE_READONLY` em GRANT | tentou dar GRANT a usuário de XML | não dê GRANT: o acesso do app é o perfil `readonly` em `users.xml` |
| http://localhost:8000 não abre no container | Chainlit bindou em `127.0.0.1` | `CHAINLIT_HOST=0.0.0.0` (compose/devcontainer já fazem isso) |
| Porta 8000 ocupada | outro serviço na porta | `CHAINLIT_PORT=8001` (e `ports` no compose) |
| Login (Google ou local) falha | `CHAINLIT_AUTH_SECRET` vazio no `.env` com login ligado | gere com `chainlit create-secret`; `make preflight` acusa isso |
| Sem resposta do LLM | `llm.base_url/api_key` errados ou sem rede | `make preflight` (checa `GET {base_url}/models`); veja os logs estruturados no stdout |
| Traces não aparecem no Langfuse | profile `observability` desligado ou `observability.enabled: false` | `make observability`; ligue `enabled` e confira host/chaves no `config.yaml` |
| Porta `8123`/`9000` já em uso | resto de um stack antigo (`infra/docker-compose.yml` ou `infrastructure/compose.yaml`, ambos removidos) | `docker ps` → `docker rm -f` dos containers antigos; depois `make stack` |

## 7. Devcontainer

Abriu na devcontainer: `post-create.sh` instala Python 3.12 e o tooling JS (o
login do `opencode` só roda com terminal interativo — em automação ele é
pulado). Portas publicadas: `8000` (Chainlit) e `4096` (OpenChamber), e
`CHAINLIT_HOST=0.0.0.0` já vem setado. Suba o banco do host com
`docker compose up -d --wait clickhouse` e rode `make seed` + `make run`.

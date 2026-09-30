# Configuração do ClickHouse — infraestrutura dos dados oficiais

Documento de definição de infraestrutura para o agente de código implementar. Descreve **como o ClickHouse é configurado, protegido, modelado e integrado** ao Cantábria. Companheiro do `base-ficticia.md` (que define o formato das bases e o gerador de dados fictícios).

> Os artefatos implementados (compose, DDL, `.env.example`, adapter) devem viver em `infra/` e `src/`; este doc é a especificação.

---

## 1. Papel do ClickHouse

O ClickHouse é o **armazém dos dados oficiais** do Cantábria (clientes, produtos, contratos, rentabilidade) — conforme o `architecture/flow.md`, é a base que o **motor determinístico** de `financial_calculation` consulta para executar filtros, joins e agregações governadas.

Regra da arquitetura hexagonal: a aplicação **nunca** acessa o ClickHouse diretamente. Só através de um **Port** (interface no core) e um **Adapter** (implementação na infraestrutura), conectados pelo bootstrapper. O LLM **não** tem acesso ao banco.

---

## 2. Alinhamento com os requisitos do projeto

| Requisito | Como esta configuração atende |
|---|---|
| **Reprodutível** | Tudo em `docker-compose` + scripts versionados; qualquer avaliador roda `docker compose up` e um script de seed determinístico. |
| **Seguro** | Credenciais em `.env` (fora do git), usuário de aplicação com permissões mínimas, usuário default protegido. |
| **Eficiente** | Tabelas `MergeTree` com chave de ordenação, partição por mês nos fatos e `LowCardinality` nos textos repetidos. |
| **Escalável** | Compose estruturado (rede/volumes nomeados) pronto para receber Mongo/MinIO/Qdrant e, se preciso, evoluir o CH. |
| **Propósito** | Fonte de dados oficiais isolada atrás de um adapter, consultada deterministicamente. |

---

## 3. Deploy (Docker)

- **Orquestração:** `docker-compose`, **1 nó** de ClickHouse (suficiente para o MVP).
- **Escopo agora:** **somente o ClickHouse**, mas o compose já nasce **extensível** — rede nomeada (ex.: `cantabria-net`), convenção de volumes e um bloco comentado com os próximos serviços (MongoDB, MinIO, Qdrant). Não subir serviços não usados.
- **Imagem:** `PROPOSTA` fixar uma versão LTS estável (ex.: `clickhouse/clickhouse-server:24.8`) — nunca `latest`, para reprodutibilidade.
- **Portas:** `8123` (HTTP — usada pelo client `clickhouse-connect`) e `9000` (protocolo nativo).
- **Persistência:** volume nomeado para os dados (ex.: `clickhouse-data` em `/var/lib/clickhouse`) e, opcionalmente, logs. Os dados sobrevivem a restart.
- **Localização dos artefatos:** o serviço `clickhouse` vive no `compose.yaml` da raiz (profile `core`, ADR 0008); a configuração montada (config.d, users.d) e o DDL ficam em `infra/clickhouse/`.

---

## 4. Segurança e credenciais

- **`.env` não versionado** (entra no `.gitignore`); versionar um **`.env.example`** com as chaves sem valores reais.
- Variáveis: `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_DB`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`.
- **Usuário de aplicação** dedicado (ex.: `cantabria_app`) com **grants mínimos** apenas no database `cantabria` (SELECT para o motor; INSERT/DDL restritos ao processo de seed).
- Usuário `default` do ClickHouse com **senha** (não deixar aberto), criado via variáveis de ambiente da imagem.
- O adapter recebe as credenciais **injetadas pelo bootstrapper** a partir do ambiente — nada hardcoded.

---

## 5. Banco e modelagem física

- **Database:** `cantabria`.
- **Engine:** `MergeTree` em todas as tabelas.
- **Tipos:** `LowCardinality(String)` para textos de baixa cardinalidade (segmento, produto, `tp_pess`); `Decimal(18,2)` para valores em R$ e para os **scores crus** (`principalidade_score`, `vinculacao_score`); `UUID` para a chave técnica de cliente; `Date` para datas; `String` para ids e PII.

### DDL de referência

O DDL vigente é o de `data/base-ficticia.md §3.3`, materializado em `infra/clickhouse/init/00_schema.sql` (fonte única de verdade). São **oito tabelas**: três de dimensão/conformidade (`fato_cliente`, `dim_segmento`, `dim_produto`), quatro de fato (`fato_contratos`, `fato_contrato_produtos`, `fato_rentabilidade_cliente`, `fato_rentabilidade_contrato_produto`) e uma de **indicadores macro de mercado** (`mercado_indicadores`, grão mensal, ver ADR 0013).

```sql
CREATE DATABASE IF NOT EXISTS cantabria;

-- Dimensão: um cliente. Chave técnica = UUID v4; PII só no dado; scores crus.
CREATE TABLE cantabria.fato_cliente (
    id_cliente             UUID,
    cpf_cnpj               String,
    nm_cliente             String,
    ds_email               String,
    nr_telefone            String,
    tp_pess                LowCardinality(String),
    ds_segm_agrup          LowCardinality(String),
    ds_segm                LowCardinality(String),
    ds_subsegm_agrup       LowCardinality(String),
    ds_subsegm             LowCardinality(String),
    principalidade_score   Decimal(18,2),
    vinculacao_score       Decimal(18,2)
) ENGINE = MergeTree ORDER BY id_cliente;

-- Dimensão: catálogo das 13 combinações válidas de segmento (conformidade).
CREATE TABLE cantabria.dim_segmento (
    id_segmento            String,
    tp_pess                LowCardinality(String),
    ds_segm_agrup          LowCardinality(String),
    ds_segm                LowCardinality(String),
    ds_subsegm_agrup       LowCardinality(String),
    ds_subsegm             LowCardinality(String)
) ENGINE = MergeTree ORDER BY id_segmento;

-- Dimensão: catálogo estático de produtos (subproduto).
CREATE TABLE cantabria.dim_produto (
    id_produto     String,
    cd_produto     String,
    ds_grupo_prod  LowCardinality(String),
    ds_produto     LowCardinality(String),
    ds_subproduto  LowCardinality(String)
) ENGINE = MergeTree ORDER BY id_produto;

-- Fato: um contrato (cabeçalho). Sem produto.
CREATE TABLE cantabria.fato_contratos (
    id_contrato         String,
    id_cliente          UUID,
    dt_ini_contrato     Date,
    dt_encerramento     Nullable(Date)
) ENGINE = MergeTree ORDER BY (id_cliente, id_contrato);

-- Fato: composição do contrato. Grão = contrato x produto.
CREATE TABLE cantabria.fato_contrato_produtos (
    id_contrato  String,
    id_produto   String
) ENGINE = MergeTree ORDER BY (id_contrato, id_produto);

-- Fato: rentabilidade do cliente. Grão = cliente x mês.
CREATE TABLE cantabria.fato_rentabilidade_cliente (
    id_cliente     UUID,
    mes_ref        Date,
    vl_saldo       Decimal(18,2),
    vl_margem      Decimal(18,2),
    data_medicao   Date
) ENGINE = MergeTree
  PARTITION BY toYYYYMM(mes_ref)
  ORDER BY (mes_ref, id_cliente);

-- Fato: rentabilidade do contrato e do produto. Grão = contrato x produto x mês.
CREATE TABLE cantabria.fato_rentabilidade_contrato_produto (
    id_contrato    String,
    id_produto     String,
    mes_ref        Date,
    vl_saldo       Decimal(18,2),
    vl_margem      Decimal(18,2),
    data_medicao   Date
) ENGINE = MergeTree
  PARTITION BY toYYYYMM(mes_ref)
  ORDER BY (mes_ref, id_contrato, id_produto);
```

Justificativa das escolhas:

- As duas tabelas de rentabilidade são **particionadas por mês** (`toYYYYMM(mes_ref)`): consultas por período podam partições — o padrão dos UCs (recortes temporais). O `ORDER BY` favorece varreduras por período e o join pelo grão.
- **Duas tabelas por grão** (cliente × mês e contrato × produto × mês): a soma dentro de uma tabela é sempre segura; escolher a errada quebra a análise. Cliente **e** contrato×produto medem o mesmo negócio — **nunca** somar as duas.
- Dimensões e `fato_contratos` são pequenas → sem partição; `ORDER BY` escolhido para os joins mais comuns (por cliente/contrato/produto).
- `LowCardinality` reduz muito o armazenamento e acelera group-by nas dimensões repetidas.

> Nota: ClickHouse não impõe FK/unicidade. A integridade referencial (ex.: `id_contrato` existir em `fato_contratos`, `id_cliente` existir em `fato_cliente`) é garantida pelo **gerador**, não pelo banco.

---

## 6. Integração com a aplicação (hexagonal)

- **Port** no core (`financial_calculation`): uma interface para leitura dos dados oficiais (ex.: `OfficialDataRepository` / porta de consulta usada pelas calculation families).
- **Adapter** em `src/cantabria/infraestructure`: implementa o Port usando o client **`clickhouse-connect`** (HTTP, oficial).
- **Bootstrapper** conecta o Adapter ao Port e injeta a config (host/porta/db/credenciais) vinda do ambiente.
- **Dependências** (`pyproject.toml`):
  - runtime (app): `clickhouse-connect`.
  - tooling (gerador em `utils/`): `faker`, `clickhouse-connect` (e `pyarrow`/`pandas` se for exportar Parquet opcional).

---

## 7. Inicialização e seed

Ordem determinística e idempotente:

1. `docker compose up` sobe o ClickHouse (com volume persistente).
2. **Um script único de setup** (opção B, escolhida) cria as tabelas (DDL) **e** carrega os dados numa só execução. Simples e repetível.
3. Esse script usa o gerador em `utils/` (seed fixa, `base-ficticia.md §4`) e insere via `clickhouse-connect`. Idempotente: recria/limpa as tabelas antes de inserir.
4. A tabela `mercado_indicadores` é populada do **cache versionado** `data/market/bacen_sgs.csv` (séries do BACEN/SGS, ver ADR 0013) — sem rede no seed. Para rebuscar as séries com rede: `python utils/ingest_market_data.py --force`.
5. (Opcional) export Parquet para inspeção.

---

## 8. Reprodutibilidade (passo a passo para o avaliador)

`PROPOSTA` documentar no README:

1. `cp .env.example .env` e ajustar se quiser.
2. `docker compose up -d` (sobe o ClickHouse).
3. Rodar o script de seed (`utils/`) para criar schema + popular os dados.
4. A aplicação lê tudo via o adapter ClickHouse.

Determinismo garantido pela **imagem pinada** + **seed fixa** + **scripts versionados**.

---

## 9. Decisões travadas

- Doc de infra dedicado (este arquivo).
- Deploy via `docker-compose`, 1 nó, **só ClickHouse agora**, compose **extensível** para os demais serviços.
- Modelagem **otimizada**: `MergeTree` + `ORDER BY` + partição por mês nos fatos + `LowCardinality`/`Decimal`/`Date`.
- Credenciais em `.env` **não versionado** + **usuário de aplicação** com permissões mínimas.
- Acesso somente via **Port + Adapter** (`clickhouse-connect`); dados oficiais isolados do LLM.
- Criação das tabelas + carga via **um script único de setup** (opção B), determinístico e repetível.

---

## 10. Itens de afinação (defaults adotados)

1. Versão exata da imagem do ClickHouse (sugerido LTS `24.8`).
2. Precisão dos `Decimal` (sugerido `Decimal(18,2)`).
3. Chaves de `ORDER BY` finais por tabela (ajustar conforme os padrões de consulta reais).
4. Caminho exato dos artefatos em `infra/`.

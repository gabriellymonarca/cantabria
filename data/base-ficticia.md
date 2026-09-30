# Base fictícia do Cantábria — formato das bases e geração

Documento de definição da **fonte de dados fictícia** do Cantábria. Define o
**formato das bases** (colunas, grão, chaves, papel), **como alterar as bases
atuais** e **como construir o gerador de dados aleatórios**. Companheiro do
`data/clickhouse.md` (infra) e do `data/data-generation/explicacao.md` (geração
vigente); este documento é a referência nova que os substitui em formato.

> Princípio herdado de `explicacao.md` §1: o Cantábria **recebe números
> oficiais** das áreas de negócio. Ele não recalcula número oficial — apenas
> agrega deterministicamente. Consequência: a fonte entrega **R$ somáveis**
> (`vl_margem`, `vl_saldo`) no grão mais fino; a **taxa é derivada**.

---

## 1. Objetivo e status

- **O que é fonte fictícia:** dados gerados por script determinístico (seed
  fixa) para o MVP, gravados no ClickHouse.
- **O que é dado oficial:** `vl_saldo` e `vl_margem` (R$), e os atributos de
  cliente/produto enviados pelas áreas. A taxa de rentabilidade **não** é
  oficial enquanto número — é derivada.
- **Relação com os demais documentos:**
  - `data/clickhouse.md` — como o ClickHouse é configurado e protegido.
  - `data/data-generation/explicacao.md` — definição anterior (4 tabelas).
  - **este documento** — formato-alvo das bases e guia do gerador.

### 1.1 Os quatro UCs não definem o limite

Como em `definitions.md`, o Cantábria é de **orquestração genérica**: a fonte é
desenhada para a combinação livre de **métricas × dimensões × análises ×
períodos × amostras**, não para quatro perguntas. A estrutura precisa garantir
**cobertura** (linhas em cada célula), **variabilidade** (dispersão entre
grupos) e **ruído** (sem valores idênticos artificiais).

---

## 2. As bases (formato)

Seis bases. Dimensões de conformidade: `fato_cliente`, `dim_produto` e
`dim_segmento` (as duas últimas catálogos estáticos) e as de medida:
`fato_contratos` (cabeçalho), `fato_contrato_produtos` (itens) e as tabelas de
rentabilidade. A rentabilidade tem **duas tabelas por grão**:
`fato_rentabilidade_cliente` e `fato_rentabilidade_contrato_produto`.

Nomes lógicos usados aqui; o DDL físico segue o padrão da base real
(`id_`, `ds_`, `vl_`, `dt_`, `nr_`, `tp_`, `cd_`).

### 2.1 `fato_cliente` — dimensão

Grão: **um cliente**. Um cliente tem **N contratos**; a base de clientes **não**
carrega contrato.

| Coluna | Tipo | Papel |
|---|---|---|
| `id_cliente` | UUID | **chave técnica** — UUID v4, sem significado de negócio |
| `cpf_cnpj` | String | CPF (PF) ou CNPJ (PJ) — **PII** / identificador de negócio |
| `nm_cliente` | String | cosmético / **PII** (Faker) |
| `ds_email` | String | cosmético / **PII** (Faker) |
| `nr_telefone` | String | cosmético / **PII** (Faker) |
| `tp_pess` | LowCardinality(String) | `F` / `J` |
| `ds_segm_agrup` | LowCardinality(String) | hierarquia de segmento |
| `ds_segm` | LowCardinality(String) | hierarquia de segmento |
| `ds_subsegm_agrup` | LowCardinality(String) | hierarquia de segmento |
| `ds_subsegm` | LowCardinality(String) | hierarquia de segmento |
| `principalidade_score` | Decimal(18,2) | **score cru** da área |
| `vinculacao_score` | Decimal(18,2) | **score cru** da área |

Regras:

- O **id do cliente é um UUID v4** (`id_cliente`), chave técnica de join — **nunca**
  eixo de agrupamento (`execute_calculation` 2.4). O `cpf_cnpj` é o identificador
  de negócio e fica como coluna, **não** como chave de join.
- `cpf_cnpj`, `nm_cliente`, `ds_email` e `nr_telefone` são **PII**: não
  aparecem em resultado nem viram grão (recusa G55/G56).
- **Scores entram crus.** O eixo governado (`alta/media/baixa`) é uma **regra de
  faixa** aplicada no catálogo/adapter (§5.1). Sem a faixa, um score contínuo
  não é agrupável.
- A classificação de segmento deve ser uma das combinações válidas do `.xlsm`,
  coerente com `tp_pess`.
- Simplificação do MVP: segmento e scores são **fixos por cliente** (sem
  histórico mês a mês). Costura futura: promover a `cliente × mês` sem mudar os
  contratos das families.

### 2.2 `fato_contratos` — fato (cabeçalho)

Grão: **um contrato**. Não traz produto — o produto vive em 2.3.

| Coluna | Tipo | Papel |
|---|---|---|
| `id_cliente` | UUID | FK → `fato_cliente` (vínculo por UUID) |
| `id_contrato` | String | chave (`CTR_00000001`) |
| `data_ini` | Date | abertura |
| `data_fim` | Date | `vigente` = ativo |

Regras:

- `contract_count` = `COUNT(DISTINCT id_contrato)` sobre contratos ativos na data.
- "Ativo em uma data de referência" = `data_ini_contrato ≤ ref` E
  (`data_encerramento` é `NULL` OU `data_encerramento ≥ ref`).
- As datas existem para a **vigência** (stock). Medir originação ou encerramento
  no período seria **fluxo**, fora de escopo.
- Um contrato pode ter **1..N produtos** (§2.3).

### 2.3 `fato_contrato_produtos` — fato (itens do contrato)

Grão: **um contrato × produto**. É a composição do contrato.

| Coluna | Tipo | Papel |
|---|---|---|
| `id_contrato` | String | FK → `fato_contratos` |
| `id_produto` | String | FK → catálogo de produto |

Regras:

- O catálogo `dim_produto` (29 linhas estáticas do `.xlsm`, ver §4.2) permanece
  a **fonte única da hierarquia** `ds_grupo_prod/ds_produto/ds_subproduto`.
  Alternativa documentada (§6): denormalizar a hierarquia dentro do próprio
  fato — aceitável em ClickHouse, mas duplica texto e reescreve história ao
  renomear produto.
- Simplificação do MVP: a composição de produtos de um contrato é **fixa por
  contrato**. Se evoluir no tempo, a base vira SCD com vigência e a
  rentabilidade referencia o item vigente.
- Contagem por produto conta **itens**; `contract_count` conta **contratos**.
  São números diferentes quando um contrato tem mais de um produto — o nome da
  métrica precisa dizer qual usa.

### 2.4 `dim_segmento` — dimensão (catálogo de conformidade)

Catálogo estático das **13 combinações válidas** de segmento (aba `segmentos`
do `.xlsm`). Assim como `dim_produto` é a fonte única da hierarquia de produto,
`dim_segmento` é a fonte única da hierarquia de segmento.

| Coluna | Tipo | Papel |
|---|---|---|
| `id_segmento` | String | chave (`SEG_01`) |
| `tp_pess` | LowCardinality(String) | `F` / `J` |
| `ds_segm_agrup` | LowCardinality(String) | nível 1 da hierarquia |
| `ds_segm` | LowCardinality(String) | nível 2 |
| `ds_subsegm_agrup` | LowCardinality(String) | nível 3 |
| `ds_subsegm` | LowCardinality(String) | nível 4 |

Regras:

- **Não muda as perguntas.** As hierarquias de segmento continuam sendo
  resolvidas pelos `subjects` do plano; isto é catálogo de conformidade, como
  `dim_produto`.
- **Duas opções de uso (a decidir):**
  - **(a) Validação/conformidade** — `fato_cliente` continua guardando as quatro
    colunas `ds_*`, e `dim_segmento` é a allowlist que o gerador/validador usa
    para garantir coerência (4 strings pertenciam à mesma combinação válida).
  - **(b) Normalização** — `fato_cliente` guarda apenas `id_segmento`; os `ds_*`
    vêm daqui por join. Reduz texto, mas exige um join e um salto de resolução.
- **Recomendação:** (a) no MVP — mantém o modelo atual (sem novo join no caminho
  quente) e ganha a coerência verificável que hoje só existe no `.xlsm`. Migrar
  para (b) depois é trocar colunas por FK, sem tocar nos planos.

### 2.5 Fato de rentabilidade — duas tabelas por grão

A rentabilidade é medida em **dois grãos de detalhe**, em **duas tabelas
separadas** (evita a soma acidental entre níveis):

- **`fato_rentabilidade_cliente`** — grão **cliente × mês**. Mede a
  rentabilidade do cliente; as **hierarquias** de cliente (segmento,
  subsegmento, principalidade, vinculação) são derivadas por agrupamento.
- **`fato_rentabilidade_contrato_produto`** — grão **contrato × produto × mês**.
  Mede a rentabilidade do **contrato** e do **produto**; as hierarquias de
  produto (`grupo`, `produto`, `subproduto`) e o nível **contrato** são
  derivadas por agrupamento.

As duas tabelas têm o mesmo formato de medidas; só muda a chave e a
possibilidade de roll-up.

#### 2.5.1 `fato_rentabilidade_cliente`

| Coluna | Tipo | Papel |
|---|---|---|
| `id_cliente` | UUID | **chave** → `fato_cliente` |
| `mes_ref` | Date | **período de referência** (fim do mês) |
| `vl_saldo` | Decimal(18,2) | saldo do cliente no mês (R$) — oficial |
| `vl_margem` | Decimal(18,2) | margem do cliente **já anualizada** (R$/ano) — oficial |
| `data_medicao` | Date | **linhagem**: quando a linha foi medida/carregada |

#### 2.5.2 `fato_rentabilidade_contrato_produto`

| Coluna | Tipo | Papel |
|---|---|---|
| `id_contrato` | String | **chave** (parte 1) → `fato_contratos` |
| `id_produto` | String | **chave** (parte 2) → `dim_produto` |
| `mes_ref` | Date | **período de referência** (fim do mês) |
| `vl_saldo` | Decimal(18,2) | saldo do item no mês (R$) — oficial |
| `vl_margem` | Decimal(18,2) | margem do item **já anualizada** (R$/ano) — oficial |
| `data_medicao` | Date | **linhagem**: quando a linha foi medida/carregada |

Regras comuns:

- **Não há coluna de taxa.** Rentabilidade = `Σ vl_margem ÷ Σ vl_saldo`.
- **Cada tabela tem um grão único** — não há mistura de níveis, então `SUM`
  dentro de uma tabela é seguro.
- **Não somar as duas tabelas.** Cliente **e** contrato×produto contêm medidas
  do mesmo negócio; somá-las conta o valor duas vezes. A escolha da tabela é
  governada pelo que a pergunta pede:
  - cliente e **hierarquias de cliente** → `fato_rentabilidade_cliente`;
  - produto e **hierarquias de produto** → `fato_rentabilidade_contrato_produto`;
  - **contrato** → `fato_rentabilidade_contrato_produto` agrupado por
    `id_contrato`.
- **Hierarquia de cliente não se obtém da tabela de produto por soma de taxas.**
  Para "rentabilidade por segmento", agrupa-se `fato_rentabilidade_cliente`
  pelo segmento — nunca se recombinam os itens.
- **Hierarquia de produto** sai da tabela contrato×produto: agrupa-se por
  `ds_grupo_prod/ds_produto/ds_subproduto` (via `dim_produto`).
- `data_medicao` é **bitemporal**, não analítico: só `mes_ref` participa de
  plano, série ou recorte.
- **A divisão é a última operação.** Com grão trimestral/anual, re-derive no
  grão: `Σmargem(n meses) ÷ Σsaldo(n meses)` — **nunca** a média das taxas
  mensais.
- **`vl_saldo` não soma entre meses.** É estoque: R$ 200 parados por 3 meses
  continuam R$ 200.
- **`vl_margem` já é anual**: `vl_margem ÷ vl_saldo` sai como taxa anual, sem
  `×12`.
- **Coerência**: o `id_cliente`/`id_contrato`/`id_produto` precisa existir nas
  bases correspondentes e o cliente/contrato do item deve bater com
  `fato_contratos`. O gerador deriva, não sorteia.

---

## 3. Como alterar as bases atuais

As bases atuais vivem em `infra/clickhouse/init/00_schema.sql` (4 tabelas). A
mudança é pequena no banco e relevante no motor/catálogo.

### 3.1 De → para

| Base atual | Base nova | Mudança |
|---|---|---|
| `dim_cliente` | `fato_cliente` | `vinculacao`/`principalidade` (**texto**) → `vinculacao_score`/`principalidade_score` (**Decimal, cru**) |
| — | `fato_contrato_produtos` | **nova**: tira `id_produto` de `fato_contrato` e expande os itens |
| `fato_contrato` | `fato_contratos` | passa a ser **cabeçalho**: perde `id_produto` |
| `fato_rentabilidade` | duas tabelas por grão | substituída por `fato_rentabilidade_cliente` (cliente×mês) e `fato_rentabilidade_contrato_produto` (contrato×produto×mês); ambas com `data_medicao` |
| `dim_produto` | `dim_produto` | **inalterada** (catálogo estático) |
| — | `dim_segmento` | **nova**: catálogo das 13 combinações válidas de segmento (conformidade) |
| — | `fato_rentabilidade_cliente` | **nova**: grão cliente × mês |
| — | `fato_rentabilidade_contrato_produto` | **nova**: grão contrato × produto × mês |

### 3.2 DDL — antes

```sql
CREATE TABLE cantabria.dim_cliente (
    id_cliente        String,
    nr_cpf_cnpj       String,
    nm_cliente        String,
    ds_email          String,
    nr_telefone       String,
    vl_renda          Decimal(18,2),
    tp_pess           LowCardinality(String),
    ds_segm_agrup     LowCardinality(String),
    ds_segm           LowCardinality(String),
    ds_subsegm_agrup  LowCardinality(String),
    ds_subsegm        LowCardinality(String),
    vinculacao        LowCardinality(String),
    principalidade    LowCardinality(String)
) ENGINE = MergeTree ORDER BY id_cliente;

CREATE TABLE cantabria.fato_contrato (
    id_contrato  String,
    id_cliente   String,
    id_produto   String,
    dt_inicio    Date,
    dt_fim       Nullable(Date)
) ENGINE = MergeTree ORDER BY (id_cliente, id_produto, id_contrato);

CREATE TABLE cantabria.fato_rentabilidade (
    id_contrato  String,
    mes_ref      Date,
    vl_saldo     Decimal(18,2),
    vl_margem    Decimal(18,2)
) ENGINE = MergeTree
  PARTITION BY toYYYYMM(mes_ref)
  ORDER BY (mes_ref, id_contrato);
```

### 3.3 DDL — depois

```sql
-- Dimensão: um cliente. Chave técnica = UUID v4. CPF/CNPJ e demais PII
-- (nome/email/telefone) ficam no dado, nunca expostas. Scores crus; a faixa
-- governada é derivada no adapter.
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
-- vl_margem já anualizada; taxa derivada; data_medicao é linhagem.
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
-- O nível contrato é esse grão agrupado por id_contrato.
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

Notas de infraestrutura:

- As duas tabelas são **particionadas por `toYYYYMM(mes_ref)`** — recortes
  temporais podam partições.
- Duas tabelas de fato, um grão cada: a soma dentro de uma tabela é sempre
  segura. A escolha da tabela é governada pela pergunta (§2.4).
- O ClickHouse não impõe FK/unicidade: a integridade é garantida pelo gerador.

### 3.4 Impacto no motor e no catálogo

| Item | Antes | Depois |
|---|---|---|
| `contract_count` | `COUNT(DISTINCT id_contrato)` em `fato_contrato` | idem em `fato_contratos` (cabeçalho) |
| `customer_count` | `COUNT(DISTINCT id_cliente)` via contrato | `COUNT(DISTINCT id_cliente)` via `fato_contratos` |
| `outstanding_balance` | `Σ vl_saldo` em `fato_rentabilidade` (contrato×mês) | `Σ vl_saldo` na tabela do grão pedido |
| `profitability` | `Σ vl_margem ÷ Σ vl_saldo` | mesma fórmula, na tabela do grão pedido |
| rentabilidade do **cliente** | roll-up dos contratos | `fato_rentabilidade_cliente` |
| rentabilidade por **hierarquia de cliente** | roll-up | `fato_rentabilidade_cliente` agrupada por segmento/subsegmento/etc. |
| rentabilidade do **contrato** | grão contrato×mês | `fato_rentabilidade_contrato_produto` agrupada por `id_contrato` |
| rentabilidade do **produto** | não existia | `fato_rentabilidade_contrato_produto` (grão item) |
| rentabilidade por **hierarquia de produto** | não existia | idem, agrupada por grupo/produto/subproduto |
| vinculação/principalidade | colunas categóricas em `dim_cliente` | derivadas de `*_score` por faixa governada |

#### Mapa `subject.type` → tabela de rentabilidade

O binding físico é **determinístico**: o adapter lê o `type` de cada `Subject` do
plano e escolhe a tabela. Não há nível no plano.

| `subject.type` do eixo pedido | Tabela | Grão de leitura |
|---|---|---|
| `customer_segmentation` | `fato_rentabilidade_cliente` | cliente × mês |
| `customer_relationship` | `fato_rentabilidade_cliente` | cliente × mês |
| `customer_principality` | `fato_rentabilidade_cliente` | cliente × mês |
| `product` | `fato_rentabilidade_contrato_produto` | contrato × produto × mês |
| `total` | `fato_rentabilidade_cliente` | cliente × mês |
| **contrato** (não é `subject`; eixo implícito) | `fato_rentabilidade_contrato_produto` | agrupado por `id_contrato` |

Regras do mapa:

- **Todo `type` de cliente resolvido em `fato_rentabilidade_cliente`**, porque o
  grão cliente já carrega segmento/vinculação/principalidade via join com
  `fato_cliente`.
- **`total`** (sem quebra) usa `fato_rentabilidade_cliente`: é a série do
  portfólio no nível do cliente, independente de produto. Se o plano combinar
  `total` **com** um `subject` de produto, vale a regra de produto.
- **Eixo de produto** só existe em `fato_rentabilidade_contrato_produto`.
- **Contrato** não é `subject` do catálogo; quando a pergunta é por contrato, a
  leitura é a tabela de produto agrupada por `id_contrato`.
- **Planos com mais de um `subject`:** a tabela é a do `type` **de produto** se
  houver algum eixo de produto (é a tabela mais fina e contém `id_contrato`);
  caso contrário, `fato_rentabilidade_cliente`. Cruzamentos cliente × produto
  são o único caso que combina as duas — via contrato, nunca por soma direta.

Caminho de join governado:

```
fato_rentabilidade_cliente.id_cliente            → fato_cliente.id_cliente
fato_rentabilidade_contrato_produto.id_contrato  → fato_contratos.id_contrato
fato_rentabilidade_contrato_produto.id_produto   → dim_produto.id_produto
```

> Cliente **e** contrato×produto medem o mesmo negócio: **nunca** somar as duas
> tabelas. Cada pergunta escolhe uma tabela; dentro dela, `Σ margem ÷ Σ saldo`
> é seguro.

### 3.5 Impacto no catálogo e nos casos

- **Eixos** (`semantic_catalog_v1.yaml`): `customer_relationship.relationship_depth`
  e `customer_principality.principality_depth` continuam existindo; deixam de
  apontar para coluna de texto e passam a resolver a faixa do score.
- **Contagens**: `contract_count` (contrato) e "contagem de itens por produto"
  são métricas distintas. Se o produto pedido for "quantos contratos de Cartão",
  decide-se explicitamente entre contrato×produto.
- **Casos de rentabilidade por produto** (A4, B17, B18) permanecem `OK` — agora
  sustentados pelo grão item, não por suposição de 1 produto por contrato.
- **D35** (rentabilidade média por contrato) continua `GAP`: razão entre
  métricas ainda não existe no contrato.

---

## 4. Guia do gerador de dados aleatórios

Script em `utils/` (fora de `src/`), determinístico e idempotente: recria as
tabelas (DDL) e insere. Export Parquet é opcional.

### 4.1 Parâmetros gerais

- **Seed fixa** (ex.: `42`) — reprodutibilidade bit a bit.
- **Janela:** 24 meses, `2024-09-30` a `2026-08-31` (fins de mês), ancorada em
  `2026-08`.
- **Volumes-alvo:** ~10.000 clientes; ~25–30 mil contratos; 1..N itens por
  contrato; ~500–900 mil linhas em `fato_rentabilidade_contrato_produto` e
  ~200–240 mil em `fato_rentabilidade_cliente`.
- **Esquemas de id:** cliente = **UUID v4** (`id_cliente`); CPF/CNPJ como coluna;
  `PROD_001`, `CTR_00000001`.
- **PII fictícia via Faker (`pt_BR`):** `cpf_cnpj`, `nm_cliente` (nome PF,
  razão social PJ), `ds_email`, `nr_telefone`.

### 4.2 Leitura das hierarquias oficiais (`produtos_segmentos.xlsm`)

| Aba | Conteúdo | Uso |
|---|---|---|
| `segmentos` | 13 combinações válidas de `tp_pess + ds_segm_agrup + ds_segm + ds_subsegm_agrup + ds_subsegm` | popula `dim_segmento` e valida `fato_cliente` |
| `produtos` | 29 combinações de `ds_grupo_prod + ds_produto + ds_subproduto` | popula `dim_produto` |
| `matriz_seg_prod` | allowlist segmento × produto | governa quais produtos um cliente pode ter |

### 4.3 Geração de clientes

1. Sorteia `tp_pess` e `ds_segm` conforme distribuição da base real (Varejo PF
   ~62%, Varejo PJ ~21%, Rural ~9%, Corporate ~5%, Private ~2%, CIB ~1%),
   garantindo combinação de segmento válida para o `tp_pess`.
2. Gera a **PII** com Faker: `cpf_cnpj` (CPF p/ `F`, CNPJ p/ `J`),
   `nm_cliente` (nome PF, razão social PJ), `ds_email`, `nr_telefone`.
3. Gera o **`id_cliente`** como **UUID v4** (chave técnica; determinístico a
   partir da seed fixa).
4. Gera **scores crus** (`principalidade_score`, `vinculacao_score`) — ver §5.1
   para a faixa derivada.
5. Grava `dim_segmento` **uma vez** a partir da aba `segmentos`; as 4 colunas
   `ds_*` de cada cliente devem corresponder a uma linha dela (conformidade).

Tendências a embutir (correlações plausíveis, **não** vieses para um UC):

- segmentos premium (Private/Corporate/CIB) com scores mais altos;
- scores mais altos somando incremento à taxa-alvo (ver §4.6).

### 4.4 Geração de contratos e itens

1. Nº de contratos por cliente/segmento (default, sempre ≥ 1):
   - Varejo PF ~2 (1–3); Varejo PJ ~3 (1–5); Varejo Rural ~2 (1–3);
   - Corporate Middle ~4 (2–7); Corporate Large ~5 (2–9); Private ~4 (2–7);
     CIB ~6 (3–10).
2. Cada contrato recebe **1..N produtos** (novo parâmetro), amostrados **sem
   repetição** dentro do contrato e apenas da allowlist do segmento.
   Distribuição default sugerida: 1 produto ~70%, 2 produtos ~22%, 3+ ~8%.
3. `dt_ini_contrato` distribuída ao longo/antes da janela; uma fração encerra
   dentro da janela (para haver variação de contratos ativos no tempo).
4. Grava `fato_contratos` (cabeçalho) e `fato_contrato_produtos` (itens).

### 4.5 Geração de rentabilidade (duas tabelas)

Gerar as medidas nas **duas tabelas**, cada uma no seu grão:

- **`fato_rentabilidade_contrato_produto`** (o detalhe): para cada item
  `(id_contrato, id_produto)` e cada mês ativo → saldo-base pela faixa do
  segmento × fator do grupo de produto; random walk suave e positivo;
  `vl_margem = vl_saldo × taxa_alvo + ruído`, com `taxa_alvo` composta por grupo
  de produto + segmento + incremento de score;
- **`fato_rentabilidade_cliente`**: para cada `id_cliente` e cada mês ativo →
  uma linha com margem/saldo próprios do cliente (default: soma dos itens dos
  contratos dele naquele mês, com pequeno ajuste opcional);
- `data_medicao` = data de carga (constante ou levemente posterior a `mes_ref`);
- Contrato e hierarquias de produto **não** ganham linha própria: são o grão
  `contrato × produto` agrupado por `id_contrato` ou pela hierarquia (§4.7).

### 4.6 Magnitudes e tendências (defaults ajustáveis)

- **Saldo por segmento (R$):** Varejo PF 1k–150k; Varejo PJ 10k–2M; Rural
  5k–500k; Corporate Middle 500k–20M; Corporate Large 5M–100M; Private
  500k–30M; CIB 10M–1B.
- **Taxa-alvo por grupo de produto:** Rotativo 15–35%; Parcelado 8–20%;
  Consignado 5–12%; com Garantia 2–8%; Especializado/Transacional/
  Renegociação intermediárias.
- **Incremento de score (p.p. na taxa-alvo):** principalidade baixa +0 /
  media +1,5 / alta +3; vinculação baixa +0 / media +1 / alta +2.
- **Ruído:** gaussiano ~±15% relativo por item/mês antes de virar `vl_margem`.
- **Volumes-alvo (×24 meses):** `fato_rentabilidade_contrato_produto` = itens
  ativos × meses; `fato_rentabilidade_cliente` = clientes ativos × meses.

### 4.7 Regra anti-double-count (invariante do gerador)

- Cada tabela tem **um único grão**. `SUM`/taxa só é feito **dentro de uma
  tabela**; nunca se somam as duas.
- Se o gerador somar `fato_rentabilidade_cliente` com
  `fato_rentabilidade_contrato_produto`, o mesmo negócio é contado duas vezes e
  o erro é **silencioso**. O gerador e o motor não podem produzir esse estado.
- A taxa **nunca** é obtida por média entre grãos nem por soma de taxas: cada
  tabela/grão tem sua própria razão `Σ margem ÷ Σ saldo`.
- Coerência: o `id_cliente` de `fato_rentabilidade_cliente` deve existir em
  `fato_cliente`; o `id_contrato`/`id_produto` de
  `fato_rentabilidade_contrato_produto` deve existir em `fato_contratos` /
  `fato_contrato_produtos`.
- `data_medicao` nunca substitui `mes_ref` como eixo temporal.

---

## 5. Decisões, trade-offs e pendências

### 5.1 Scores crus e faixa governada

- **Decisão:** persistir o score **cru** da área; derivar a faixa
  (`baixa/media/alta`) no catálogo/adapter.
- **Faixas default (ajustáveis):** `alta ≥ 70`, `media 40–69`, `baixa < 40`
  (escala 0–100). A regra é governada, versionada no catálogo.
- **Trade-off:** fidelidade à fonte × necessidade de uma regra explícita. Sem
  a faixa, o score contínuo não serve de eixo.
- **Pendência:** confirmar a escala real do score (0–100? 0–1000?) e se a
  área envia faixa pronta.

### 5.2 Duas tabelas por grão, sem double count

- **Decisão:** duas tabelas de rentabilidade — `fato_rentabilidade_cliente`
  (cliente×mês) e `fato_rentabilidade_contrato_produto` (contrato×produto×mês).
- **Motivo:** medir cliente, contrato e produto sem permitir a soma acidental
  entre níveis. Tabelas separadas por grão tornam a soma **segura por
  construção** dentro de cada uma.
- **Como cada nível é atendido:**
  - cliente → `fato_rentabilidade_cliente`;
  - hierarquias de cliente → idem, agrupada por segmento/subsegmento/etc.;
  - produto e hierarquias → `fato_rentabilidade_contrato_produto`;
  - contrato → idem, agrupada por `id_contrato`.
- **Trade-off:** duas fontes de verdade do mesmo negócio que **não se somam**;
  o consumidor precisa escolher a tabela certa. Em troca, nenhum `SUM` ingênuo
  dá número errado.
- **Consequência:** `profitability`/`outstanding_balance` não têm parâmetro de
  nível no plano; o binding físico (qual tabela) é derivado do `subject.type`
  pelo mapa da §3.4 — determinístico, sem decisão do LLM.

### 5.3 `dim_segmento` como catálogo de conformidade

- **Decisão:** criar `dim_segmento` com as 13 combinações válidas do `.xlsm`,
  espelhando `dim_produto`. No MVP, `fato_cliente` **continua** com as quatro
  colunas `ds_*`; a dim serve de **allowlist/validação** (opção a da §2.4).
- **Motivo:** hoje a coerência da hierarquia de segmento só existe no `.xlsm`;
  nada no banco garante que `ds_subsegm` pertença ao `ds_segm` do cliente. A dim
  torna essa regra verificável, como já é para produto.
- **O que **não** muda:** nenhuma pergunta. As hierarquias de segmento seguem
  saindo dos `subjects`; a dim não entra no caminho de agregação.
- **Alternativa (b):** normalizar (`fato_cliente.id_segmento`) reduz texto, mas
  adiciona join e salto de resolução. Documentada, não adotada no MVP.
- **Pendência:** decidir se um dia a `dim_segmento` passa a ser referenciada por
  `id_segmento` (normalização) e se a `matriz_seg_prod` deve migrar para
  `id_segmento` em vez das 5 strings.

### 5.3 Contrato com 1..N produtos

- **Decisão:** contrato é cabeçalho; produtos são itens em tabela própria.
- **Consequência:** `contract_count` (contrato) ≠ contagem de itens por
  produto. O nome da métrica precisa explicitar qual usa.
- **Trade-off:** mais uma tabela e um join × impossibilidade de representar
  contratos multiproduto sem duplicar o cabeçalho.

### 5.4 Tempo: referência vs. medição

- **Decisão:** `mes_ref` é analítico; `data_medicao` é linhagem.
- **Motivo:** evitar a ambiguidade "agosto de referência ou de medição?".
- **Pendência (futuro):** se a fonte publicar revisões retroativas, definir
  política de versão (manter histórico de `data_medicao` ou sobrescrever).

### 5.5 Simplificações conscientes do MVP

| Simplificação | Motivo | Costura futura |
|---|---|---|
| Segmento e scores fixos por cliente | simplicidade | promover a `cliente × mês` |
| Composição de produtos fixa por contrato | simplicidade | item com vigência (SCD) |
| Sem fluxo (originação/encerramento) | escopo é estoque | nova family + grão de evento |

### 5.6 PII e grão individual

- `cpf_cnpj`, `nm_cliente`, `ds_email` e `nr_telefone` existem no dado
  fictício, mas **não** são eixo, filtro ou campo de resultado. Perguntas por
  cliente individual são recusadas (`governance`).

---

## 6. Alternativas documentadas (não adotadas)

| Alternativa | Prós | Contras | Situação |
|---|---|---|---|
| Embutir `ds_grupo_prod/ds_produto/ds_subproduto` em `fato_contrato_produtos` | menos um join | duplica texto; renomear produto reescreve história | documentada |
| Guardar a taxa (%) nas tabelas de rentabilidade | leitura direta | razão não aditiva; média errada | **rejeitada** |
| Uma única tabela com coluna `nivel` | menos tabelas | exige filtrar nível em toda leitura; soma ingênua erra | **rejeitada** (preferidas duas tabelas) |
| **Duas tabelas por grão** (adotada) | soma segura por construção; mede cliente, contrato e produto | duas fontes que não se somam; escolher a tabela certa | **adotada** (§2.5) |
| `dim_segmento` só para validação (adotada) | coerência da hierarquia sem join | mantém as 4 colunas em `fato_cliente` | **adotada** (§5.3) |
| Normalizar `fato_cliente.id_segmento` | menos texto; FK estável | join e salto de resolução no caminho quente | **não adotada** no MVP (§2.4) |
| Uma única tabela larga (OBT) | menos joins | perde garantia de agregação; dificulta governança | **rejeitada** |

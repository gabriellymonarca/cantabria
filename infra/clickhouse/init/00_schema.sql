-- Schema dos dados oficiais do Cantábria.
-- Referência: data/base-ficticia.md §2 (formato) e §3.3 (DDL).
--
-- Idempotente: recriar do zero a cada execução do seed. O gerador é
-- determinístico (seed fixa), então "DROP + CREATE + INSERT" reproduz
-- sempre o mesmo dataset — não há migração incremental a preservar no MVP.
--
-- Este arquivo é executado com o usuário `cantabria_seed` (DDL + escrita).

CREATE DATABASE IF NOT EXISTS cantabria;

-- Dimensão: um cliente. Chave técnica = UUID v4. CPF/CNPJ e demais PII
-- (nome/email/telefone) ficam no dado, nunca expostas. Scores crus; a faixa
-- governada (alta/media/baixa) é derivada no adapter.
CREATE TABLE IF NOT EXISTS cantabria.fato_cliente (
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
) ENGINE = MergeTree
  ORDER BY id_cliente;

-- Dimensão: catálogo das 13 combinações válidas de segmento (conformidade).
CREATE TABLE IF NOT EXISTS cantabria.dim_segmento (
    id_segmento            String,
    tp_pess                LowCardinality(String),
    ds_segm_agrup          LowCardinality(String),
    ds_segm                LowCardinality(String),
    ds_subsegm_agrup       LowCardinality(String),
    ds_subsegm             LowCardinality(String)
) ENGINE = MergeTree
  ORDER BY id_segmento;

-- Dimensão: catálogo estático de produtos (subproduto).
CREATE TABLE IF NOT EXISTS cantabria.dim_produto (
    id_produto     String,
    cd_produto     String,
    ds_grupo_prod  LowCardinality(String),
    ds_produto     LowCardinality(String),
    ds_subproduto  LowCardinality(String)
) ENGINE = MergeTree
  ORDER BY id_produto;

-- Fato: um contrato (cabeçalho). Sem produto — o produto vive em
-- fato_contrato_produtos.
CREATE TABLE IF NOT EXISTS cantabria.fato_contratos (
    id_contrato         String,
    id_cliente          UUID,
    dt_ini_contrato     Date,
    dt_encerramento     Nullable(Date)
) ENGINE = MergeTree
  ORDER BY (id_cliente, id_contrato);

-- Fato: composição do contrato. Grão = contrato x produto.
CREATE TABLE IF NOT EXISTS cantabria.fato_contrato_produtos (
    id_contrato  String,
    id_produto   String
) ENGINE = MergeTree
  ORDER BY (id_contrato, id_produto);

-- Fato: rentabilidade do cliente. Grão = cliente x mês.
-- vl_margem já anualizada; a taxa é derivada (Σ margem ÷ Σ saldo).
-- data_medicao é linhagem (bitemporal), não eixo analítico.
CREATE TABLE IF NOT EXISTS cantabria.fato_rentabilidade_cliente (
    id_cliente     UUID,
    mes_ref        Date,
    vl_saldo       Decimal(18,2),
    vl_margem      Decimal(18,2),
    data_medicao   Date
) ENGINE = MergeTree
  PARTITION BY toYYYYMM(mes_ref)
  ORDER BY (mes_ref, id_cliente);

-- Fato: rentabilidade do contrato e do produto. Grão = contrato x produto x mês.
-- O nível contrato é este grão agrupado por id_contrato; a hierarquia de
-- produto vem de dim_produto. Nunca somar com fato_rentabilidade_cliente.
CREATE TABLE IF NOT EXISTS cantabria.fato_rentabilidade_contrato_produto (
    id_contrato    String,
    id_produto     String,
    mes_ref        Date,
    vl_saldo       Decimal(18,2),
    vl_margem      Decimal(18,2),
    data_medicao   Date
) ENGINE = MergeTree
  PARTITION BY toYYYYMM(mes_ref)
  ORDER BY (mes_ref, id_contrato, id_produto);

-- Indicadores macro de mercado (BACEN/SGS e IBGE): grão mensal, um indicador
-- por linha. `taxa` é a taxa MENSAL em fração decimal (0.0084 = 0.84% no mês),
-- já convertida do valor publicado; a capitalização composta e a anualização
-- são do motor (shared.aggregation), nunca do banco. `mes_ref` é o primeiro
-- dia do mês publicado; `fonte`/`serie_codigo`/`data_extracao` são linhagem
-- (ver ADR 0013).
CREATE TABLE IF NOT EXISTS cantabria.mercado_indicadores (
    indicador      LowCardinality(String),
    mes_ref        Date,
    taxa           Decimal(18,9),
    fonte          LowCardinality(String),
    serie_codigo   String,
    data_extracao  Date
) ENGINE = MergeTree
  ORDER BY (indicador, mes_ref);

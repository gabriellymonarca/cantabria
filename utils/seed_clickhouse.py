#!/usr/bin/env python3
"""Setup + seed do ClickHouse do Cantábria (DDL + carga, idempotente).

Faz, numa única execução determinística e repetível:
  1. gera os dados fictícios (`utils/generate_cantabria_data.py`);
  2. recria o schema a partir do DDL VERSIONADO em
     `infra/clickhouse/init/00_schema.sql` (fonte única de verdade — o
     mesmo arquivo que o container roda no primeiro boot);
  3. insere via `clickhouse-connect` (HTTP), em blocos.

Credenciais do ambiente (ver .env.example):
    CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_DB,
    CLICKHOUSE_SEED_USER, CLICKHOUSE_SEED_PASSWORD

Idempotência: DROP + CREATE + INSERT. O gerador tem seed fixa, então o
resultado é bit-a-bit o mesmo a cada execução.

Uso:
    python utils/seed_clickhouse.py
    python utils/seed_clickhouse.py --clientes 10000 --seed 42
    python utils/seed_clickhouse.py --export data/dataset   # Parquet opcional
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from utils.generate_cantabria_data import (  # noqa: E402
    DEFAULT_CLIENTES,
    DEFAULT_SEED,
    Dataset,
    exportar_parquet,
    gerar_dataset,
    resumo,
)
from utils.ingest_market_data import MarketPoint, read_cache  # noqa: E402

from entrypoints.env import load_dotenv  # noqa: E402

SCHEMA_SQL = REPO_ROOT / "infra" / "clickhouse" / "init" / "00_schema.sql"
DEFAULT_MARKET_CSV = REPO_ROOT / "data" / "market" / "bacen_sgs.csv"
TABELAS = [
    "fato_cliente",
    "dim_segmento",
    "dim_produto",
    "fato_contratos",
    "fato_contrato_produtos",
    "fato_rentabilidade_cliente",
    "fato_rentabilidade_contrato_produto",
    "mercado_indicadores",
]

# Tabelas do modelo antigo (explicacao.md, 4 bases): removidas na migração
# para data/base-ficticia.md. Num volume novo elas nem existem.
TABELAS_LEGADAS = ["dim_cliente", "fato_contrato", "fato_rentabilidade"]

CLIENTE_COLS = [
    "id_cliente",
    "cpf_cnpj",
    "nm_cliente",
    "ds_email",
    "nr_telefone",
    "tp_pess",
    "ds_segm_agrup",
    "ds_segm",
    "ds_subsegm_agrup",
    "ds_subsegm",
    "principalidade_score",
    "vinculacao_score",
]
SEGMENTO_COLS = [
    "id_segmento",
    "tp_pess",
    "ds_segm_agrup",
    "ds_segm",
    "ds_subsegm_agrup",
    "ds_subsegm",
]
PRODUTO_COLS = [
    "id_produto",
    "cd_produto",
    "ds_grupo_prod",
    "ds_produto",
    "ds_subproduto",
]
CONTRATO_COLS = ["id_contrato", "id_cliente", "dt_ini_contrato", "dt_encerramento"]
CONTRATO_PRODUTO_COLS = ["id_contrato", "id_produto"]
RENT_CLIENTE_COLS = ["id_cliente", "mes_ref", "vl_saldo", "vl_margem", "data_medicao"]
RENT_ITEM_COLS = [
    "id_contrato",
    "id_produto",
    "mes_ref",
    "vl_saldo",
    "vl_margem",
    "data_medicao",
]
MERCADO_COLS = [
    "indicador",
    "mes_ref",
    "taxa",
    "fonte",
    "serie_codigo",
    "data_extracao",
]


def _config(
    database: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> dict:
    return {
        "host": os.environ.get("CLICKHOUSE_HOST", "localhost"),
        "port": int(os.environ.get("CLICKHOUSE_PORT", "8123")),
        "database": database or os.environ.get("CLICKHOUSE_DB", "cantabria"),
        "username": user or os.environ.get("CLICKHOUSE_SEED_USER", "default"),
        "password": password
        if password is not None
        else os.environ.get("CLICKHOUSE_SEED_PASSWORD", ""),
    }


def _rows_clientes(dataset: Dataset) -> list[tuple]:
    return [tuple(c[campo] for campo in CLIENTE_COLS) for c in dataset.clientes]


def _rows_segmentos(dataset: Dataset) -> list[tuple]:
    return [
        (s.id, s.tp_pess, s.ds_segm_agrup, s.ds_segm, s.ds_subsegm_agrup, s.ds_subsegm)
        for s in dataset.segmentos
    ]


def _rows_produtos(dataset: Dataset) -> list[tuple]:
    return [
        (p.id, p.cd, p.ds_grupo_prod, p.ds_produto, p.ds_subproduto)
        for p in dataset.produtos
    ]


def _rows_contratos(dataset: Dataset) -> list[tuple]:
    return [
        (c["id_contrato"], c["id_cliente"], c["dt_ini_contrato"], c["dt_encerramento"])
        for c in dataset.contratos
    ]


def _rows_contrato_produtos(dataset: Dataset) -> list[tuple]:
    return [(i["id_contrato"], i["id_produto"]) for i in dataset.contrato_produtos]


def _rows_rent_cliente(dataset: Dataset) -> list[tuple]:
    return [
        (
            r["id_cliente"],
            r["mes_ref"],
            r["vl_saldo"],
            r["vl_margem"],
            r["data_medicao"],
        )
        for r in dataset.rentabilidade_cliente
    ]


def _rows_rent_item(dataset: Dataset) -> list[tuple]:
    return [
        (
            r["id_contrato"],
            r["id_produto"],
            r["mes_ref"],
            r["vl_saldo"],
            r["vl_margem"],
            r["data_medicao"],
        )
        for r in dataset.rentabilidade_contrato_produto
    ]


def _rows_mercado(points: list[MarketPoint]) -> list[tuple]:
    """Converte o valor publicado (% no mês) na fração decimal da tabela."""

    return [
        (
            point.indicador,
            point.data_referencia,
            point.valor_publicado / Decimal(100),
            point.fonte,
            point.serie_codigo,
            point.data_extracao,
        )
        for point in points
    ]


def _statements(sql: str) -> list[str]:
    """Divide um script SQL em comandos, descartando comentários e vazios."""
    linhas = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    limpo = "\n".join(linhas)
    return [stmt.strip() for stmt in limpo.split(";") if stmt.strip()]


def _apply_schema(client) -> None:
    """Executa o DDL versionado (fonte única de verdade)."""
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    # O DDL é idempotente (IF NOT EXISTS); removemos as tabelas antes para
    # garantir um dataset limpo a cada seed.
    db = client.database
    for tabela in TABELAS + TABELAS_LEGADAS:
        client.command(f"DROP TABLE IF EXISTS {db}.{tabela}")
    for statement in _statements(sql):
        client.command(statement)


def seed(dataset: Dataset, client, market_points: list[MarketPoint]) -> None:
    _apply_schema(client)
    db = client.database
    client.insert(
        f"{db}.fato_cliente", _rows_clientes(dataset), column_names=CLIENTE_COLS
    )
    client.insert(
        f"{db}.dim_segmento", _rows_segmentos(dataset), column_names=SEGMENTO_COLS
    )
    client.insert(
        f"{db}.dim_produto", _rows_produtos(dataset), column_names=PRODUTO_COLS
    )
    client.insert(
        f"{db}.fato_contratos", _rows_contratos(dataset), column_names=CONTRATO_COLS
    )
    client.insert(
        f"{db}.fato_contrato_produtos",
        _rows_contrato_produtos(dataset),
        column_names=CONTRATO_PRODUTO_COLS,
    )
    client.insert(
        f"{db}.fato_rentabilidade_cliente",
        _rows_rent_cliente(dataset),
        column_names=RENT_CLIENTE_COLS,
    )
    client.insert(
        f"{db}.fato_rentabilidade_contrato_produto",
        _rows_rent_item(dataset),
        column_names=RENT_ITEM_COLS,
    )
    client.insert(
        f"{db}.mercado_indicadores",
        _rows_mercado(market_points),
        column_names=MERCADO_COLS,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clientes", type=int, default=DEFAULT_CLIENTES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--market",
        type=Path,
        default=DEFAULT_MARKET_CSV,
        help="cache versionado das séries macro (data/market/bacen_sgs.csv)",
    )
    parser.add_argument(
        "--export", type=Path, default=None, help="Export Parquet opcional"
    )
    args = parser.parse_args()

    try:
        import clickhouse_connect
    except ImportError:
        raise SystemExit(
            "erro: instale clickhouse-connect (pip install clickhouse-connect)."
        ) from None

    load_dotenv()
    dataset = gerar_dataset(args.clientes, args.seed)
    market_points = read_cache(Path(args.market))
    print(resumo(dataset))

    target_db = os.environ.get("CLICKHOUSE_DB", "cantabria")

    # O client resolve o database na conexão; conectamos ao `default` para
    # garantir a existência do database alvo antes de abrir o client nele.
    bootstrap = clickhouse_connect.get_client(**_config(database="default"))
    try:
        bootstrap.command(f"CREATE DATABASE IF NOT EXISTS {target_db}")
    finally:
        bootstrap.close()

    client = clickhouse_connect.get_client(**_config())
    try:
        seed(dataset, client, market_points)
    finally:
        client.close()

    print(
        f"OK: {len(TABELAS)} tabelas recriadas e populadas no database "
        f"'{target_db}' ({len(market_points)} pontos de mercado)."
    )

    if args.export:
        exportar_parquet(dataset, args.export)
        print(f"Parquet exportado em {args.export}")


if __name__ == "__main__":
    main()

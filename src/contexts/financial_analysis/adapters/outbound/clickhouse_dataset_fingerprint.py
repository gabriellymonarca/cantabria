"""Adapter outbound: a impressão digital de conteúdo do dataset oficial.

Lê do ClickHouse um retrato canônico por tabela (contagens, somas em R$,
mês máximo) e devolve o hash sha256 desse retrato via o kernel puro
(`shared.dataset_version`). O mesmo retrato calculado em Python sobre as
linhas do fixture gera o mesmo digest: é assim que o harness prova que o
motor leu exatamente o dado do oracle.
"""

from __future__ import annotations

import os
from typing import Any

from contexts.financial_analysis.ports.outbound.dataset_fingerprint_port import (
    DatasetFingerprintPort,
)
from shared.dataset_version import (
    fingerprint_tables,
    normalize_count,
    normalize_money,
)

_RENT_TABLES = (
    "fato_rentabilidade_cliente",
    "fato_rentabilidade_contrato_produto",
)

_COUNT_TABLES = (
    "fato_cliente",
    "dim_segmento",
    "dim_produto",
    "fato_contratos",
    "fato_contrato_produtos",
)


class _LazyClickHouseClient:
    def __init__(self, kwargs: dict[str, Any]):

        self._kwargs = kwargs
        self._client: Any = None

    def query(self, sql: str) -> Any:

        if self._client is None:
            import clickhouse_connect

            self._client = clickhouse_connect.get_client(**self._kwargs)

        return self._client.query(sql)


class ClickHouseDatasetFingerprintAdapter(DatasetFingerprintPort):
    """Coleta o retrato canônico do ClickHouse e devolve o digest."""

    def __init__(self, client: Any, *, database: str):

        self._client = client
        self._database = database

    @classmethod
    def from_env(cls) -> ClickHouseDatasetFingerprintAdapter:

        client = _LazyClickHouseClient(
            {
                "host": os.environ.get("CLICKHOUSE_HOST", "localhost"),
                "port": int(os.environ.get("CLICKHOUSE_PORT", "8123")),
                "database": os.environ.get("CLICKHOUSE_DB", "cantabria"),
                "username": os.environ.get("CLICKHOUSE_USER", "default"),
                "password": os.environ.get("CLICKHOUSE_PASSWORD", ""),
            }
        )

        database = os.environ.get("CLICKHOUSE_DB", "cantabria")

        return cls(client, database=database)

    def digest(self) -> str:

        tables: dict[str, dict[str, str]] = {}

        for table in _COUNT_TABLES:
            tables[table] = {"count": self._count(table)}

        for table in _RENT_TABLES:
            tables[table] = self._rent_summary(table)

        return fingerprint_tables(tables)

    def _count(self, table: str) -> str:

        row = self._client.query(
            f"SELECT count() FROM {self._database}.{table}"
        ).first_row

        return normalize_count(row[0])

    def _rent_summary(self, table: str) -> dict[str, str]:

        row = self._client.query(
            f"SELECT count(), sum(vl_saldo), sum(vl_margem), max(mes_ref)"
            f" FROM {self._database}.{table}"
        ).first_row

        count, sum_saldo, sum_margem, max_mes = row

        return {
            "count": normalize_count(count),
            "max_mes_ref": max_mes.isoformat() if max_mes is not None else "",
            "sum_vl_margem": normalize_money(sum_margem)
            if sum_margem is not None
            else normalize_money(0),
            "sum_vl_saldo": normalize_money(sum_saldo)
            if sum_saldo is not None
            else normalize_money(0),
        }

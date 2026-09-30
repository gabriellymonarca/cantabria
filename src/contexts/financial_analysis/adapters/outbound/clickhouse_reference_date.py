"""Adapter ClickHouse: a data de referência é o último mês com dado oficial.

A data de referência é lida de `max(mes_ref)` das tabelas de fato analíticas e
avança sozinha quando um novo mês entra na base.

A conexão é preguiçosa e a falha é absorvida: banco fora do ar devolve `None` e
o prompt usa o valor de fallback do catálogo.
"""

from __future__ import annotations

import os
import time
from datetime import date
from typing import Any

import structlog

from contexts.financial_analysis.ports.outbound.reference_date_port import (
    ReferenceDatePort,
)

logger = structlog.get_logger(__name__)

# Maior mês analítico das tabelas de fato com grão mensal; `data_medicao` é
# linhagem (bitemporal), não eixo analítico.
_MAX_REFERENCE_DATE_SQL = (
    "SELECT max(mes_ref) FROM ("
    " SELECT max(mes_ref) AS mes_ref FROM fato_rentabilidade_cliente"
    " UNION ALL"
    " SELECT max(mes_ref) AS mes_ref FROM fato_rentabilidade_contrato_produto"
    ")"
)


class _LazyClickHouseClient:
    """Cria o client ClickHouse na primeira consulta."""

    def __init__(self, kwargs: dict[str, Any]):

        self._kwargs = kwargs
        self._client: Any = None

    def query(self, sql: str) -> Any:

        if self._client is None:
            import clickhouse_connect

            self._client = clickhouse_connect.get_client(**self._kwargs)

        return self._client.query(sql)


class ClickHouseReferenceDateAdapter(ReferenceDatePort):
    """Lê a data de referência do ClickHouse, com cache curto em memória."""

    def __init__(self, client: Any, *, ttl_seconds: float = 300.0):

        self._client = client
        self._ttl_seconds = ttl_seconds
        self._cached: date | None = None
        self._cached_at: float | None = None

    @classmethod
    def from_env(cls, *, ttl_seconds: float = 300.0) -> ClickHouseReferenceDateAdapter:

        client = _LazyClickHouseClient(
            {
                "host": os.environ.get("CLICKHOUSE_HOST", "localhost"),
                "port": int(os.environ.get("CLICKHOUSE_PORT", "8123")),
                "database": os.environ.get("CLICKHOUSE_DB", "cantabria"),
                "username": os.environ.get("CLICKHOUSE_USER", "default"),
                "password": os.environ.get("CLICKHOUSE_PASSWORD", ""),
            }
        )

        return cls(client, ttl_seconds=ttl_seconds)

    def latest_reference_date(self) -> date | None:

        if self._is_fresh():
            return self._cached

        try:
            row = self._client.query(_MAX_REFERENCE_DATE_SQL).first_row
            self._cached = row[0] if row else None
        except Exception as error:
            logger.warning(
                "Reference date unavailable; falling back to the catalog",
                error=str(error),
            )
            self._cached = None

        self._cached_at = time.monotonic()

        return self._cached

    def _is_fresh(self) -> bool:

        if self._cached_at is None:
            return False

        return (time.monotonic() - self._cached_at) < self._ttl_seconds

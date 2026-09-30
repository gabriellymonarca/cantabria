"""Data de referência lida do dado oficial, não do catálogo nem do relógio."""

from __future__ import annotations

from datetime import date
from typing import Any

from contexts.financial_analysis.adapters.outbound.clickhouse_reference_date import (
    ClickHouseReferenceDateAdapter,
)


class _StubClient:
    """Client ClickHouse falso: devolve um valor e conta as consultas."""

    def __init__(self, value: date | None):

        self._value = value
        self.calls = 0

    def query(self, sql: str) -> Any:

        self.calls += 1

        return _StubResult((self._value,))


class _StubResult:
    def __init__(self, first_row: tuple[date | None,]):

        self.first_row = first_row


class _BoomClient:
    def query(self, sql: str) -> Any:

        raise RuntimeError("clickhouse indisponível")


def test_le_a_data_do_clickhouse_e_cacheia() -> None:

    client = _StubClient(date(2026, 8, 31))
    adapter = ClickHouseReferenceDateAdapter(client)

    assert adapter.latest_reference_date() == date(2026, 8, 31)

    adapter.latest_reference_date()

    assert client.calls == 1


def test_falha_do_banco_devolve_none_para_fallback() -> None:

    adapter = ClickHouseReferenceDateAdapter(_BoomClient())

    assert adapter.latest_reference_date() is None

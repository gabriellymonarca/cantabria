"""Adapter concreto: settings, tradução da resposta e config do ambiente.

O client ClickHouse é substituído por um stub: prova que o adapter empurra
`join_use_nulls` (ausência vira NULL, nunca 0), passa os parâmetros tipados e
mapeia as linhas pelo layout compilado — sem subir banco.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import clickhouse_connect

from contexts.financial_calculation.adapters.outbound.clickhouse_config import (
    ClickHouseConfig,
)
from contexts.financial_calculation.adapters.outbound.clickhouse_official_data import (
    ClickHouseOfficialDataRepository,
)
from contexts.financial_calculation.domain.calculation_plan import RuleId
from contexts.financial_calculation.domain.metric_binding import METRIC_BINDINGS
from contexts.financial_calculation.ports.outbound.official_data_repository import (
    MetricRequest,
    PeriodRequest,
    SubjectRequest,
)


class _StubClient:
    def __init__(self, rows: list) -> None:

        self.rows = rows
        self.calls: list[tuple] = []
        self.closed = False

    def query(self, sql: str, parameters=None, settings=None) -> SimpleNamespace:

        self.calls.append((sql, parameters, settings))

        return SimpleNamespace(result_rows=self.rows)

    def close(self) -> None:

        self.closed = True


def _repository() -> ClickHouseOfficialDataRepository:

    return ClickHouseOfficialDataRepository(
        host="clickhouse",
        port=8123,
        database="cantabria",
        user="app",
        password="secret",
    )


def _request() -> MetricRequest:

    binding = METRIC_BINDINGS[RuleId.PROFITABILITY]

    return MetricRequest(
        rule_id=str(RuleId.PROFITABILITY),
        unit=binding.unit,
        aggregation=binding.aggregation,
        temporal_behavior=binding.temporal_behavior,
        subjects=(SubjectRequest("customer_segmentation", "segment"),),
    )


def test_fetch_aggregated_empurra_settings_e_mapeia_linhas(monkeypatch) -> None:

    stub = _StubClient(
        [("Varejo PF", dt.date(2026, 8, 31), Decimal("10.00"), Decimal("100.00"), 25)]
    )
    monkeypatch.setattr(clickhouse_connect, "get_client", lambda **kwargs: stub)

    repository = _repository()
    rows = repository.fetch_aggregated(
        _request(), PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month")
    )

    assert rows[0].subjects == {"customer_segmentation.segment": "Varejo PF"}
    assert rows[0].period == "2026-08-31"
    assert rows[0].components == {
        "numerator": Decimal("10.00"),
        "denominator": Decimal("100.00"),
        "population": 25,
    }

    sql, parameters, settings = stub.calls[0]

    assert "cantabria.fato_rentabilidade_cliente" in sql
    assert parameters["buckets"] == [dt.date(2026, 8, 31)]
    assert settings == {"join_use_nulls": 1}

    repository.close()

    assert stub.closed is True


def test_fetch_aggregated_devolve_ausencia_quando_client_devolve_nulo(
    monkeypatch,
) -> None:

    stub = _StubClient([("Varejo PF", dt.date(2026, 8, 31), None, None, None)])
    monkeypatch.setattr(clickhouse_connect, "get_client", lambda **kwargs: stub)

    repository = _repository()
    rows = repository.fetch_aggregated(
        _request(), PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month")
    )

    assert rows[0].components == {
        "numerator": None,
        "denominator": None,
        "population": None,
    }


def test_fetch_aggregated_de_mercado_empurra_indicador_e_mapeia_taxas(
    monkeypatch,
) -> None:

    stub = _StubClient([(dt.date(2026, 8, 31), [Decimal("0.01"), Decimal("0.02")])])
    monkeypatch.setattr(clickhouse_connect, "get_client", lambda **kwargs: stub)

    binding = METRIC_BINDINGS[RuleId.CDI_RATE]
    request = MetricRequest(
        rule_id=str(RuleId.CDI_RATE),
        unit=binding.unit,
        aggregation=binding.aggregation,
        temporal_behavior=binding.temporal_behavior,
        subjects=(SubjectRequest("total", "total"),),
    )

    repository = _repository()
    rows = repository.fetch_aggregated(
        request, PeriodRequest("2025-09-01", "2026-08-31", "series", "total")
    )

    assert rows[0].components == {"rates": (Decimal("0.01"), Decimal("0.02"))}

    sql, parameters, settings = stub.calls[0]

    assert "cantabria.mercado_indicadores" in sql
    assert parameters["indicador"] == "cdi"
    assert settings == {"join_use_nulls": 1}

    repository.close()

    assert stub.closed is True


def test_config_le_do_ambiente(monkeypatch) -> None:

    monkeypatch.setenv("CLICKHOUSE_HOST", "db.internal")
    monkeypatch.setenv("CLICKHOUSE_PORT", "9000")
    monkeypatch.setenv("CLICKHOUSE_DB", "cantabria")
    monkeypatch.setenv("CLICKHOUSE_USER", "cantabria_app")
    monkeypatch.setenv("CLICKHOUSE_PASSWORD", "secret")

    config = ClickHouseConfig.from_env()

    assert config == ClickHouseConfig(
        host="db.internal",
        port=9000,
        database="cantabria",
        user="cantabria_app",
        password="secret",
    )


def test_config_tem_defaults(monkeypatch) -> None:

    for name in (
        "CLICKHOUSE_HOST",
        "CLICKHOUSE_PORT",
        "CLICKHOUSE_DB",
        "CLICKHOUSE_USER",
        "CLICKHOUSE_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    config = ClickHouseConfig.from_env()

    assert config.host == "localhost"
    assert config.port == 8123
    assert config.database == "cantabria"
    assert config.user == "default"
    assert config.password == ""

"""Paridade SQL <-> referência: o adapter contra um ClickHouse real.

Sobe um ClickHouse efêmero, semeia um dataset mínimo determinístico no schema
vigente (`data/base-ficticia.md`) e compara o resultado do motor (via Port) com
uma agregação de referência feita em Python sobre os MESMOS dados. Cobre:
ratio por cliente e por produto, cruzamento cliente x produto, estoque no grão
(não soma), contagem com grupo ausente, `total`, recorte por faixa de score e
política de ausência (None).

Requer Docker. Rode: pytest -m integration
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from contexts.financial_calculation.adapters.outbound.clickhouse_official_data import (
    ClickHouseOfficialDataRepository,
)
from contexts.financial_calculation.application.commands.execute_calculation import (
    execute_calculation,
)
from contexts.financial_calculation.domain.calculation_plan import (
    AxisLevel,
    AxisType,
    CalculationPlan,
    Grain,
    Metric,
    Period,
    PeriodType,
    RuleId,
    SampleCondition,
    Subject,
)
from shared.aggregation import (
    annualize_rate,
    compound_annualized_rate,
    compound_rate,
    ratio,
    sum_values,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = REPO_ROOT / "infra" / "clickhouse" / "init" / "00_schema.sql"


def _schema_statements() -> list[str]:
    """DDL vigente do schema (fonte única): o teste não mantém cópia própria."""

    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    sql = sql.replace("cantabria.", "")
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    statements = [
        statement.strip()
        for statement in "\n".join(lines).split(";")
        if statement.strip()
    ]

    return [statement for statement in statements if "CREATE DATABASE" not in statement]


CLI_1 = uuid.UUID("11111111-1111-4111-8111-111111111111")
CLI_2 = uuid.UUID("22222222-2222-4222-8222-222222222222")
CLI_3 = uuid.UUID("33333333-3333-4333-8333-333333333333")

CLIENTES = [
    (
        CLI_1,
        "F",
        "Varejo PF",
        "Varejo PF",
        "Varejo",
        "Varejo",
        Decimal("30.00"),
        Decimal("30.00"),
    ),
    (
        CLI_2,
        "F",
        "Varejo PF",
        "Varejo PF",
        "Varejo",
        "Varejo",
        Decimal("80.00"),
        Decimal("80.00"),
    ),
    (
        CLI_3,
        "J",
        "Private",
        "Private",
        "Private",
        "Private",
        Decimal("80.00"),
        Decimal("50.00"),
    ),
]

PRODUTOS = [
    ("PROD_1", "1", "Crédito Rotativo", "Cartão", "Cartão Crédito"),
    ("PROD_2", "2", "Crédito Consignado", "Consignado", "Consignado Privado"),
]

CONTRATOS = [
    ("CTR_1", CLI_1, dt.date(2024, 1, 1), None),
    ("CTR_2", CLI_2, dt.date(2024, 1, 1), None),
    ("CTR_3", CLI_3, dt.date(2024, 1, 1), dt.date(2026, 7, 15)),
]

CONTRATO_PRODUTOS = [
    ("CTR_1", "PROD_1"),
    ("CTR_2", "PROD_1"),
    ("CTR_3", "PROD_2"),
]

RENT_CLIENTE = [
    (CLI_1, dt.date(2026, 6, 30), Decimal("100.00"), Decimal("10.00")),
    (CLI_1, dt.date(2026, 7, 31), Decimal("100.00"), Decimal("10.00")),
    (CLI_1, dt.date(2026, 8, 31), Decimal("100.00"), Decimal("10.00")),
    (CLI_2, dt.date(2026, 6, 30), Decimal("300.00"), Decimal("30.00")),
    (CLI_2, dt.date(2026, 7, 31), Decimal("200.00"), Decimal("40.00")),
    (CLI_2, dt.date(2026, 8, 31), Decimal("100.00"), Decimal("50.00")),
    (CLI_3, dt.date(2026, 6, 30), Decimal("1000.00"), Decimal("100.00")),
    (CLI_3, dt.date(2026, 7, 31), Decimal("1000.00"), Decimal("100.00")),
]

RENT_ITEM = [
    ("CTR_1", "PROD_1", dt.date(2026, 6, 30), Decimal("100.00"), Decimal("10.00")),
    ("CTR_1", "PROD_1", dt.date(2026, 7, 31), Decimal("100.00"), Decimal("10.00")),
    ("CTR_1", "PROD_1", dt.date(2026, 8, 31), Decimal("100.00"), Decimal("10.00")),
    ("CTR_2", "PROD_1", dt.date(2026, 6, 30), Decimal("300.00"), Decimal("30.00")),
    ("CTR_2", "PROD_1", dt.date(2026, 7, 31), Decimal("200.00"), Decimal("40.00")),
    ("CTR_2", "PROD_1", dt.date(2026, 8, 31), Decimal("100.00"), Decimal("50.00")),
    ("CTR_3", "PROD_2", dt.date(2026, 6, 30), Decimal("1000.00"), Decimal("100.00")),
    ("CTR_3", "PROD_2", dt.date(2026, 7, 31), Decimal("1000.00"), Decimal("100.00")),
]

MERCADO = [
    (
        "cdi",
        dt.date(2026, 6, 1),
        Decimal("0.010"),
        "BACEN/SGS",
        "4391",
        dt.date(2026, 9, 29),
    ),
    (
        "cdi",
        dt.date(2026, 7, 1),
        Decimal("0.020"),
        "BACEN/SGS",
        "4391",
        dt.date(2026, 9, 29),
    ),
    (
        "cdi",
        dt.date(2026, 8, 1),
        Decimal("-0.005"),
        "BACEN/SGS",
        "4391",
        dt.date(2026, 9, 29),
    ),
]

CDI_MONTHLY = {
    "2026-06-30": Decimal("0.010"),
    "2026-07-31": Decimal("0.020"),
    "2026-08-31": Decimal("-0.005"),
}

SEGMENTO_POR_CLIENTE = {CLI_1: "Varejo PF", CLI_2: "Varejo PF", CLI_3: "Private"}
PRODUTO_POR_CONTRATO = {"CTR_1": "Cartão", "CTR_2": "Cartão", "CTR_3": "Consignado"}


@pytest.fixture(scope="module")
def repository():
    from testcontainers.community.clickhouse import ClickHouseContainer

    with ClickHouseContainer(
        "clickhouse/clickhouse-server:24.8",
        username="test",
        password="test",
        dbname="test",
    ) as container:
        import clickhouse_connect

        client = clickhouse_connect.get_client(
            host=container.get_container_host_ip(),
            port=container.get_exposed_port(8123),
            username="test",
            password="test",
            database="test",
        )
        for statement in _schema_statements():
            client.command(statement)

        client.insert(
            "fato_cliente",
            CLIENTES,
            column_names=[
                "id_cliente",
                "tp_pess",
                "ds_segm_agrup",
                "ds_segm",
                "ds_subsegm_agrup",
                "ds_subsegm",
                "principalidade_score",
                "vinculacao_score",
            ],
        )
        client.insert(
            "dim_produto",
            PRODUTOS,
            column_names=[
                "id_produto",
                "cd_produto",
                "ds_grupo_prod",
                "ds_produto",
                "ds_subproduto",
            ],
        )
        client.insert(
            "fato_contratos",
            CONTRATOS,
            column_names=[
                "id_contrato",
                "id_cliente",
                "dt_ini_contrato",
                "dt_encerramento",
            ],
        )
        client.insert(
            "fato_contrato_produtos",
            CONTRATO_PRODUTOS,
            column_names=["id_contrato", "id_produto"],
        )
        client.insert(
            "fato_rentabilidade_cliente",
            [row + (row[1],) for row in RENT_CLIENTE],
            column_names=[
                "id_cliente",
                "mes_ref",
                "vl_saldo",
                "vl_margem",
                "data_medicao",
            ],
        )
        client.insert(
            "fato_rentabilidade_contrato_produto",
            [row + (row[2],) for row in RENT_ITEM],
            column_names=[
                "id_contrato",
                "id_produto",
                "mes_ref",
                "vl_saldo",
                "vl_margem",
                "data_medicao",
            ],
        )
        client.insert(
            "mercado_indicadores",
            MERCADO,
            column_names=[
                "indicador",
                "mes_ref",
                "taxa",
                "fonte",
                "serie_codigo",
                "data_extracao",
            ],
        )

        repo = ClickHouseOfficialDataRepository(
            host=container.get_container_host_ip(),
            port=container.get_exposed_port(8123),
            database="test",
            user="test",
            password="test",
        )

        yield repo

        repo.close()


def _rows(metric: Metric, period: Period, repository) -> list:
    plan = CalculationPlan(calculation_plan_id="calc", metric=metric, period=period)
    result = execute_calculation(plan, repository)

    return result.values


def _value(rows: list, period: str, subjects: dict):
    for row in rows:
        if row.period != period:
            continue
        if all(row.subjects.get(key) == value for key, value in subjects.items()):
            return row.value

    raise AssertionError(f"linha não encontrada: {period} {subjects}")


def _segment_of(client: uuid.UUID) -> str:
    return SEGMENTO_POR_CLIENTE[client]


def _reference_profitability_cliente(segment: str, month: str) -> Decimal | None:
    margens, saldos = [], []

    for client, mes, saldo, margem in RENT_CLIENTE:
        if mes.isoformat() != month:
            continue
        if _segment_of(client) == segment:
            margens.append(margem)
            saldos.append(saldo)

    if not saldos:
        return None

    return ratio(sum_values(margens), sum_values(saldos))


def _reference_profitability_produto(produto: str, month: str) -> Decimal | None:
    margens, saldos = [], []

    for contrato, _id_produto, mes, saldo, margem in RENT_ITEM:
        if mes.isoformat() != month:
            continue
        if PRODUTO_POR_CONTRATO[contrato] == produto:
            margens.append(margem)
            saldos.append(saldo)

    if not saldos:
        return None

    return ratio(sum_values(margens), sum_values(saldos))


def _reference_profitability_par(
    segment: str, produto: str, month: str
) -> Decimal | None:
    margens, saldos = [], []

    for contrato, _id_produto, mes, saldo, margem in RENT_ITEM:
        if mes.isoformat() != month:
            continue
        if PRODUTO_POR_CONTRATO[contrato] != produto:
            continue
        client = next(c for c in CONTRATOS if c[0] == contrato)[1]
        if _segment_of(client) == segment:
            margens.append(margem)
            saldos.append(saldo)

    if not saldos:
        return None

    return ratio(sum_values(margens), sum_values(saldos))


def test_profitability_series_por_segmento(repository) -> None:
    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[
            Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SEGMENT)
        ],
    )
    period = Period(
        start=dt.date(2026, 6, 1),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SERIES,
        grain=Grain.MONTH,
    )

    rows = _rows(metric, period, repository)

    for month in ("2026-06-30", "2026-07-31", "2026-08-31"):
        value = _value(rows, month, {"customer_segmentation.segment": "Varejo PF"})
        assert value == _reference_profitability_cliente("Varejo PF", month)

    assert _value(rows, "2026-06-30", {"customer_segmentation.segment": "Private"}) == (
        _reference_profitability_cliente("Private", "2026-06-30")
    )
    assert (
        _value(rows, "2026-08-31", {"customer_segmentation.segment": "Private"}) is None
    )


def test_profitability_series_por_produto(repository) -> None:
    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[Subject(type=AxisType.PRODUCT, level=AxisLevel.PRODUCT)],
    )
    period = Period(
        start=dt.date(2026, 6, 1),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SERIES,
        grain=Grain.MONTH,
    )

    rows = _rows(metric, period, repository)

    for month in ("2026-06-30", "2026-07-31", "2026-08-31"):
        assert _value(rows, month, {"product.product": "Cartão"}) == (
            _reference_profitability_produto("Cartão", month)
        )

    assert _value(rows, "2026-08-31", {"product.product": "Consignado"}) is None


def test_profitability_cruzamento_segmento_produto(repository) -> None:
    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[
            Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SEGMENT),
            Subject(type=AxisType.PRODUCT, level=AxisLevel.PRODUCT),
        ],
    )
    period = Period(
        start=dt.date(2026, 6, 1),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SERIES,
        grain=Grain.MONTH,
    )

    rows = _rows(metric, period, repository)

    subjects = {
        "customer_segmentation.segment": "Varejo PF",
        "product.product": "Cartão",
    }

    for month in ("2026-06-30", "2026-07-31", "2026-08-31"):
        assert _value(rows, month, subjects) == (
            _reference_profitability_par("Varejo PF", "Cartão", month)
        )


def test_estoque_no_grao_nao_soma(repository) -> None:
    metric = Metric(
        rule_id=RuleId.OUTSTANDING_BALANCE,
        subjects=[
            Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SEGMENT)
        ],
    )
    period = Period(
        start=dt.date(2026, 6, 1),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SERIES,
        grain=Grain.QUARTER,
    )

    rows = _rows(metric, period, repository)

    varejo = {"customer_segmentation.segment": "Varejo PF"}
    private = {"customer_segmentation.segment": "Private"}

    assert _value(rows, "2026-06-30", varejo) == Decimal("400.00")
    assert _value(rows, "2026-09-30", varejo) == Decimal("200.00")
    assert _value(rows, "2026-09-30", private) == Decimal("1000.00")


def test_contract_count_snapshot_com_grupo_ausente(repository) -> None:
    metric = Metric(
        rule_id=RuleId.CONTRACT_COUNT,
        subjects=[
            Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SEGMENT)
        ],
    )
    period = Period(
        start=dt.date(2026, 8, 31),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SNAPSHOT,
        grain=Grain.MONTH,
    )

    rows = _rows(metric, period, repository)

    assert (
        _value(rows, "2026-08-31", {"customer_segmentation.segment": "Varejo PF"}) == 2
    )
    assert (
        _value(rows, "2026-08-31", {"customer_segmentation.segment": "Private"}) is None
    )


def test_customer_count_por_produto(repository) -> None:
    metric = Metric(
        rule_id=RuleId.CUSTOMER_COUNT,
        subjects=[Subject(type=AxisType.PRODUCT, level=AxisLevel.PRODUCT)],
    )
    period = Period(
        start=dt.date(2026, 8, 31),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SNAPSHOT,
        grain=Grain.MONTH,
    )

    rows = _rows(metric, period, repository)

    assert _value(rows, "2026-08-31", {"product.product": "Cartão"}) == 2
    assert _value(rows, "2026-08-31", {"product.product": "Consignado"}) is None


def test_total_nao_tem_dimensao(repository) -> None:
    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[Subject(type=AxisType.TOTAL, level=AxisLevel.TOTAL)],
    )
    period = Period(
        start=dt.date(2026, 8, 31),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SNAPSHOT,
        grain=Grain.MONTH,
    )

    plan = CalculationPlan(calculation_plan_id="calc", metric=metric, period=period)
    result = execute_calculation(plan, repository)

    assert len(result.values) == 1
    assert result.values[0].subjects == {}
    assert result.values[0].value == Decimal("60.00") / Decimal("200.00")


def test_recorte_por_faixa_de_score(repository) -> None:
    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[Subject(type=AxisType.PRODUCT, level=AxisLevel.PRODUCT)],
        sample=[
            SampleCondition(
                type=AxisType.CUSTOMER_PRINCIPALITY,
                level=AxisLevel.PRINCIPALITY_DEPTH,
                value_id="high",
            )
        ],
    )
    period = Period(
        start=dt.date(2026, 8, 31),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SNAPSHOT,
        grain=Grain.MONTH,
    )

    rows = _rows(metric, period, repository)

    assert _value(rows, "2026-08-31", {"product.product": "Cartão"}) == (
        Decimal("50.00") / Decimal("100.00")
    )
    assert _value(rows, "2026-08-31", {"product.product": "Consignado"}) is None


def test_recorte_de_produto_em_quebra_de_cliente(repository) -> None:
    metric = Metric(
        rule_id=RuleId.CUSTOMER_COUNT,
        subjects=[
            Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SEGMENT)
        ],
        sample=[
            SampleCondition(
                type=AxisType.PRODUCT,
                level=AxisLevel.PRODUCT_GROUP,
                value_id="rotativo",
            )
        ],
    )
    period = Period(
        start=dt.date(2026, 8, 31),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SNAPSHOT,
        grain=Grain.MONTH,
    )

    rows = _rows(metric, period, repository)

    assert (
        _value(rows, "2026-08-31", {"customer_segmentation.segment": "Varejo PF"}) == 2
    )
    assert (
        _value(rows, "2026-08-31", {"customer_segmentation.segment": "Private"}) is None
    )


def test_rentabilidade_no_trimestre_rederiva_do_fato_e_nao_e_media(repository) -> None:
    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[
            Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SEGMENT)
        ],
    )
    period = Period(
        start=dt.date(2026, 6, 1),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SERIES,
        grain=Grain.QUARTER,
    )

    rows = _rows(metric, period, repository)
    value = _value(rows, "2026-09-30", {"customer_segmentation.segment": "Varejo PF"})

    rederived = ratio(
        sum_values([Decimal("50.00"), Decimal("60.00")]),
        sum_values([Decimal("300.00"), Decimal("200.00")]),
    )
    mean_of_rates = sum_values(
        [
            Decimal("50.00") / Decimal("300.00"),
            Decimal("60.00") / Decimal("200.00"),
        ]
    ) / Decimal("2")

    assert value == rederived
    assert value != mean_of_rates


def test_grao_total_rederiva_a_janela_inteira(repository) -> None:

    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[
            Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SEGMENT)
        ],
    )
    period = Period(
        start=dt.date(2026, 6, 1),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SERIES,
        grain=Grain.TOTAL,
    )

    rows = _rows(metric, period, repository)
    value = _value(rows, "2026-08-31", {"customer_segmentation.segment": "Varejo PF"})

    margens = [
        margem
        for client, mes, _saldo, margem in RENT_CLIENTE
        if dt.date(2026, 6, 1) <= mes <= dt.date(2026, 8, 31)
        and _segment_of(client) == "Varejo PF"
    ]
    saldos = [
        saldo
        for client, mes, saldo, _margem in RENT_CLIENTE
        if dt.date(2026, 6, 1) <= mes <= dt.date(2026, 8, 31)
        and _segment_of(client) == "Varejo PF"
    ]

    assert value == ratio(sum_values(margens), sum_values(saldos))
    assert len(rows) == len(
        {row.subjects["customer_segmentation.segment"] for row in rows}
    )


def _market_metric(rule_id: RuleId) -> Metric:

    return Metric(
        rule_id=rule_id,
        subjects=[Subject(type=AxisType.TOTAL, level=AxisLevel.TOTAL)],
    )


def test_mercado_mensal_anualiza_cada_mes(repository) -> None:
    """A série mensal entrega a taxa anual equivalente de cada mês semeado."""

    metric = _market_metric(RuleId.CDI_RATE)
    period = Period(
        start=dt.date(2026, 6, 1),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SERIES,
        grain=Grain.MONTH,
    )

    rows = _rows(metric, period, repository)

    assert [row.period for row in rows] == list(CDI_MONTHLY)

    for month, rate in CDI_MONTHLY.items():
        assert _value(rows, month, {}) == compound_annualized_rate([rate])


def test_mercado_total_capitaliza_a_janela_e_anualiza(repository) -> None:
    """Três meses: a janela compõe Π(1+r) e anualiza por 12/3 — nunca soma."""

    metric = _market_metric(RuleId.CDI_RATE)
    period = Period(
        start=dt.date(2026, 6, 1),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SERIES,
        grain=Grain.TOTAL,
    )

    rows = _rows(metric, period, repository)
    value = _value(rows, "2026-08-31", {})
    rates = tuple(CDI_MONTHLY.values())

    assert len(rows) == 1
    assert rows[0].subjects == {}
    assert value == compound_annualized_rate(rates)
    assert value == annualize_rate(compound_rate(rates), 3)
    assert value != compound_rate(rates)
    assert value != sum_values(rates)


def test_mercado_sem_serie_semeada_e_ausencia_e_nao_zero(repository) -> None:
    """SELIC não está na tabela semeada: bucket ausente é `None`, nunca 0.0."""

    metric = _market_metric(RuleId.SELIC_RATE)
    period = Period(
        start=dt.date(2026, 6, 1),
        end=dt.date(2026, 8, 31),
        type=PeriodType.SERIES,
        grain=Grain.TOTAL,
    )

    rows = _rows(metric, period, repository)

    assert len(rows) == 1
    assert rows[0].value is None

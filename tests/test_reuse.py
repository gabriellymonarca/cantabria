"""Chave de reuso e cache do `run_calculation`.

A chave usa a identidade semântica (rule, quebra, recorte, período, versões),
não os rótulos efêmeros do pacote. O `run_calculation` consulta o store antes
de recalcular e grava o resultado no miss.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from contexts.financial_calculation.adapters.outbound.in_memory_calculation_store import (
    InMemoryCalculationStore,
)
from contexts.financial_calculation.application.commands.run_calculation import (
    run_calculation,
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
from contexts.financial_calculation.domain.calculation_result import CalculationResult
from contexts.financial_calculation.domain.reuse_key import compute_reuse_key
from contexts.financial_calculation.ports.outbound.official_data_repository import (
    AggregatedRow,
)


class CountingRepository:
    def __init__(self) -> None:

        self.calls = 0

    def fetch_aggregated(self, metric, period) -> list[AggregatedRow]:

        self.calls += 1

        return [
            AggregatedRow(
                subjects={"customer_segmentation.segment": "Varejo PF"},
                period="2026-09-30",
                components={"value": Decimal("400.00")},
            )
        ]


def _high_principality() -> SampleCondition:
    return SampleCondition(
        type=AxisType.CUSTOMER_PRINCIPALITY,
        level=AxisLevel.PRINCIPALITY_DEPTH,
        value_id="high",
    )


def _plan(
    *,
    plan_id: str = "calc1",
    metric_id: str | None = None,
    rule_id: RuleId = RuleId.OUTSTANDING_BALANCE,
    subjects: list[Subject] | None = None,
    sample: list[SampleCondition] | None = None,
    start: date = date(2026, 7, 1),
    end: date = date(2026, 9, 30),
    type_: PeriodType = PeriodType.SERIES,
    grain: Grain = Grain.MONTH,
) -> CalculationPlan:

    return CalculationPlan(
        calculation_plan_id=plan_id,
        metric=Metric(
            id=metric_id,
            rule_id=rule_id,
            subjects=subjects
            or [
                Subject(
                    type=AxisType.CUSTOMER_SEGMENTATION,
                    level=AxisLevel.SEGMENT,
                )
            ],
            sample=sample or [],
        ),
        period=Period(start=start, end=end, type=type_, grain=grain),
    )


def test_rotulos_diferentes_nao_mudam_a_chave() -> None:

    first = compute_reuse_key(
        _plan(plan_id="calc_a", metric_id="m_a"), "v1", "2026-08-31"
    )
    second = compute_reuse_key(
        _plan(plan_id="calc_b", metric_id="m_b"), "v1", "2026-08-31"
    )

    assert first == second


def test_recorte_diferente_muda_a_chave() -> None:

    without = compute_reuse_key(_plan(), "v1", "2026-08-31")
    with_high = compute_reuse_key(
        _plan(sample=[_high_principality()]), "v1", "2026-08-31"
    )

    assert without != with_high


def test_periodo_diferente_muda_a_chave() -> None:

    first = compute_reuse_key(_plan(), "v1", "2026-08-31")
    second = compute_reuse_key(_plan(start=date(2026, 6, 1)), "v1", "2026-08-31")

    assert first != second


def test_versao_de_snapshot_muda_a_chave() -> None:

    first = compute_reuse_key(_plan(), "v1", "2026-08-31")
    second = compute_reuse_key(_plan(), "v1", "2026-07-31")

    assert first != second


def test_run_calculation_reusa_o_resultado() -> None:

    repository = CountingRepository()
    store = InMemoryCalculationStore()
    plan = _plan()

    first = run_calculation(plan, repository, store, "v1", "2026-08-31")
    second = run_calculation(plan, repository, store, "v1", "2026-08-31")

    assert repository.calls == 1
    assert first == second
    assert first.values[0].value == Decimal("400.00")


def test_snapshot_novo_recalcula() -> None:

    repository = CountingRepository()
    store = InMemoryCalculationStore()
    plan = _plan()

    run_calculation(plan, repository, store, "v1", "2026-08-31")
    run_calculation(plan, repository, store, "v1", "2026-09-30")

    assert repository.calls == 2


def test_ordem_de_quebras_e_recortes_nao_muda_a_chave() -> None:

    segment = Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SEGMENT)
    product = Subject(type=AxisType.PRODUCT, level=AxisLevel.PRODUCT)
    first_condition = _high_principality()
    second_condition = SampleCondition(
        type=AxisType.CUSTOMER_RELATIONSHIP,
        level=AxisLevel.RELATIONSHIP_DEPTH,
        value_id="high",
    )

    first = _plan(
        subjects=[segment, product], sample=[first_condition, second_condition]
    )
    second = _plan(
        subjects=[product, segment], sample=[second_condition, first_condition]
    )

    assert compute_reuse_key(first, "v1", "2026-08-31") == compute_reuse_key(
        second, "v1", "2026-08-31"
    )


def test_rule_diferente_muda_a_chave() -> None:

    first = compute_reuse_key(_plan(), "v1", "2026-08-31")
    second = compute_reuse_key(_plan(rule_id=RuleId.PROFITABILITY), "v1", "2026-08-31")

    assert first != second


def test_versao_de_catalogo_muda_a_chave() -> None:

    first = compute_reuse_key(_plan(), "v1", "2026-08-31")
    second = compute_reuse_key(_plan(), "v2", "2026-08-31")

    assert first != second


def test_tipo_e_grao_mudam_a_chave() -> None:

    series_month = compute_reuse_key(_plan(), "v1", "2026-08-31")
    snapshot = compute_reuse_key(
        _plan(
            type_=PeriodType.SNAPSHOT, start=date(2026, 8, 31), end=date(2026, 8, 31)
        ),
        "v1",
        "2026-08-31",
    )
    quarter = compute_reuse_key(_plan(grain=Grain.QUARTER), "v1", "2026-08-31")

    assert series_month != snapshot
    assert series_month != quarter


def test_chave_e_estavel_entre_chamadas() -> None:

    plan = _plan()

    assert compute_reuse_key(plan, "v1", "2026-08-31") == compute_reuse_key(
        plan, "v1", "2026-08-31"
    )


def test_quebra_diferente_muda_a_chave() -> None:

    first = compute_reuse_key(_plan(), "v1", "2026-08-31")
    second = compute_reuse_key(
        _plan(
            subjects=[
                Subject(type=AxisType.PRODUCT, level=AxisLevel.PRODUCT),
            ]
        ),
        "v1",
        "2026-08-31",
    )

    assert first != second


def test_valor_de_recorte_diferente_muda_a_chave() -> None:

    low = SampleCondition(
        type=AxisType.CUSTOMER_PRINCIPALITY,
        level=AxisLevel.PRINCIPALITY_DEPTH,
        value_id="low",
    )

    assert compute_reuse_key(
        _plan(sample=[low]), "v1", "2026-08-31"
    ) != compute_reuse_key(_plan(sample=[_high_principality()]), "v1", "2026-08-31")


def test_store_em_memoria_guarda_e_devolve() -> None:

    store = InMemoryCalculationStore()
    result = CalculationResult(
        calculation_plan_id="calc1", rule_id="outstanding_balance", unit="currency"
    )

    assert store.find("sem-chave") is None

    store.save("chave", result)

    assert store.find("chave") is result


def test_reuso_entre_rotulos_devolve_o_resultado_do_primeiro() -> None:

    repository = CountingRepository()
    store = InMemoryCalculationStore()

    first = run_calculation(
        _plan(plan_id="calc_a"), repository, store, "v1", "2026-08-31"
    )
    second = run_calculation(
        _plan(plan_id="calc_b"), repository, store, "v1", "2026-08-31"
    )

    # Uma só ida ao armazém; as linhas são as mesmas, mas o rótulo é do plano
    # que pediu — a análise procura o resultado pelo id do plano atual.
    assert repository.calls == 1
    assert second.values is first.values
    assert second.calculation_plan_id == "calc_b"
    assert first.calculation_plan_id == "calc_a"

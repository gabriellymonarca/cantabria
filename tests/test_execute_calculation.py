"""Use case `execute_calculation`: validação tipada e combinação de componentes.

O motor não agrega: ele recebe componentes já agregados pelo Port e aplica a
fórmula genérica. Aqui um FakeRepository devolve os componentes direto, o que
prova a combinação e a política de ausência sem banco.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date
from decimal import Decimal
from typing import cast

import pytest

from contexts.financial_calculation.application.commands.execute_calculation import (
    _combine,
    execute_calculation,
)
from contexts.financial_calculation.domain.calculation_plan import (
    LEVELS_BY_AXIS,
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
    is_known_value,
)
from contexts.financial_calculation.domain.errors import (
    CalculationError,
    InvalidPeriodError,
    InvalidPlanError,
    UnknownAxisError,
    UnknownRuleError,
    UnknownValueError,
    UnsupportedGrainError,
)
from contexts.financial_calculation.domain.metric_binding import (
    Aggregation,
    MetricBinding,
)
from contexts.financial_calculation.ports.outbound.official_data_repository import (
    AggregatedRow,
    MetricRequest,
    PeriodRequest,
)


class FakeRepository:
    """Devolve componentes pré-fabricados, ignorando a agregação real."""

    def __init__(self, rows: list[AggregatedRow] | None = None):

        self._rows = rows or []
        self.calls: list[tuple[MetricRequest, PeriodRequest]] = []

    def fetch_aggregated(
        self,
        metric: MetricRequest,
        period: PeriodRequest,
    ) -> list[AggregatedRow]:

        self.calls.append((metric, period))

        return list(self._rows)


def _segment_subject() -> Subject:
    return Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SEGMENT)


def _profit_seg_metric() -> Metric:
    return Metric(rule_id=RuleId.PROFITABILITY, subjects=[_segment_subject()])


def _period(
    *,
    grain: Grain = Grain.MONTH,
    type_: PeriodType = PeriodType.SERIES,
    start: date = date(2026, 7, 1),
    end: date = date(2026, 9, 30),
) -> Period:
    return Period(start=start, end=end, type=type_, grain=grain)


def _plan(metric: Metric, period: Period | None = None) -> CalculationPlan:
    return CalculationPlan(
        calculation_plan_id="calc1",
        metric=metric,
        period=period or _period(),
    )


def _row(
    components: dict,
    subjects: dict | None = None,
    period: str = "2026-09-30",
) -> AggregatedRow:
    return AggregatedRow(
        subjects=(
            subjects
            if subjects is not None
            else {"customer_segmentation.segment": "Varejo PF"}
        ),
        period=period,
        components=components,
    )


def test_ratio_rederiva_dos_componentes() -> None:

    repo = FakeRepository(
        [_row({"numerator": Decimal("300.00"), "denominator": Decimal("11100.00")})]
    )

    result = execute_calculation(_plan(_profit_seg_metric()), repo)

    assert result.calculation_plan_id == "calc1"
    assert result.rule_id == "profitability"
    assert result.unit == "decimal_rate"
    assert result.values[0].value == Decimal("300.00") / Decimal("11100.00")
    assert result.values[0].subjects == {"customer_segmentation.segment": "Varejo PF"}


def test_population_do_port_chega_a_linha_como_inteiro() -> None:

    repo = FakeRepository(
        [
            _row(
                {
                    "numerator": Decimal("300.00"),
                    "denominator": Decimal("11100.00"),
                    "population": Decimal("37"),
                }
            )
        ]
    )

    result = execute_calculation(_plan(_profit_seg_metric()), repo)

    assert result.values[0].population == 37
    assert isinstance(result.values[0].population, int)


def test_population_ausente_no_port_fica_desconhecida() -> None:
    """Repositório sem `population`: a linha carrega None (desconhecido), não 0."""

    repo = FakeRepository(
        [_row({"numerator": Decimal("300.00"), "denominator": Decimal("11100.00")})]
    )

    result = execute_calculation(_plan(_profit_seg_metric()), repo)

    assert result.values[0].population is None
    assert result.values[0].value is not None


def test_denominador_zero_e_ausencia_nunca_zero() -> None:

    repo = FakeRepository(
        [_row({"numerator": Decimal("0.00"), "denominator": Decimal("0.00")})]
    )

    result = execute_calculation(_plan(_profit_seg_metric()), repo)

    assert result.values[0].value is None


def test_grupo_ausente_propaga_nulo() -> None:

    repo = FakeRepository([_row({"numerator": None, "denominator": None})])

    result = execute_calculation(_plan(_profit_seg_metric()), repo)

    assert result.values[0].value is None


def test_estoque_usa_componente_value() -> None:

    metric = Metric(
        rule_id=RuleId.OUTSTANDING_BALANCE,
        subjects=[_segment_subject()],
    )
    repo = FakeRepository([_row({"value": Decimal("400.00")})])

    result = execute_calculation(_plan(metric), repo)

    assert result.values[0].value == Decimal("400.00")
    assert result.unit == "currency"


def test_contagem_distinta_passa_direto() -> None:

    metric = Metric(rule_id=RuleId.CONTRACT_COUNT, subjects=[_segment_subject()])
    repo = FakeRepository([_row({"value": 42})])

    result = execute_calculation(_plan(metric), repo)

    assert result.values[0].value == 42
    assert result.unit == "count"


def test_plano_carrega_exatamente_uma_metrica() -> None:

    assert [field.name for field in fields(CalculationPlan)] == [
        "calculation_plan_id",
        "metric",
        "period",
    ]


def test_rule_id_fora_do_catalogo() -> None:

    metric = Metric(rule_id=cast(RuleId, "producao"), subjects=[_segment_subject()])

    with pytest.raises(UnknownRuleError):
        execute_calculation(_plan(metric), FakeRepository())


def test_eixo_fora_do_catalogo() -> None:

    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[
            Subject(
                type=AxisType.CUSTOMER_SEGMENTATION,
                level=cast(AxisLevel, "regiao"),
            )
        ],
    )

    with pytest.raises(UnknownAxisError):
        execute_calculation(_plan(metric), FakeRepository())


def test_grain_invalido() -> None:

    with pytest.raises(UnsupportedGrainError):
        execute_calculation(
            _plan(_profit_seg_metric(), _period(grain=cast(Grain, "semana"))),
            FakeRepository(),
        )


# A forma do período e da métrica é invariante dos value objects: o plano
# malformado nem chega a existir, então o erro sai da construção, não do motor.


def test_snapshot_exige_start_igual_end() -> None:

    with pytest.raises(InvalidPeriodError):
        _period(
            type_=PeriodType.SNAPSHOT,
            start=date(2026, 7, 1),
            end=date(2026, 9, 30),
        )


def test_start_posterior_ao_fim_e_recusado() -> None:

    with pytest.raises(InvalidPeriodError):
        _period(start=date(2026, 9, 30), end=date(2026, 7, 1))


def test_data_iso_e_normalizada_para_date() -> None:

    period = Period(
        start="2026-07-01", end="2026-09-30", type=PeriodType.SERIES, grain=Grain.MONTH
    )  # type: ignore[arg-type]

    assert period.start == date(2026, 7, 1)
    assert period.end == date(2026, 9, 30)


def test_eixo_repetido() -> None:

    with pytest.raises(InvalidPlanError):
        Metric(
            rule_id=RuleId.PROFITABILITY,
            subjects=[_segment_subject(), _segment_subject()],
        )


def test_plano_sem_quebra_e_recusado() -> None:

    with pytest.raises(InvalidPlanError):
        Metric(rule_id=RuleId.PROFITABILITY, subjects=[])


def test_total_com_outra_quebra_e_recusado() -> None:

    with pytest.raises(InvalidPlanError):
        Metric(
            rule_id=RuleId.PROFITABILITY,
            subjects=[
                Subject(type=AxisType.TOTAL, level=AxisLevel.TOTAL),
                _segment_subject(),
            ],
        )


def test_recorte_igual_ao_eixo_e_recusado() -> None:

    with pytest.raises(UnknownAxisError):
        Metric(
            rule_id=RuleId.PROFITABILITY,
            subjects=[_segment_subject()],
            sample=[
                SampleCondition(
                    type=AxisType.CUSTOMER_SEGMENTATION,
                    level=AxisLevel.SEGMENT,
                    value_id="varejo_pf",
                )
            ],
        )


def test_valor_de_recorte_fora_do_catalogo() -> None:

    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[_segment_subject()],
        sample=[
            SampleCondition(
                type=AxisType.CUSTOMER_PRINCIPALITY,
                level=AxisLevel.PRINCIPALITY_DEPTH,
                value_id="altissima",
            )
        ],
    )

    with pytest.raises(UnknownValueError):
        execute_calculation(_plan(metric), FakeRepository())


def test_recorte_repetido_e_recusado() -> None:

    condition = SampleCondition(
        type=AxisType.CUSTOMER_PRINCIPALITY,
        level=AxisLevel.PRINCIPALITY_DEPTH,
        value_id="high",
    )

    with pytest.raises(InvalidPlanError):
        Metric(
            rule_id=RuleId.PROFITABILITY,
            subjects=[_segment_subject()],
            sample=[condition, condition],
        )


def test_total_nao_e_recorte_valido() -> None:

    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[_segment_subject()],
        sample=[
            SampleCondition(
                type=AxisType.TOTAL, level=AxisLevel.TOTAL, value_id="total"
            ),
        ],
    )

    with pytest.raises(UnknownAxisError):
        execute_calculation(_plan(metric), FakeRepository())


def test_recorte_de_produto_sem_quebra_de_produto_e_recusado() -> None:

    metric = Metric(
        rule_id=RuleId.OUTSTANDING_BALANCE,
        subjects=[_segment_subject()],
        sample=[
            SampleCondition(
                type=AxisType.PRODUCT,
                level=AxisLevel.PRODUCT_GROUP,
                value_id="rotativo",
            )
        ],
    )

    with pytest.raises(InvalidPlanError):
        execute_calculation(_plan(metric), FakeRepository())


def test_recorte_de_produto_com_quebra_de_produto_e_aceito() -> None:

    metric = Metric(
        rule_id=RuleId.OUTSTANDING_BALANCE,
        subjects=[Subject(type=AxisType.PRODUCT, level=AxisLevel.PRODUCT)],
        sample=[
            SampleCondition(
                type=AxisType.PRODUCT,
                level=AxisLevel.PRODUCT_GROUP,
                value_id="rotativo",
            )
        ],
    )

    execute_calculation(_plan(metric), FakeRepository())


def test_recorte_de_produto_em_contagem_e_aceito() -> None:

    metric = Metric(
        rule_id=RuleId.CUSTOMER_COUNT,
        subjects=[_segment_subject()],
        sample=[
            SampleCondition(
                type=AxisType.PRODUCT,
                level=AxisLevel.PRODUCT_GROUP,
                value_id="rotativo",
            )
        ],
    )

    execute_calculation(_plan(metric), FakeRepository())


def test_total_nao_gera_dimensao_nula() -> None:

    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[Subject(type=AxisType.TOTAL, level=AxisLevel.TOTAL)],
    )
    repo = FakeRepository(
        [
            AggregatedRow(
                subjects={},
                period="2026-09-30",
                components={
                    "numerator": Decimal("10"),
                    "denominator": Decimal("100"),
                },
            )
        ]
    )

    result = execute_calculation(_plan(metric), repo)

    assert result.values[0].subjects == {}
    assert result.values[0].value == Decimal("0.1")


def test_request_leva_subjects_e_sample_ao_port() -> None:

    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[_segment_subject()],
        sample=[
            SampleCondition(
                type=AxisType.CUSTOMER_PRINCIPALITY,
                level=AxisLevel.PRINCIPALITY_DEPTH,
                value_id="high",
            )
        ],
    )
    repo = FakeRepository()

    execute_calculation(_plan(metric), repo)

    request, period = repo.calls[0]

    assert request.rule_id == "profitability"
    assert request.unit == "decimal_rate"
    assert request.temporal_behavior == "ratio"
    assert request.subjects[0].type == "customer_segmentation"
    assert request.subjects[0].level == "segment"
    assert request.sample[0].type == "customer_principality"
    assert request.sample[0].level == "principality_depth"
    assert request.sample[0].value_id == "high"
    assert period == PeriodRequest(
        start="2026-07-01",
        end="2026-09-30",
        type=PeriodType.SERIES,
        grain=Grain.MONTH,
    )


ALL_AXES = sorted(
    (axis, level) for axis, levels in LEVELS_BY_AXIS.items() for level in levels
)


@pytest.mark.parametrize(("axis_type", "level"), ALL_AXES)
def test_todo_eixo_valido_e_aceito(axis_type: AxisType, level: AxisLevel) -> None:

    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[Subject(type=axis_type, level=level)],
    )
    repo = FakeRepository()

    execute_calculation(_plan(metric), repo)

    request, _ = repo.calls[0]

    assert request.subjects[0].type == str(axis_type)
    assert request.subjects[0].level == str(level)


def test_serie_com_uma_data_e_valida() -> None:

    period = _period(start=date(2026, 8, 31), end=date(2026, 8, 31))
    repo = FakeRepository()

    execute_calculation(_plan(_profit_seg_metric(), period), repo)

    assert repo.calls[0][1].type == "series"
    assert repo.calls[0][1].grain == "month"


def test_grao_anual_e_valido() -> None:

    repo = FakeRepository()

    execute_calculation(_plan(_profit_seg_metric(), _period(grain=Grain.YEAR)), repo)

    assert repo.calls[0][1].grain == "year"


def test_grao_total_e_valido() -> None:

    repo = FakeRepository()

    execute_calculation(_plan(_profit_seg_metric(), _period(grain=Grain.TOTAL)), repo)

    assert repo.calls[0][1].grain == "total"


def test_snapshot_valido_exige_datas_iguais() -> None:

    period = _period(
        type_=PeriodType.SNAPSHOT,
        start=date(2026, 8, 31),
        end=date(2026, 8, 31),
    )
    repo = FakeRepository()

    execute_calculation(_plan(_profit_seg_metric(), period), repo)

    assert repo.calls[0][1].type == "snapshot"


def test_metric_id_e_apenas_rotulo() -> None:

    metric = Metric(
        id="m_prof",
        rule_id=RuleId.PROFITABILITY,
        subjects=[_segment_subject()],
    )

    result = execute_calculation(_plan(metric), FakeRepository())

    assert result.calculation_plan_id == "calc1"
    assert result.rule_id == "profitability"


def test_recorte_medio_de_principalidade_e_aceito() -> None:

    metric = Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[_segment_subject()],
        sample=[
            SampleCondition(
                type=AxisType.CUSTOMER_PRINCIPALITY,
                level=AxisLevel.PRINCIPALITY_DEPTH,
                value_id="medium",
            )
        ],
    )

    execute_calculation(_plan(metric), FakeRepository())


@pytest.mark.parametrize(
    ("value_id", "expected"),
    [
        ("low", True),
        ("medium", True),
        ("high", True),
        ("altissima", False),
        ("HIGH", False),
    ],
)
def test_valores_governados_das_profundidades(value_id: str, expected: bool) -> None:

    known = is_known_value(
        AxisType.CUSTOMER_PRINCIPALITY,
        AxisLevel.PRINCIPALITY_DEPTH,
        value_id,
    )

    assert known is expected


def test_contagem_leva_chave_distinta_ao_port() -> None:

    repo = FakeRepository()
    metric = Metric(rule_id=RuleId.CUSTOMER_COUNT, subjects=[_segment_subject()])

    execute_calculation(_plan(metric), repo)

    request, _ = repo.calls[0]

    assert request.aggregation.kind == "distinct"
    assert request.aggregation.distinct_key == "id_cliente"
    assert request.temporal_behavior == "count"


def test_estoque_leva_medida_e_rollup_ao_port() -> None:

    repo = FakeRepository()
    metric = Metric(rule_id=RuleId.OUTSTANDING_BALANCE, subjects=[_segment_subject()])

    execute_calculation(_plan(metric), repo)

    request, _ = repo.calls[0]

    assert request.aggregation.kind == "sum"
    assert request.aggregation.measure == "vl_saldo"
    assert request.temporal_behavior == "stock"


def test_ratio_com_um_componente_nulo_e_ausencia() -> None:

    repo = FakeRepository([_row({"numerator": Decimal("10"), "denominator": None})])

    result = execute_calculation(_plan(_profit_seg_metric()), repo)

    assert result.values[0].value is None


def test_forma_de_agregacao_desconhecida_e_recusada() -> None:

    binding = MetricBinding(
        rule_id=RuleId.PROFITABILITY,
        unit="decimal_rate",
        aggregation=Aggregation(kind="percentil"),
        temporal_behavior="ratio",
    )

    with pytest.raises(CalculationError):
        _combine(binding, {"value": Decimal("1")})


def _total_subject() -> Subject:
    return Subject(type=AxisType.TOTAL, level=AxisLevel.TOTAL)


def test_taxa_composta_le_taxas_do_port_e_anualiza() -> None:
    """A série macro passa a lista de taxas mensais ao Port; o motor compõe os
    fatores e anualiza a taxa efetiva da janela — nunca média nem soma."""

    repo = FakeRepository(
        [
            _row(
                {"rates": (Decimal("0.01"), Decimal("0.02"), Decimal("0.03"))},
                subjects={},
            )
        ]
    )
    metric = Metric(rule_id=RuleId.CDI_RATE, subjects=[_total_subject()])

    result = execute_calculation(_plan(metric), repo)

    request, _ = repo.calls[0]
    effective = Decimal("1.01") * Decimal("1.02") * Decimal("1.03") - 1
    annualized = (Decimal(1) + effective) ** 4 - 1

    assert request.aggregation.kind == "compounded_rate"
    assert request.aggregation.measure == "taxa_mensal"
    assert request.temporal_behavior == "compounded"
    assert result.unit == "decimal_rate"
    assert result.values[0].value == annualized
    assert result.values[0].population is None


def test_taxa_composta_ausente_e_none_nunca_zero() -> None:

    repo = FakeRepository([_row({"rates": None}, subjects={})])
    metric = Metric(rule_id=RuleId.SELIC_RATE, subjects=[_total_subject()])

    result = execute_calculation(_plan(metric), repo)

    assert result.values[0].value is None


def test_taxa_composta_rejeita_eixo_de_negocio_no_motor() -> None:

    metric = Metric(rule_id=RuleId.CDI_RATE, subjects=[_segment_subject()])

    with pytest.raises(InvalidPlanError):
        execute_calculation(_plan(metric), FakeRepository())


def test_taxa_composta_rejeita_sample_no_motor() -> None:

    metric = Metric(
        rule_id=RuleId.INFLATION_IPCA,
        subjects=[_total_subject()],
        sample=[
            SampleCondition(
                type=AxisType.CUSTOMER_PRINCIPALITY,
                level=AxisLevel.PRINCIPALITY_DEPTH,
                value_id="high",
            )
        ],
    )

    with pytest.raises(InvalidPlanError):
        execute_calculation(_plan(metric), FakeRepository())

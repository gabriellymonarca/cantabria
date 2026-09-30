"""Execute a CalculationPlan and produce a CalculationResult.

O plano diz o que medir; o Adapter lê e agrega no armazém; este use case
valida, pede os componentes e combina com a fórmula genérica
(`shared.aggregation`).

Fluxo:
  1. Valida período, métrica, quebras e recorte (erros tipados).
  2. Traduz o plano no MetricRequest semântico.
  3. Pede os componentes ao Port (o banco agrega).
  4. Combina os componentes de cada linha e monta o CalculationResult.

A divisão da razão é a última operação, e acontece AQUI, sobre os componentes
que o banco somou — nunca a média de taxas mensais.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from contexts.financial_calculation.domain.calculation_plan import (
    LEVELS_BY_AXIS,
    AxisLevel,
    AxisType,
    CalculationPlan,
    Grain,
    Metric,
    Period,
    PeriodType,
    is_known_value,
)
from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
    CalculationResultRow,
    Number,
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
    METRIC_BINDINGS,
    MetricBinding,
)
from contexts.financial_calculation.ports.outbound.official_data_repository import (
    AggregatedRow,
    MetricRequest,
    OfficialDataRepository,
    PeriodRequest,
    SampleConditionRequest,
    SubjectRequest,
)
from shared.aggregation import compound_annualized_rate, ratio

_VALID_PERIOD_TYPES = frozenset(PeriodType)
_VALID_GRAINS = frozenset(Grain)

_Axis = tuple[AxisType, AxisLevel]


def execute_calculation(
    plan: CalculationPlan,
    repository: OfficialDataRepository,
) -> CalculationResult:
    """Executa um CalculationPlan validado e produz o CalculationResult."""

    _validate_period(plan.period)
    binding = _validate_metric(plan.metric)

    metric = _to_request(plan.metric, binding)
    period = PeriodRequest(
        start=plan.period.start.isoformat(),
        end=plan.period.end.isoformat(),
        type=str(plan.period.type),
        grain=str(plan.period.grain),
    )

    rows = repository.fetch_aggregated(metric, period)

    return _to_result(plan, binding, rows)


# ---------------------------------------------------------------------------
# 1. Validação (precondição determinística)
# ---------------------------------------------------------------------------
#
# A forma do `Period` (start <= end, snapshot pontual) e da `Metric` (quebra
# obrigatória, sem repetição, `total` sozinho, recorte que não repete quebra)
# é garantida pelos próprios value objects em `domain/calculation_plan.py`.
# Aqui ficam só as regras que dependem do catálogo do motor (bindings, eixos,
# valores governados e a expressabilidade do recorte de produto).


def _validate_period(period: Period) -> None:

    if period.type not in _VALID_PERIOD_TYPES:
        raise InvalidPeriodError(
            f"period.type '{period.type}' inválido (series|snapshot)."
        )

    if period.grain not in _VALID_GRAINS:
        raise UnsupportedGrainError(
            f"grain '{period.grain}' não suportado (month|quarter|year)."
        )


def _validate_metric(metric: Metric) -> MetricBinding:

    binding = METRIC_BINDINGS.get(metric.rule_id)

    if binding is None:
        raise UnknownRuleError(
            f"rule_id '{metric.rule_id}' não pertence ao catálogo de métricas."
        )

    _ensure_macro_shape(metric, binding)

    subjects = [
        _resolve_axis(subject.type, subject.level) for subject in metric.subjects
    ]

    _validate_sample(metric, subjects, binding)

    return binding


def _ensure_macro_shape(metric: Metric, binding: MetricBinding) -> None:
    """Taxa composta é série macro: só `total.total`, sem recorte, no motor.

    `validate_plan` já recusa eixos de negócio com `not_expressible`; esta é a
    guarda do próprio motor, para execução direta (testes/parity) não aceitar
    um recorte escondido.
    """

    if binding.aggregation.kind != "compounded_rate":
        return

    subjects = metric.subjects

    total_only = (
        len(subjects) == 1
        and subjects[0].type is AxisType.TOTAL
        and subjects[0].level is AxisLevel.TOTAL
    )

    if not total_only or metric.sample:
        raise InvalidPlanError(
            f"métrica macro '{metric.rule_id}' só aceita total.total, sem recorte."
        )


def _resolve_axis(axis_type: object, level: object) -> _Axis:

    try:
        axis = AxisType(axis_type)
        grain = AxisLevel(level)
    except ValueError as error:
        raise UnknownAxisError(
            f"eixo '{axis_type}.{level}' fora do catálogo."
        ) from error

    if grain not in LEVELS_BY_AXIS[axis]:
        raise UnknownAxisError(f"eixo '{axis}.{grain}' fora do catálogo.")

    return axis, grain


def _validate_sample(
    metric: Metric,
    subjects: Sequence[_Axis],
    binding: MetricBinding,
) -> None:

    sample: list[_Axis] = []

    for condition in metric.sample:
        axis = _resolve_axis(condition.type, condition.level)

        if axis[0] is AxisType.TOTAL:
            raise UnknownAxisError(
                "'total' não é um recorte válido: não encolhe população nenhuma."
            )

        sample.append(axis)

        if not is_known_value(axis[0], axis[1], condition.value_id):
            raise UnknownValueError(
                f"valor '{condition.value_id}' fora do catálogo de {axis[0]}.{axis[1]}."
            )

    _ensure_product_sample_is_expressible(sample, subjects, binding)


def _ensure_product_sample_is_expressible(
    sample: Sequence[_Axis],
    subjects: Sequence[_Axis],
    binding: MetricBinding,
) -> None:

    has_product_sample = any(axis[0] is AxisType.PRODUCT for axis in sample)

    if not has_product_sample:
        return

    has_product_split = any(axis[0] is AxisType.PRODUCT for axis in subjects)

    if has_product_split or binding.aggregation.kind == "distinct":
        return

    raise InvalidPlanError(
        "recorte de produto sem quebra de produto não é expressável: a medida é "
        "do cliente, e filtrar clientes por produto devolveria o item, não a "
        "carteira dele."
    )


# ---------------------------------------------------------------------------
# 2. Tradução plano -> contrato do Port
# ---------------------------------------------------------------------------


def _to_request(metric: Metric, binding: MetricBinding) -> MetricRequest:

    return MetricRequest(
        rule_id=str(metric.rule_id),
        unit=binding.unit,
        aggregation=binding.aggregation,
        temporal_behavior=binding.temporal_behavior,
        subjects=tuple(
            SubjectRequest(type=str(subject.type), level=str(subject.level))
            for subject in metric.subjects
        ),
        sample=tuple(
            SampleConditionRequest(
                type=str(condition.type),
                level=str(condition.level),
                value_id=condition.value_id,
            )
            for condition in metric.sample
        ),
    )


# ---------------------------------------------------------------------------
# 4. Componentes -> valor (a fórmula genérica é aplicada aqui)
# ---------------------------------------------------------------------------


def _combine(
    binding: MetricBinding,
    components: dict[str, object],
) -> Number | None:

    kind = binding.aggregation.kind

    if kind == "ratio":
        numerator = components.get("numerator")
        denominator = components.get("denominator")

        if numerator is None or denominator is None:
            return None

        return ratio(Decimal(numerator), Decimal(denominator))

    if kind == "compounded_rate":
        rates = components.get("rates")

        if not isinstance(rates, (tuple, list)) or not rates:
            return None

        return compound_annualized_rate(tuple(Decimal(rate) for rate in rates))

    if kind in ("sum", "distinct"):
        return components.get("value")

    raise CalculationError(f"forma de agregação desconhecida: '{kind}'.")


def _population(components: dict[str, object]) -> int | None:
    """Clientes distintos do grupo; ausente na fonte é desconhecido, não 0."""

    population = components.get("population")

    if population is None or isinstance(population, tuple):
        return None

    return int(population)


def _to_result(
    plan: CalculationPlan,
    binding: MetricBinding,
    rows: Sequence[AggregatedRow],
) -> CalculationResult:

    return CalculationResult(
        calculation_plan_id=plan.calculation_plan_id,
        rule_id=str(plan.metric.rule_id),
        unit=binding.unit,
        values=[
            CalculationResultRow(
                subjects=row.subjects,
                period=row.period,
                value=_combine(binding, row.components),
                population=_population(row.components),
            )
            for row in rows
        ],
    )

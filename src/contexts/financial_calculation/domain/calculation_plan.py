from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from contexts.financial_calculation.domain.errors import (
    InvalidPeriodError,
    InvalidPlanError,
    UnknownAxisError,
)


class RuleId(StrEnum):
    """Regra de cálculo: como a métrica é calculada."""

    PROFITABILITY = "profitability"
    OUTSTANDING_BALANCE = "outstanding_balance"
    CONTRACT_COUNT = "contract_count"
    CUSTOMER_COUNT = "customer_count"
    CDI_RATE = "cdi_rate"
    SELIC_RATE = "selic_rate"
    INFLATION_IPCA = "inflation_ipca"


class AxisType(StrEnum):
    """Dimensão semântica de um sujeito ou de um recorte amostral."""

    CUSTOMER_SEGMENTATION = "customer_segmentation"
    CUSTOMER_RELATIONSHIP = "customer_relationship"
    CUSTOMER_PRINCIPALITY = "customer_principality"
    PRODUCT = "product"
    TOTAL = "total"


class AxisLevel(StrEnum):
    """Grão dentro de uma dimensão semântica."""

    PERSON_TYPE = "person_type"
    SEGMENT_GROUP = "segment_group"
    SEGMENT = "segment"
    SUBSEGMENT_GROUP = "subsegment_group"
    SUBSEGMENT = "subsegment"
    RELATIONSHIP_DEPTH = "relationship_depth"
    PRINCIPALITY_DEPTH = "principality_depth"
    PRODUCT_GROUP = "product_group"
    PRODUCT = "product"
    SUBPRODUCT = "subproduct"
    TOTAL = "total"


LEVELS_BY_AXIS: dict[AxisType, frozenset[AxisLevel]] = {
    AxisType.CUSTOMER_SEGMENTATION: frozenset(
        {
            AxisLevel.PERSON_TYPE,
            AxisLevel.SEGMENT_GROUP,
            AxisLevel.SEGMENT,
            AxisLevel.SUBSEGMENT_GROUP,
            AxisLevel.SUBSEGMENT,
        }
    ),
    AxisType.CUSTOMER_RELATIONSHIP: frozenset({AxisLevel.RELATIONSHIP_DEPTH}),
    AxisType.CUSTOMER_PRINCIPALITY: frozenset({AxisLevel.PRINCIPALITY_DEPTH}),
    AxisType.PRODUCT: frozenset(
        {
            AxisLevel.PRODUCT_GROUP,
            AxisLevel.PRODUCT,
            AxisLevel.SUBPRODUCT,
        }
    ),
    AxisType.TOTAL: frozenset({AxisLevel.TOTAL}),
}

# value_ids governados por eixo, quando enumeráveis. Eixos sem conjunto
# enumerado aqui (segmento, produto) aceitam o id resolvido pelo catálogo
# semântico de origem, que é validado no contexto de análise.
VALUE_IDS: dict[tuple[AxisType, AxisLevel], frozenset[str]] = {
    (AxisType.CUSTOMER_PRINCIPALITY, AxisLevel.PRINCIPALITY_DEPTH): frozenset(
        {"low", "medium", "high"}
    ),
    (AxisType.CUSTOMER_RELATIONSHIP, AxisLevel.RELATIONSHIP_DEPTH): frozenset(
        {"low", "medium", "high"}
    ),
}


def is_known_value(axis: AxisType, level: AxisLevel, value_id: str) -> bool:
    """True se o valor pertence ao conjunto governado, quando ele é enumerado."""

    allowed = VALUE_IDS.get((axis, level))

    return allowed is None or value_id in allowed


class PeriodType(StrEnum):
    SERIES = "series"
    SNAPSHOT = "snapshot"


class Grain(StrEnum):
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"
    TOTAL = "total"


@dataclass(frozen=True)
class Subject:
    """A quebra (GROUP BY): cada sujeito vira exatamente uma linha do resultado."""

    type: AxisType
    level: AxisLevel


@dataclass(frozen=True)
class SampleCondition:
    """Condição do campo amostral (WHERE): encolhe quem entra, sem virar linha."""

    type: AxisType
    level: AxisLevel
    value_id: str


@dataclass(frozen=True)
class Metric:
    """O que medir, sobre quem medir (`subjects`) e em que universo (`sample`).

    Invariantes de forma (uma casa só, aqui): há ao menos uma quebra; nenhuma
    quebra se repete; `total` é a ausência de quebra e anda sozinho; um recorte
    não repete uma quebra nem aparece duas vezes.
    """

    rule_id: RuleId
    subjects: tuple[Subject, ...]
    sample: tuple[SampleCondition, ...] = field(default_factory=tuple)
    id: str | None = None

    def __post_init__(self) -> None:

        object.__setattr__(self, "subjects", tuple(self.subjects))
        object.__setattr__(self, "sample", tuple(self.sample))

        if not self.subjects:
            raise InvalidPlanError(
                "metric.subjects não pode ser vazio; sem quebra use total.total."
            )

        keys = [(subject.type, subject.level) for subject in self.subjects]

        if len(set(keys)) != len(keys):
            raise InvalidPlanError("quebra repetida no mesmo plano.")

        if len(keys) > 1 and any(axis is AxisType.TOTAL for axis, _ in keys):
            raise InvalidPlanError(
                "'total' não pode ser combinado com outra quebra: ele é a ausência de quebra."
            )

        _ensure_sample_shape(self.sample, keys)


def _ensure_sample_shape(
    sample: tuple[SampleCondition, ...],
    breakdown_keys: list[tuple[AxisType, AxisLevel]],
) -> None:

    seen: set[tuple[AxisType, AxisLevel]] = set()

    for condition in sample:
        axis = (condition.type, condition.level)

        if axis in breakdown_keys:
            raise UnknownAxisError(
                f"o recorte '{axis[0]}.{axis[1]}' repete uma quebra do plano."
            )

        if axis in seen:
            raise InvalidPlanError(
                f"o recorte '{axis[0]}.{axis[1]}' aparece duas vezes no plano."
            )

        seen.add(axis)


@dataclass(frozen=True)
class Period:
    """A janela de tempo: intervalo, forma (`series`/`snapshot`) e grão.

    Invariantes: `start <= end`; uma foto (`snapshot`) é um único instante,
    logo `start == end`. Datas em ISO são aceitas e normalizadas para `date`.
    """

    start: date
    end: date
    type: PeriodType
    grain: Grain

    def __post_init__(self) -> None:

        object.__setattr__(self, "start", _as_date(self.start))
        object.__setattr__(self, "end", _as_date(self.end))

        if self.start > self.end:
            raise InvalidPeriodError(
                f"period.start ({self.start}) posterior a period.end ({self.end})."
            )

        if self.type == PeriodType.SNAPSHOT and self.start != self.end:
            raise InvalidPeriodError(
                "snapshot exige start == end: uma foto é um único instante."
            )


def _as_date(value: date | str) -> date:

    if isinstance(value, date):
        return value

    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise InvalidPeriodError(f"data '{value}' não é ISO (YYYY-MM-DD).") from error


@dataclass(frozen=True)
class CalculationPlan:
    """Uma métrica sobre um período. O id do plano é a referência da série."""

    calculation_plan_id: str
    metric: Metric
    period: Period

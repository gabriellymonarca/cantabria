"""O catálogo semântico como objeto tipado — a única autoridade do plano.

O YAML versionado (fora de `src/`) é compilado neste grafo: métricas, eixos,
valores, janelas e a matriz de compatibilidade. `create_plan` e `validate_plan`
consomem o mesmo objeto.

Pertencimento é travessia: a métrica existe? o eixo existe e tem esse nível? o
`value_id` pertence ao nível? a janela está na vigência? O caminho percorrido é
a justificativa auditável do plano.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from contexts.financial_analysis.domain.errors import InvalidCatalogError


class MetricShape(StrEnum):
    """Forma de agregação da métrica: como ela (não) se soma."""

    RATIO = "ratio"
    STOCK = "stock"
    COUNT = "count"


class AxisKind(StrEnum):
    """Eixo sem ordem natural (`nominal`) ou com ordem (`ordinal`)."""

    NOMINAL = "nominal"
    ORDINAL = "ordinal"


class Requirement(StrEnum):
    """Exigência estrutural de um método sobre o resultado."""

    SERIES = "series"
    COLLAPSED_RESULT = "collapsed_result"
    ORDINAL_AXIS = "ordinal_axis"


class CompatibilitySource(StrEnum):
    """De onde o método lê os valores."""

    CALCULATION_PLAN_IDS = "calculation_plan_ids"
    STATISTIC_REFS = "statistic_refs"


class SameField(StrEnum):
    """O que as fontes de um método precisam ter em comum."""

    RULE_ID = "rule_id"
    SUBJECTS = "subjects"
    SAMPLE = "sample"


class WindowRequirement(StrEnum):
    """Exigência temporal entre as janelas de um método."""

    DISJOINT_EQUAL_DURATION = "disjoint_equal_duration"


@dataclass(frozen=True)
class MetricEntry:
    """Uma métrica do catálogo: id, forma, unidade e sinônimos.

    `macro` marca a série escalar macro (CDI/SELIC/IPCA): ela só faz sentido no
    grão `total.total`, sem `sample`; `validate_plan` recusa eixos de negócio
    com `not_expressible`.
    """

    rule_id: str
    shape: MetricShape
    unit: str
    synonyms: tuple[str, ...] = ()
    macro: bool = False


@dataclass(frozen=True)
class AxisEntry:
    """Um eixo (dimensão + nível) e seu tipo."""

    type: str
    level: str
    kind: AxisKind
    synonyms: tuple[str, ...] = ()
    parent_level: str | None = None

    @property
    def key(self) -> str:
        return f"{self.type}.{self.level}"


@dataclass(frozen=True)
class ValueEntry:
    """Um `value_id` governado de um eixo enumerável."""

    type: str
    level: str
    value_id: str
    labels: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.type}.{self.level}={self.value_id}"


@dataclass(frozen=True)
class WindowEntry:
    """Uma janela nomeada: definição, forma e grão de referência."""

    id: str
    kind: str
    type: str
    grain: str
    labels: tuple[str, ...] = ()
    months: int | None = None


@dataclass(frozen=True)
class MethodCompatibility:
    """Regras de um método contra a forma da métrica e o resultado."""

    method: str
    requires_metric_shape: tuple[MetricShape, ...] = ()
    forbids_metric_shape: tuple[MetricShape, ...] = ()
    requires: tuple[Requirement, ...] = ()
    requires_any: tuple[Requirement, ...] = ()
    reads: CompatibilitySource | None = None
    count: int | None = None
    same: tuple[SameField, ...] = ()
    windows: WindowRequirement | None = None
    min_points: int | None = None
    min_levels: int | None = None
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class OperationCompatibility:
    """Regras de uma operação: params, fontes e restrições."""

    operation: str
    requires_params: tuple[str, ...] = ()
    count: int | None = None
    requires_source: tuple[str, ...] = ()
    forbidden_rules_metric_shape: Mapping[str, MetricShape] = field(
        default_factory=dict
    )
    params_when: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NotConfusePair:
    """Dois termos parecidos que não são sinônimos."""

    term_a: str
    term_b: str
    note: str | None = None


@dataclass(frozen=True)
class SemanticCatalog:
    """O grafo do catálogo, imutável, de uma versão."""

    catalog_version: str
    locale: str
    reference_date: date
    window_start: date
    window_end: date
    metrics: tuple[MetricEntry, ...] = ()
    axes: tuple[AxisEntry, ...] = ()
    values: tuple[ValueEntry, ...] = ()
    windows: tuple[WindowEntry, ...] = ()
    period_defaults: Mapping[str, str] = field(default_factory=dict)
    methods: tuple[MethodCompatibility, ...] = ()
    operations: tuple[OperationCompatibility, ...] = ()
    not_confuse: tuple[NotConfusePair, ...] = ()

    def __post_init__(self) -> None:

        _ensure_unique([entry.rule_id for entry in self.metrics], "métrica")
        _ensure_unique([entry.key for entry in self.axes], "eixo")
        _ensure_unique([entry.key for entry in self.values], "valor")
        _ensure_unique([entry.id for entry in self.windows], "janela")
        _ensure_unique([entry.method for entry in self.methods], "método")
        _ensure_unique([entry.operation for entry in self.operations], "operação")

        axis_keys = {entry.key for entry in self.axes}

        for value in self.values:
            if f"{value.type}.{value.level}" not in axis_keys:
                raise InvalidCatalogError(
                    f"valor '{value.key}' aponta para eixo inexistente."
                )

        metric_ids = {entry.rule_id for entry in self.metrics}

        if not metric_ids:
            raise InvalidCatalogError("catálogo sem métricas.")

    def metric(self, rule_id: str) -> MetricEntry | None:

        return next(
            (entry for entry in self.metrics if entry.rule_id == rule_id),
            None,
        )

    def axis(self, axis_type: str, level: str) -> AxisEntry | None:

        return next(
            (
                entry
                for entry in self.axes
                if entry.type == axis_type and entry.level == level
            ),
            None,
        )

    def value(self, axis_type: str, level: str, value_id: str) -> ValueEntry | None:

        return next(
            (
                entry
                for entry in self.values
                if entry.type == axis_type
                and entry.level == level
                and entry.value_id == value_id
            ),
            None,
        )

    def window(self, window_id: str) -> WindowEntry | None:

        return next(
            (entry for entry in self.windows if entry.id == window_id),
            None,
        )

    def method_rule(self, method: str) -> MethodCompatibility | None:

        return next(
            (entry for entry in self.methods if entry.method == method),
            None,
        )

    def operation_rule(self, operation: str) -> OperationCompatibility | None:

        return next(
            (entry for entry in self.operations if entry.operation == operation),
            None,
        )

    def is_ordinal(self, axis_type: str, level: str) -> bool:

        entry = self.axis(axis_type, level)

        return entry is not None and entry.kind is AxisKind.ORDINAL


def _ensure_unique(keys: list[str], kind: str) -> None:

    seen: set[str] = set()

    for key in keys:
        if key in seen:
            raise InvalidCatalogError(f"{kind} repetida no catálogo: '{key}'.")

        seen.add(key)

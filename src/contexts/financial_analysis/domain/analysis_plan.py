from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from contexts.financial_analysis.domain.errors import (
    AmbiguousMethodSourceError,
    CyclicReferenceError,
    DuplicateIdError,
    InvalidPresentationError,
    UnresolvedReferenceError,
)


class StatisticalMethodType(StrEnum):
    """Catálogo fechado de métodos: cada um diz qual quantidade produzir."""

    NULL = "null"
    MEAN = "mean"
    MEDIAN = "median"
    MODE = "mode"
    STD = "std"
    DISPERSION = "dispersion"
    VARIATION = "variation"
    TREND = "trend"
    SHARE = "share"
    CORRELATION = "correlation"
    OUTLIER = "outlier"


class OperationType(StrEnum):
    """Catálogo fechado de operações: organizam o número pronto."""

    RANKING = "ranking"
    COMPARISON = "comparison"
    CUMULATIVE_SHARE = "cumulative_share"
    SELECTION = "selection"
    PIVOT = "pivot"
    DECOMPOSITION = "decomposition"


class RankOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class RankAxis(StrEnum):
    ENTITY = "entity"
    PERIOD = "period"


class ComparisonAcross(StrEnum):
    ENTITY = "entity"
    RESULT = "result"


class SelectionRule(StrEnum):
    ABOVE_MEAN = "above_mean"
    BELOW_MEAN = "below_mean"
    TOP_PERCENT = "top_percent"


class PresentationType(StrEnum):
    """Catálogo fechado de formas de apresentação do resultado."""

    BAR = "bar"
    LINE = "line"
    RANKING_BAR = "ranking_bar"
    TABLE = "table"


class PresentationAxis(StrEnum):
    """O eixo que a apresentação põe na horizontal (categorias ou tempo)."""

    ENTITY = "entity"
    PERIOD = "period"


_MAX_TITLE_CHARS = 120

# Ids internos que nunca devem vazar para um título mostrado ao usuário:
# planos (`plan_x`, `calc_x`), métodos/operações (`s1`, `o2`), chaves
# qualificadas (`customer_segmentation.segment`) e nomes de campos.
_MARKUP_PATTERN = re.compile(r"<[^>]*>")
_INTERNAL_TITLE_PATTERN = re.compile(
    r"\bcalc_[A-Za-z0-9_]+\b"
    r"|\bplan_[A-Za-z0-9_]+\b"
    r"|\b[som]\d+\b"
    r"|\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\b"
    r"|\b(?:analysis_plan_id|catalog_version|dataset_version|trace_id)\b"
)


@dataclass(frozen=True)
class Presentation:
    """Como mostrar o resultado: a forma de apresentação.

    Catálogo fechado — `type`: `bar` (poucas entidades), `line` (série
    temporal; exige `axis: period`), `ranking_bar` (ranking) ou `table`
    (default); `axis`: `entity` (categorias) ou `period` (tempo); `title`:
    frase curta ao usuário, sem ids internos. Uma apresentação incompatível
    com o plano degrada para `table`.
    """

    type: PresentationType = PresentationType.TABLE
    axis: PresentationAxis = PresentationAxis.ENTITY
    title: str = ""

    def __post_init__(self) -> None:

        presentation_type = _catalog_member(PresentationType, self.type, "type")
        axis = _catalog_member(PresentationAxis, self.axis, "axis")

        if (
            presentation_type is PresentationType.LINE
            and axis is not PresentationAxis.PERIOD
        ):
            raise InvalidPresentationError("presentation 'line' exige axis 'period'.")

        object.__setattr__(self, "type", presentation_type)
        object.__setattr__(self, "axis", axis)
        object.__setattr__(self, "title", _business_title(self.title))


def safe_presentation(
    presentation_type: object = None,
    axis: object = None,
    title: object = None,
) -> Presentation:
    """Apresentação válida para o resultado: qualquer valor fora do catálogo
    degrada para `table`, de forma determinística.

    Campo ausente (`None`) vale o default do próprio value object: `table`,
    `entity` e título vazio. A apresentação é cosmética; uma proposta inválida
    do LLM não pode derrubar o plano inteiro nem gastar um retry — o usuário
    ainda quer os números verificados."""

    try:
        return Presentation(  # type: ignore[arg-type]
            type=(
                PresentationType.TABLE
                if presentation_type is None
                else presentation_type
            ),
            axis=PresentationAxis.ENTITY if axis is None else axis,
            title="" if title is None else title,
        )
    except InvalidPresentationError:
        return Presentation()


def _catalog_member[Member: StrEnum](
    options: type[Member],
    value: object,
    field: str,
) -> Member:

    if isinstance(value, options):
        return value

    if isinstance(value, str):
        try:
            return options(value)
        except ValueError:
            pass

    raise InvalidPresentationError(f"presentation.{field} fora do catálogo: {value!r}.")


def _business_title(title: object) -> str:

    if not isinstance(title, str):
        raise InvalidPresentationError("presentation.title deve ser texto.")

    # Título é texto do LLM exibido na UI: tira marcação/controle para não
    # virar HTML no gráfico (a checagem de lastro dos números é feita no
    # builder, contra o resultado do turno).
    cleaned = _MARKUP_PATTERN.sub("", title)
    cleaned = "".join(char for char in cleaned if char.isprintable())
    cleaned = " ".join(cleaned.split())

    if len(cleaned) > _MAX_TITLE_CHARS:
        raise InvalidPresentationError(
            f"presentation.title excede {_MAX_TITLE_CHARS} caracteres."
        )

    if _INTERNAL_TITLE_PATTERN.search(cleaned):
        raise InvalidPresentationError(
            "presentation.title não pode citar ids internos do plano."
        )

    return cleaned


@dataclass(frozen=True)
class StatisticalMethod:
    """Um método lê `calculation_plan_ids` ou `statistic_refs`, nunca os dois."""

    id: str
    method: StatisticalMethodType
    calculation_plan_ids: tuple[str, ...] = field(default_factory=tuple)
    statistic_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:

        object.__setattr__(
            self, "calculation_plan_ids", tuple(self.calculation_plan_ids)
        )
        object.__setattr__(self, "statistic_refs", tuple(self.statistic_refs))


@dataclass(frozen=True)
class Operation:
    """Organiza o resultado referenciado em `refs`; `params` depende do `type`."""

    id: str
    type: OperationType
    refs: tuple[str, ...]
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:

        object.__setattr__(self, "refs", tuple(self.refs))


@dataclass(frozen=True)
class AnalysisPlan:
    """Como associar os números: métodos estatísticos e operações."""

    id: str
    statistical_method: tuple[StatisticalMethod, ...]
    operations: tuple[Operation, ...] = field(default_factory=tuple)
    presentation: Presentation | None = None

    def __post_init__(self) -> None:

        object.__setattr__(self, "statistical_method", tuple(self.statistical_method))
        object.__setattr__(self, "operations", tuple(self.operations))

        if self.presentation is not None and not isinstance(
            self.presentation, Presentation
        ):
            raise InvalidPresentationError(
                "presentation precisa ser um Presentation ou None."
            )

        _ensure_unique_ids(
            [method.id for method in self.statistical_method],
            "statistical_method",
        )
        _ensure_unique_ids(
            [operation.id for operation in self.operations],
            "operation",
        )

        method_ids = {method.id for method in self.statistical_method}

        for method in self.statistical_method:
            _ensure_single_source(method)
            _ensure_refs_resolve(method.statistic_refs, method_ids, method.id)

        for operation in self.operations:
            _ensure_refs_resolve(operation.refs, method_ids, operation.id)

        _ensure_acyclic(self.statistical_method)


def _ensure_unique_ids(ids: list[str], kind: str) -> None:

    seen: set[str] = set()

    for identifier in ids:
        if identifier in seen:
            raise DuplicateIdError(f"{kind} repete o id '{identifier}'.")

        seen.add(identifier)


def _ensure_single_source(method: StatisticalMethod) -> None:

    has_calculation = bool(method.calculation_plan_ids)
    has_statistic = bool(method.statistic_refs)

    if has_calculation == has_statistic:
        raise AmbiguousMethodSourceError(
            f"statistical_method '{method.id}' precisa ler calculation_plan_ids "
            "ou statistic_refs, nunca os dois nem nenhum."
        )


def _ensure_refs_resolve(
    refs: Sequence[str], declared: set[str], owner_id: str
) -> None:

    for ref in refs:
        if ref not in declared:
            raise UnresolvedReferenceError(
                f"'{owner_id}' referencia '{ref}', que não foi declarado no plano."
            )


def _ensure_acyclic(methods: Sequence[StatisticalMethod]) -> None:

    edges = {method.id: method.statistic_refs for method in methods}
    visited: set[str] = set()
    in_path: set[str] = set()

    for method_id in edges:
        _walk(method_id, edges, visited, in_path)


def _walk(
    node: str,
    edges: dict[str, Sequence[str]],
    visited: set[str],
    in_path: set[str],
) -> None:

    if node in visited:
        return

    if node in in_path:
        raise CyclicReferenceError(
            f"statistic_refs formam um ciclo a partir de '{node}'."
        )

    in_path.add(node)

    for target in edges.get(node, []):
        _walk(target, edges, visited, in_path)

    in_path.discard(node)
    visited.add(node)

"""Artefatos determinísticos: figura Plotly e tabela do resultado verificado.

O LLM escolhe a forma (`AnalysisPlan.presentation`); os números vêm do
`AnalysisResult` verificado, sem agregação, arredondamento ou linha `undefined`
plotada. O título proposto pelo LLM é o único texto do artefato e passa pela
mesma checagem de lastro do redator: se citar número fora do resultado, só o
título cai. O conteúdo é montado em estruturas que o Plotly e o pandas
serializam no último passo; o `Decimal` só vira `float`/texto no renderizador
da UI.

O `location` do `ArtifactRef` é `derived://analysis-result/<artifact>`: o
artefato é reproduzível a partir do resultado.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

import structlog

from contexts.financial_analysis.domain.analysis_plan import (
    OperationType,
    Presentation,
    PresentationAxis,
    PresentationType,
)
from contexts.financial_analysis.domain.analysis_result import (
    AnalysisResult,
    MethodResult,
    MethodValue,
    OperationResult,
    OperationValue,
)
from contexts.financial_analysis.domain.artifacts import ArtifactKind, ArtifactRef
from contexts.financial_analysis.domain.insight_presentation import (
    InsightNumberError,
    display_unit,
    entity_label,
    method_label,
    validate_insight_numbers,
    value_key_label,
)
from contexts.financial_analysis.ports.inbound.user_request import Dataframe, Plotly
from contexts.financial_analysis.ports.outbound.artifact_builder_port import (
    ArtifactBuilderPort,
    ArtifactBundle,
)

logger = structlog.get_logger(__name__)

_LOCATION_PREFIX = "derived://analysis-result"
_TABLE_COLUMNS = ("Entidade", "Período", "Método", "Valor", "Unidade")
_AXIS_LABELS = {
    PresentationAxis.ENTITY: "Entidade",
    PresentationAxis.PERIOD: "Período",
}
_EMPTY = "—"
_CHART_KEYS = ("value", "absolute", "contribution")


@dataclass(frozen=True)
class _Trace:
    """Uma série do gráfico: nome opcional e pontos (eixo × número)."""

    name: str | None
    x: tuple[str, ...]
    y: tuple[Decimal | int, ...]


@dataclass(frozen=True)
class _Chart:
    """O gráfico montado a partir do resultado, antes de virar figura."""

    kind: PresentationType
    x_label: str
    y_label: str
    traces: tuple[_Trace, ...]


class PlotlyArtifactBuilder(ArtifactBuilderPort):
    """Constrói a tabela e a figura Plotly a partir do resultado verificado."""

    def build(
        self,
        trace_id: str,
        result: AnalysisResult,
        presentation: Presentation | None,
    ) -> ArtifactBundle:

        if presentation is None:
            return ArtifactBundle()

        presentation = _grounded_presentation(presentation, result)

        contents: list[Dataframe | Plotly] = []
        refs: list[ArtifactRef] = []
        dataframe = _table_content(result)

        if dataframe is not None:
            contents.append(dataframe)
            refs.append(_artifact_ref(trace_id, ArtifactKind.TABLE))

        chart = _chart(result, presentation)

        if chart is not None:
            contents.append(Plotly(figure=_figure(chart, presentation.title)))
            refs.append(_artifact_ref(trace_id, ArtifactKind.CHART))

        return ArtifactBundle(contents=tuple(contents), refs=tuple(refs))


def _grounded_presentation(
    presentation: Presentation, result: AnalysisResult
) -> Presentation:
    """O título do LLM passa pela mesma checagem de lastro do texto.

    Um número fora do resultado derruba só o título; os números verificados
    continuam plotados.
    """

    if not presentation.title:
        return presentation

    try:
        validate_insight_numbers(presentation.title, result)
    except InsightNumberError as error:
        logger.warning(
            "Artifact title cited unverified numbers; dropping it",
            numbers=list(error.numbers),
        )

        return replace(presentation, title="")

    return presentation


def _artifact_ref(trace_id: str, kind: ArtifactKind) -> ArtifactRef:
    """Ref determinística: o conteúdo é reproduzível do resultado do turno."""

    artifact_id = f"art-{trace_id}-{kind.value}"

    return ArtifactRef(
        artifact_id=artifact_id,
        kind=kind,
        location=f"{_LOCATION_PREFIX}/{artifact_id}",
    )


def _table_content(result: AnalysisResult) -> Dataframe | None:
    """Tabela dos números definidos, linha a linha de método (sem undefined)."""

    rows: list[list[Any]] = []

    for method in result.statistical_method:
        for row in method.values:
            rows.extend(_table_rows(method, row))

    if not rows:
        return None

    return Dataframe(columns=list(_TABLE_COLUMNS), rows=rows)


def _table_rows(method: MethodResult, row: MethodValue) -> list[list[Any]]:

    if row.undefined is not None:
        return []

    numbers = [
        (key, number)
        for key, number in sorted(row.values.items())
        if number is not None
    ]

    return [
        [
            entity_label(row.subjects),
            row.period or _EMPTY,
            _method_cell(method, key, len(numbers)),
            number,
            display_unit(method.unit, key=key) or _EMPTY,
        ]
        for key, number in numbers
    ]


def _method_cell(method: MethodResult, key: str, number_count: int) -> str:

    label = method_label(method.method)

    if number_count > 1:
        return f"{label} ({value_key_label(key)})"

    return label


def _chart(result: AnalysisResult, presentation: Presentation) -> _Chart | None:

    if presentation.type is PresentationType.LINE:
        return _line_chart(result)

    if presentation.type is PresentationType.RANKING_BAR:
        return _ranking_chart(result, presentation)

    if presentation.type is PresentationType.BAR:
        return _bar_chart(result, presentation)

    return None


def _line_chart(result: AnalysisResult) -> _Chart | None:

    for method in result.statistical_method:
        series = _series_points(method)

        if not series:
            continue

        return _Chart(
            kind=PresentationType.LINE,
            x_label=_AXIS_LABELS[PresentationAxis.PERIOD],
            y_label=display_unit(method.unit) or "Valor",
            traces=tuple(
                _Trace(
                    name=label,
                    x=tuple(period for period, _ in points),
                    y=tuple(number for _, number in points),
                )
                for label, points in sorted(series.items())
            ),
        )

    return None


def _series_points(
    method: MethodResult,
) -> dict[str, list[tuple[str, Decimal | int]]]:
    """Pontos por entidade (uma linha por entidade no gráfico de série)."""

    series: dict[str, list[tuple[str, Decimal | int]]] = {}

    for row in method.values:
        number = _row_number(row)

        if number is None or row.period is None:
            continue

        series.setdefault(entity_label(row.subjects), []).append((row.period, number))

    return {label: sorted(points) for label, points in series.items()}


def _bar_chart(result: AnalysisResult, presentation: Presentation) -> _Chart | None:

    for method in result.statistical_method:
        points = _unique_axis_points(method, presentation.axis)

        if not points:
            continue

        labels, numbers = points

        return _Chart(
            kind=PresentationType.BAR,
            x_label=_AXIS_LABELS[presentation.axis],
            y_label=display_unit(method.unit) or "Valor",
            traces=(_Trace(name=None, x=tuple(labels), y=tuple(numbers)),),
        )

    return None


def _unique_axis_points(
    method: MethodResult,
    axis: PresentationAxis,
) -> tuple[list[str], list[Decimal | int]] | None:
    """Pontos por rótulo do eixo; rótulo repetido tornaria o bar ambíguo.

    Série por entidade (vários períodos na mesma entidade) não vira bar
    simples: a matriz de pontos só é plotável quando o eixo escolhido tem um
    valor definido por rótulo."""

    seen: set[str] = set()
    labels: list[str] = []
    numbers: list[Decimal | int] = []

    for row in method.values:
        number = _row_number(row)

        if number is None:
            continue

        label = _axis_label(row, axis)

        if label is None or label in seen:
            return None

        seen.add(label)
        labels.append(label)
        numbers.append(number)

    return (labels, numbers) if labels else None


def _ranking_chart(
    result: AnalysisResult,
    presentation: Presentation,
) -> _Chart | None:

    for operation in result.operations:
        if operation.type != str(OperationType.RANKING):
            continue

        points = _ranked_points(operation, presentation.axis)

        if not points:
            continue

        labels, numbers = points

        return _Chart(
            kind=PresentationType.RANKING_BAR,
            x_label=display_unit(operation.unit) or "Valor",
            y_label=_AXIS_LABELS[presentation.axis],
            traces=(_Trace(name=None, x=tuple(labels), y=tuple(numbers)),),
        )

    return None


def _ranked_points(
    operation: OperationResult,
    axis: PresentationAxis,
) -> tuple[list[str], list[Decimal | int]] | None:

    entries: list[tuple[int, str, Decimal | int]] = []

    for row in operation.values:
        number = _row_number(row)
        label = _axis_label(row, axis)

        if row.rank is None or number is None or label is None:
            continue

        entries.append((row.rank, label, number))

    if not entries:
        return None

    entries.sort(key=lambda entry: entry[0])
    labels = [label for _, label, _ in entries]

    if len(set(labels)) != len(labels):
        return None

    return labels, [number for _, _, number in entries]


def _row_number(row: MethodValue | OperationValue) -> Decimal | int | None:
    """O número plotável da linha; `undefined` e medida ausente não plotam."""

    if row.undefined is not None:
        return None

    for key in _CHART_KEYS:
        number = row.values.get(key)

        if number is not None:
            return number

    return None


def _axis_label(
    row: MethodValue | OperationValue,
    axis: PresentationAxis,
) -> str | None:

    if axis is PresentationAxis.PERIOD:
        return row.period

    return entity_label(row.subjects)


def _figure(chart: _Chart, title: str) -> dict[str, Any]:

    data = [_trace_figure(trace, chart.kind) for trace in chart.traces]
    layout: dict[str, Any] = {
        "xaxis": {"title": {"text": chart.x_label}},
        "yaxis": {"title": {"text": chart.y_label}},
    }

    if title:
        layout["title"] = {"text": title}

    return {"data": data, "layout": layout}


def _trace_figure(trace: _Trace, kind: PresentationType) -> dict[str, Any]:

    horizontal = kind is PresentationType.RANKING_BAR
    figure: dict[str, Any] = {}

    if horizontal:
        figure["x"] = list(trace.y)
        figure["y"] = list(trace.x)
        figure["orientation"] = "h"
    else:
        figure["x"] = list(trace.x)
        figure["y"] = list(trace.y)

    if trace.name is not None:
        figure["name"] = trace.name

    if kind is PresentationType.LINE:
        figure["type"] = "scatter"
        figure["mode"] = "lines+markers"
    else:
        figure["type"] = "bar"

    return figure

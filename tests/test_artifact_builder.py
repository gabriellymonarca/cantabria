"""Artefatos determinísticos: só números do `AnalysisResult`, sem undefined.

O LLM escolhe a forma; o adapter monta a
tabela e a figura copiando valores verificados — nenhuma agregação, nenhum
arredondamento, nenhuma linha `undefined` plotada. O `location` do ref declara
que o artefato é reproduzível do resultado.
"""

from __future__ import annotations

from decimal import Decimal

from contexts.financial_analysis.adapters.outbound.plotly_artifact_builder import (
    PlotlyArtifactBuilder,
)
from contexts.financial_analysis.domain.analysis_plan import (
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
    UndefinedReason,
)
from contexts.financial_analysis.domain.artifacts import ArtifactKind
from contexts.financial_analysis.ports.inbound.user_request import Dataframe, Plotly

SEGMENT = "customer_segmentation.segment"
TABLE = Presentation(
    type=PresentationType.TABLE,
    axis=PresentationAxis.ENTITY,
    title="Rentabilidade por segmento",
)


def _snapshot_result() -> AnalysisResult:

    return AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v3",
        dataset_version="2026-08-31",
        trace_id="t1",
        statistical_method=[
            MethodResult(
                id="s1",
                method="null",
                unit="decimal_rate",
                rule_id="profitability",
                values=[
                    MethodValue(
                        {SEGMENT: "Varejo PF"},
                        {"value": Decimal("0.12")},
                        period="2026-08-31",
                    ),
                    MethodValue(
                        {SEGMENT: "Atacado PJ"},
                        {"value": Decimal("0.08")},
                        period="2026-08-31",
                    ),
                    MethodValue(
                        {SEGMENT: "Private"},
                        {},
                        UndefinedReason.SMALL_CELL,
                        "2026-08-31",
                    ),
                ],
            )
        ],
    )


def _series_result() -> AnalysisResult:

    rows = [
        ("Varejo PF", "2025-09-30", "0.10"),
        ("Varejo PF", "2025-10-31", "0.12"),
        ("Atacado PJ", "2025-09-30", "0.07"),
        ("Atacado PJ", "2025-10-31", "0.08"),
    ]

    return AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v3",
        dataset_version="2026-08-31",
        trace_id="t2",
        statistical_method=[
            MethodResult(
                id="s1",
                method="null",
                unit="decimal_rate",
                rule_id="profitability",
                values=[
                    MethodValue(
                        {SEGMENT: entity},
                        {"value": Decimal(number)},
                        period=period,
                    )
                    for entity, period, number in rows
                ],
            )
        ],
    )


def _ranking_result() -> AnalysisResult:

    return AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v3",
        dataset_version="2026-08-31",
        trace_id="t3",
        statistical_method=[
            MethodResult(
                id="s1",
                method="null",
                unit="decimal_rate",
                rule_id="profitability",
                values=[
                    MethodValue(
                        {SEGMENT: "Varejo PF"},
                        {"value": Decimal("0.12")},
                        period="2026-08-31",
                    ),
                    MethodValue(
                        {SEGMENT: "Atacado PJ"},
                        {"value": Decimal("0.08")},
                        period="2026-08-31",
                    ),
                ],
            )
        ],
        operations=[
            OperationResult(
                id="o1",
                type="ranking",
                refs=["s1"],
                unit="decimal_rate",
                rule_id="profitability",
                values=[
                    OperationValue(
                        {SEGMENT: "Varejo PF"},
                        {"value": Decimal("0.12")},
                        rank=1,
                        period="2026-08-31",
                    ),
                    OperationValue(
                        {SEGMENT: "Private"},
                        {},
                        rank=3,
                        undefined=UndefinedReason.SMALL_CELL,
                    ),
                    OperationValue(
                        {SEGMENT: "Atacado PJ"},
                        {"value": Decimal("0.08")},
                        rank=2,
                        period="2026-08-31",
                    ),
                ],
            )
        ],
    )


def _result_numbers(result: AnalysisResult) -> set[Decimal | int]:
    """Todos os números verificados do resultado, métodos e operações."""

    numbers: set[Decimal | int] = set()

    for method in result.statistical_method:
        for row in method.values:
            if row.undefined is None:
                numbers.update(
                    number for number in row.values.values() if number is not None
                )

    for operation in result.operations:
        for row in operation.values:
            if row.undefined is None:
                numbers.update(
                    number for number in row.values.values() if number is not None
                )

    return numbers


def test_sem_apresentacao_nao_gera_conteudo_nem_ref() -> None:

    bundle = PlotlyArtifactBuilder().build("t1", _snapshot_result(), None)

    assert bundle.contents == ()
    assert bundle.refs == ()


def test_table_gera_dataframe_com_os_numeros_do_resultado() -> None:

    result = _snapshot_result()

    bundle = PlotlyArtifactBuilder().build("t1", result, TABLE)

    (dataframe,) = bundle.contents

    assert isinstance(dataframe, Dataframe)
    assert [row[3] for row in dataframe.rows] == [Decimal("0.12"), Decimal("0.08")]
    assert all(row[3] in _result_numbers(result) for row in dataframe.rows)
    assert all("Private" not in row[0] for row in dataframe.rows)
    assert [ref.kind for ref in bundle.refs] == [ArtifactKind.TABLE]


def test_bar_plota_so_valores_do_resultado_e_deixa_undefined_fora() -> None:

    result = _snapshot_result()
    presentation = Presentation(
        type=PresentationType.BAR,
        axis=PresentationAxis.ENTITY,
        title="Rentabilidade por segmento",
    )

    bundle = PlotlyArtifactBuilder().build("t1", result, presentation)

    dataframe, plotly = bundle.contents

    assert isinstance(dataframe, Dataframe)
    assert isinstance(plotly, Plotly)
    (trace,) = plotly.figure["data"]

    assert trace["type"] == "bar"
    assert trace["y"] == [Decimal("0.12"), Decimal("0.08")]
    assert all(value in _result_numbers(result) for value in trace["y"])
    assert "Private" not in trace["x"]
    assert plotly.figure["layout"]["title"]["text"] == "Rentabilidade por segmento"
    assert [ref.kind for ref in bundle.refs] == [
        ArtifactKind.TABLE,
        ArtifactKind.CHART,
    ]


def test_line_usa_periodo_como_eixo_e_uma_trajetoria_por_entidade() -> None:

    result = _series_result()
    presentation = Presentation(
        type=PresentationType.LINE,
        axis=PresentationAxis.PERIOD,
        title="Evolução da rentabilidade",
    )

    bundle = PlotlyArtifactBuilder().build("t2", result, presentation)

    _, plotly = bundle.contents

    assert isinstance(plotly, Plotly)

    traces = plotly.figure["data"]

    assert [trace["name"] for trace in traces] == ["Atacado PJ", "Varejo PF"]
    assert all(trace["type"] == "scatter" for trace in traces)

    varejo = next(trace for trace in traces if trace["name"] == "Varejo PF")

    assert varejo["x"] == ["2025-09-30", "2025-10-31"]
    assert varejo["y"] == [Decimal("0.10"), Decimal("0.12")]

    for trace in traces:
        assert all(value in _result_numbers(result) for value in trace["y"])


def test_ranking_bar_respeita_a_ordem_do_resultado() -> None:

    result = _ranking_result()
    presentation = Presentation(
        type=PresentationType.RANKING_BAR,
        axis=PresentationAxis.ENTITY,
        title="Ranking de rentabilidade",
    )

    bundle = PlotlyArtifactBuilder().build("t3", result, presentation)

    _, plotly = bundle.contents

    assert isinstance(plotly, Plotly)
    (trace,) = plotly.figure["data"]

    assert trace["orientation"] == "h"
    assert trace["y"] == ["Varejo PF", "Atacado PJ"]
    assert trace["x"] == [Decimal("0.12"), Decimal("0.08")]
    assert "Private" not in trace["y"]
    assert all(value in _result_numbers(result) for value in trace["x"])


def test_bar_com_rotulo_repetido_cai_para_a_tabela() -> None:

    # Série por entidade: a mesma entidade aparece em vários períodos; um bar
    # simples exigiria agregar (proibido), então só a tabela é produzida.
    presentation = Presentation(type=PresentationType.BAR, axis=PresentationAxis.ENTITY)

    bundle = PlotlyArtifactBuilder().build("t2", _series_result(), presentation)

    assert len(bundle.contents) == 1
    assert isinstance(bundle.contents[0], Dataframe)
    assert [ref.kind for ref in bundle.refs] == [ArtifactKind.TABLE]


def test_resultado_todo_indefinido_nao_gera_conteudo() -> None:

    result = AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v3",
        dataset_version="2026-08-31",
        trace_id="t4",
        statistical_method=[
            MethodResult(
                id="s1",
                method="null",
                unit="decimal_rate",
                values=[
                    MethodValue(
                        {SEGMENT: "Private"},
                        {},
                        UndefinedReason.SMALL_CELL,
                        "2026-08-31",
                    )
                ],
            )
        ],
    )

    bundle = PlotlyArtifactBuilder().build(
        "t4", result, Presentation(type=PresentationType.BAR)
    )

    assert bundle.contents == ()
    assert bundle.refs == ()


def test_refs_sao_deterministicos_e_nao_mentem_sobre_o_object_store() -> None:

    builder = PlotlyArtifactBuilder()
    presentation = Presentation(type=PresentationType.BAR)

    first = builder.build("t1", _snapshot_result(), presentation)
    second = builder.build("t1", _snapshot_result(), presentation)

    assert first.refs == second.refs
    assert first.refs[0].artifact_id == "art-t1-table"
    assert first.refs[1].artifact_id == "art-t1-chart"
    assert all(
        ref.location == f"derived://analysis-result/{ref.artifact_id}"
        for ref in first.refs
    )
    assert not any(ref.location.startswith("s3://") for ref in first.refs)


def test_titulo_com_numero_inventado_e_descartado() -> None:

    presentation = Presentation(
        type=PresentationType.BAR,
        axis=PresentationAxis.ENTITY,
        title="Rentabilidade de 99,99% em 2026",
    )

    bundle = PlotlyArtifactBuilder().build("t9", _snapshot_result(), presentation)
    plotly = next(item for item in bundle.contents if isinstance(item, Plotly))

    assert "title" not in plotly.figure["layout"]
    assert any(ref.kind is ArtifactKind.CHART for ref in bundle.refs)


def test_titulo_com_numero_do_resultado_e_mantido() -> None:

    presentation = Presentation(
        type=PresentationType.BAR,
        axis=PresentationAxis.ENTITY,
        title="Rentabilidade de 12% em 2026",
    )

    bundle = PlotlyArtifactBuilder().build("t9", _snapshot_result(), presentation)
    plotly = next(item for item in bundle.contents if isinstance(item, Plotly))

    assert plotly.figure["layout"]["title"]["text"] == "Rentabilidade de 12% em 2026"


def test_titulo_perde_marcacao_de_html() -> None:

    presentation = Presentation(
        type=PresentationType.TABLE,
        title="<b>Rentabilidade</b> <script>alert(1)</script>",
    )

    assert presentation.title == "Rentabilidade alert(1)"
    assert "<" not in presentation.title

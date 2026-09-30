"""`execute_analysis`: organiza os números verificados do resultado.

Cobre os métodos do catálogo, as operações, a identidade `subjects`, a
supressão small-cell e a procedência do resultado.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    Operation,
    OperationType,
    StatisticalMethod,
    StatisticalMethodType,
)
from contexts.financial_analysis.domain.analysis_result import UndefinedReason
from contexts.financial_analysis.domain.services.execute_analysis import (
    execute_analysis,
    populations_from_results,
)
from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
    CalculationResultRow,
)

CATALOG = YamlSemanticCatalogAdapter().load_active()

SEGMENT = "customer_segmentation.segment"
RELATIONSHIP = "customer_relationship.relationship_depth"


def _result(
    plan_id: str,
    rows: list[tuple[dict, str, object]],
    *,
    rule_id: str = "profitability",
    unit: str = "decimal_rate",
) -> CalculationResult:

    return CalculationResult(
        calculation_plan_id=plan_id,
        rule_id=rule_id,
        unit=unit,
        values=[
            CalculationResultRow(subjects=subjects, period=period, value=value)
            for subjects, period, value in rows
        ],
    )


def _method(
    method_id: str,
    method: StatisticalMethodType,
    *,
    calculation_plan_ids: list[str] | None = None,
    statistic_refs: list[str] | None = None,
) -> StatisticalMethod:

    return StatisticalMethod(
        id=method_id,
        method=method,
        calculation_plan_ids=list(calculation_plan_ids or []),
        statistic_refs=list(statistic_refs or []),
    )


def _analysis(
    methods: list[StatisticalMethod],
    operations: list[Operation] | None = None,
) -> AnalysisPlan:

    return AnalysisPlan(
        id="plan",
        statistical_method=methods,
        operations=list(operations or []),
    )


def _subjects(segment: str) -> dict[str, str]:

    return {SEGMENT: segment}


def _run(
    analysis: AnalysisPlan,
    results: list[CalculationResult],
    *,
    populations: dict | None = None,
):

    return execute_analysis(
        analysis,
        results,
        CATALOG,
        dataset_version="d1",
        trace_id="t1",
        populations=populations,
    )


def test_resultado_carrega_procedencia() -> None:

    row = _subjects("Varejo PF")
    result = _result("calc1", [(row, "2026-08-31", Decimal("0.10"))])
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc1"])]
    )

    outcome = _run(analysis, [result])

    assert outcome.catalog_version == "v3"
    assert outcome.dataset_version == "d1"
    assert outcome.trace_id == "t1"


def test_null_preserva_valor_e_periodo() -> None:

    row = _subjects("Varejo PF")
    result = _result(
        "calc1",
        [
            (row, "2026-07-31", Decimal("0.10")),
            (_subjects("Atacado PJ"), "2026-07-31", None),
        ],
    )

    outcome = _run(
        _analysis(
            [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc1"])]
        ),
        [result],
    )

    values = outcome.statistical_method[0].values

    assert values[0].values["value"] == Decimal("0.10")
    assert values[0].period == "2026-07-31"
    assert values[1].undefined is UndefinedReason.NO_OBSERVATIONS


def test_media_e_desvio_da_serie_por_entidade() -> None:

    row = _subjects("Varejo PF")
    result = _result(
        "calc1",
        [
            (row, "2026-06-30", Decimal("0.10")),
            (row, "2026-07-31", Decimal("0.20")),
            (row, "2026-08-31", Decimal("0.30")),
        ],
    )
    analysis = _analysis(
        [
            _method("s1", StatisticalMethodType.MEAN, calculation_plan_ids=["calc1"]),
            _method("s2", StatisticalMethodType.STD, calculation_plan_ids=["calc1"]),
        ]
    )

    outcome = _run(analysis, [result])

    assert outcome.statistical_method[0].values[0].values["value"] == Decimal("0.2")
    assert outcome.statistical_method[1].values[0].values["value"] == pytest.approx(
        Decimal("0.1"), abs=Decimal("1e-18")
    )


def test_dispersion_devolve_o_pacote() -> None:

    row = _subjects("Varejo PF")
    result = _result(
        "calc1",
        [
            (row, "2026-06-30", Decimal("10")),
            (row, "2026-07-31", Decimal("20")),
            (row, "2026-08-31", Decimal("30")),
        ],
    )
    analysis = _analysis(
        [
            _method(
                "s1", StatisticalMethodType.DISPERSION, calculation_plan_ids=["calc1"]
            )
        ]
    )

    pack = _run(analysis, [result]).statistical_method[0].values[0].values

    assert pack["median"] == Decimal("20")
    assert pack["variance"] == Decimal("100")
    assert pack["iqr"] == Decimal("10")


def test_variation_ordena_janelas_e_devolve_absoluto_e_percentual() -> None:

    base = _result(
        "calc_base", [(_subjects("Varejo PF"), "2025-08-31", Decimal("0.20"))]
    )
    current = _result(
        "calc_curr", [(_subjects("Varejo PF"), "2026-08-31", Decimal("0.15"))]
    )
    analysis = _analysis(
        [
            _method(
                "s1",
                StatisticalMethodType.VARIATION,
                calculation_plan_ids=["calc_base", "calc_curr"],
            )
        ]
    )

    values = _run(analysis, [base, current]).statistical_method[0].values[0].values

    assert values["absolute"] == Decimal("-0.05")
    assert values["percent"] == Decimal("-0.25")


def test_share_reparte_o_total_colapsado() -> None:

    result = _result(
        "calc1",
        [
            (_subjects("A"), "2026-08-31", Decimal("30")),
            (_subjects("B"), "2026-08-31", Decimal("10")),
        ],
        rule_id="outstanding_balance",
        unit="currency",
    )
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.SHARE, calculation_plan_ids=["calc1"])]
    )

    values = _run(analysis, [result]).statistical_method[0].values

    assert values[0].values["value"] == Decimal("0.75")
    assert values[1].values["value"] == Decimal("0.25")


def test_correlation_pearson_entre_dois_metodos() -> None:
    contracts = _result(
        "calc_c",
        [
            (_subjects("A"), "2026-08-31", Decimal("10")),
            (_subjects("B"), "2026-08-31", Decimal("20")),
            (_subjects("C"), "2026-08-31", Decimal("30")),
        ],
        rule_id="contract_count",
        unit="count",
    )
    profitability = _result(
        "calc_p",
        [
            (_subjects("A"), "2026-08-31", Decimal("0.01")),
            (_subjects("B"), "2026-08-31", Decimal("0.02")),
            (_subjects("C"), "2026-08-31", Decimal("0.03")),
        ],
    )
    analysis = _analysis(
        [
            _method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_c"]),
            _method("s2", StatisticalMethodType.NULL, calculation_plan_ids=["calc_p"]),
            _method(
                "s3", StatisticalMethodType.CORRELATION, statistic_refs=["s1", "s2"]
            ),
        ]
    )

    value = _run(analysis, [contracts, profitability]).statistical_method[2].values[0]

    assert value.values["value"] == Decimal("1")


def test_trend_no_tempo_e_por_nivel_ordinal() -> None:
    total = "total.total"
    series = _result(
        "calc1",
        [
            ({total: None}, "2026-06-30", Decimal("1")),
            ({total: None}, "2026-07-31", Decimal("2")),
            ({total: None}, "2026-08-31", Decimal("3")),
        ],
    )
    ordinal = _result(
        "calc2",
        [
            ({RELATIONSHIP: "baixa"}, "2026-08-31", Decimal("0.01")),
            ({RELATIONSHIP: "media"}, "2026-08-31", Decimal("0.02")),
            ({RELATIONSHIP: "alta"}, "2026-08-31", Decimal("0.03")),
        ],
    )
    analysis = _analysis(
        [
            _method("s1", StatisticalMethodType.TREND, calculation_plan_ids=["calc1"]),
            _method("s2", StatisticalMethodType.TREND, calculation_plan_ids=["calc2"]),
        ]
    )

    outcome = _run(analysis, [series, ordinal])

    assert outcome.statistical_method[0].values[0].values["value"] == Decimal("1")
    assert outcome.statistical_method[1].values[0].values["value"] == Decimal("0.01")


def test_outlier_marca_o_ponto_atipico() -> None:
    total = "total.total"
    result = _result(
        "calc1",
        [
            ({total: None}, "2026-05-31", Decimal("1")),
            ({total: None}, "2026-06-30", Decimal("1")),
            ({total: None}, "2026-07-31", Decimal("1")),
            ({total: None}, "2026-08-31", Decimal("10")),
        ],
    )
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.OUTLIER, calculation_plan_ids=["calc1"])]
    )

    values = _run(analysis, [result]).statistical_method[0].values

    assert len(values) == 1
    assert values[0].values["value"] == Decimal("10")
    assert values[0].period == "2026-08-31"


def test_ranking_por_entidade_com_top_n() -> None:
    result = _result(
        "calc1",
        [
            (_subjects("A"), "2026-08-31", Decimal("0.10")),
            (_subjects("B"), "2026-08-31", Decimal("0.30")),
            (_subjects("C"), "2026-08-31", Decimal("0.20")),
        ],
    )
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc1"])],
        [
            Operation(
                id="o1",
                type=OperationType.RANKING,
                refs=["s1"],
                params={"order": "desc", "top_n": 2, "axis": "entity"},
            )
        ],
    )

    values = _run(analysis, [result]).operations[0].values

    assert [row.rank for row in values] == [1, 2]
    assert values[0].subjects[SEGMENT] == "B"
    assert values[1].subjects[SEGMENT] == "C"


def test_selection_top_percent_mantem_empates() -> None:
    result = _result(
        "calc1",
        [
            (_subjects("A"), "2026-08-31", Decimal("0.10")),
            (_subjects("B"), "2026-08-31", Decimal("0.30")),
            (_subjects("C"), "2026-08-31", Decimal("0.30")),
            (_subjects("D"), "2026-08-31", Decimal("0.20")),
        ],
    )
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc1"])],
        [
            Operation(
                id="o1",
                type=OperationType.SELECTION,
                refs=["s1"],
                params={"rule": "top_percent", "value": 50},
            )
        ],
    )

    values = _run(analysis, [result]).operations[0].values

    assert {row.subjects[SEGMENT] for row in values} == {"B", "C"}


def test_decomposition_fecha_a_soma_das_contribuicoes() -> None:
    base = _result(
        "calc_base",
        [
            (_subjects("A"), "2025-08-31", Decimal("0.10")),
            (_subjects("B"), "2025-08-31", Decimal("0.20")),
        ],
    )
    current = _result(
        "calc_curr",
        [
            (_subjects("A"), "2026-08-31", Decimal("0.09")),
            (_subjects("B"), "2026-08-31", Decimal("0.22")),
        ],
    )
    balance = _result(
        "calc_bal",
        [
            (_subjects("A"), "2025-08-31", Decimal("60")),
            (_subjects("B"), "2025-08-31", Decimal("40")),
        ],
        rule_id="outstanding_balance",
        unit="currency",
    )
    analysis = _analysis(
        [
            _method(
                "s1",
                StatisticalMethodType.VARIATION,
                calculation_plan_ids=["calc_base", "calc_curr"],
            ),
            _method(
                "s2", StatisticalMethodType.SHARE, calculation_plan_ids=["calc_bal"]
            ),
        ],
        [Operation(id="o1", type=OperationType.DECOMPOSITION, refs=["s1", "s2"])],
    )

    values = _run(analysis, [base, current, balance]).operations[0].values

    contributions = [row.values["contribution"] for row in values[:-1]]
    total = values[-1].values["contribution"]

    assert sum(contributions, Decimal(0)) == total
    assert total == Decimal("0.002")


def test_small_cell_suprime_com_celula_complementar() -> None:
    result = _result(
        "calc1",
        [
            (_subjects("A"), "2026-08-31", Decimal("0.10")),
            (_subjects("B"), "2026-08-31", Decimal("0.20")),
            (_subjects("C"), "2026-08-31", Decimal("0.30")),
        ],
    )
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc1"])]
    )
    populations = {
        (((SEGMENT, "A"),), "2026-08-31"): 50,
        (((SEGMENT, "B"),), "2026-08-31"): 5,
        (((SEGMENT, "C"),), "2026-08-31"): 40,
    }

    values = (
        _run(analysis, [result], populations=populations).statistical_method[0].values
    )

    suppressed = {
        row.subjects[SEGMENT]
        for row in values
        if row.undefined is UndefinedReason.SMALL_CELL
    }

    assert suppressed == {"B", "A"}
    assert any(row.undefined is None for row in values)


def _populated_result(
    plan_id: str,
    rows: list[tuple[dict, str, object, int | None]],
) -> CalculationResult:

    return CalculationResult(
        calculation_plan_id=plan_id,
        rule_id="profitability",
        unit="decimal_rate",
        values=[
            CalculationResultRow(
                subjects=subjects, period=period, value=value, population=population
            )
            for subjects, period, value, population in rows
        ],
    )


def test_populations_from_results_le_apenas_populacao_conhecida() -> None:

    result = _populated_result(
        "calc1",
        [
            (_subjects("A"), "2026-07-31", Decimal("0.10"), 7),
            (_subjects("A"), "2026-08-31", Decimal("0.11"), 15),
            (_subjects("B"), "2026-08-31", Decimal("0.20"), None),
        ],
    )

    populations = populations_from_results([result])

    assert populations == {
        (((SEGMENT, "A"),), "2026-07-31"): 7,
        (((SEGMENT, "A"),), "2026-08-31"): 15,
    }


def test_populations_from_results_prevalece_a_menor_entre_planos() -> None:

    first = _populated_result(
        "calc1", [(_subjects("A"), "2026-08-31", Decimal("0.10"), 30)]
    )
    second = _populated_result(
        "calc2", [(_subjects("A"), "2026-08-31", Decimal("0.10"), 8)]
    )

    populations = populations_from_results([first, second])

    assert populations == {(((SEGMENT, "A"),), "2026-08-31"): 8}


def test_small_cell_e_julgada_por_periodo() -> None:
    """A mesma célula pode ser pequena num mês e suficiente no outro: só o mês
    pequeno (e o seu complementar) é suprimido; o outro mês fica visível."""

    result = _populated_result(
        "calc1",
        [
            (_subjects("A"), "2026-07-31", Decimal("0.10"), 7),
            (_subjects("B"), "2026-07-31", Decimal("0.20"), 40),
            (_subjects("C"), "2026-07-31", Decimal("0.30"), 50),
            (_subjects("A"), "2026-08-31", Decimal("0.11"), 15),
            (_subjects("B"), "2026-08-31", Decimal("0.21"), 40),
            (_subjects("C"), "2026-08-31", Decimal("0.31"), 50),
        ],
    )
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc1"])]
    )

    values = (
        _run(analysis, [result], populations=populations_from_results([result]))
        .statistical_method[0]
        .values
    )

    suppressed = {
        (row.subjects[SEGMENT], row.period)
        for row in values
        if row.undefined is UndefinedReason.SMALL_CELL
    }

    assert suppressed == {("A", "2026-07-31"), ("B", "2026-07-31")}
    assert all(row.undefined is None for row in values if row.period == "2026-08-31")


def test_populacao_desconhecida_nao_suprime() -> None:

    result = _populated_result(
        "calc1",
        [
            (_subjects("A"), "2026-08-31", Decimal("0.10"), None),
            (_subjects("B"), "2026-08-31", Decimal("0.20"), 40),
        ],
    )
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc1"])]
    )

    values = (
        _run(analysis, [result], populations=populations_from_results([result]))
        .statistical_method[0]
        .values
    )

    assert all(row.undefined is None for row in values)


def test_total_recortado_e_uma_celula_e_tambem_e_suprimido() -> None:
    """Um plano `total.total` com recorte (ex.: principalidade alta) é UMA
    célula: se tem menos de k clientes, é suprimida como qualquer outra; a
    supressão complementar simplesmente não tem companheira."""

    result = _populated_result("calc1", [({}, "2026-08-31", Decimal("0.10"), 4)])
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc1"])]
    )

    values = (
        _run(analysis, [result], populations=populations_from_results([result]))
        .statistical_method[0]
        .values
    )

    assert len(values) == 1
    assert values[0].subjects == {}
    assert values[0].undefined is UndefinedReason.SMALL_CELL
    assert values[0].values == {}


def test_total_com_populacao_suficiente_fica_intacto() -> None:

    result = _populated_result("calc1", [({}, "2026-08-31", Decimal("0.10"), 40)])
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc1"])]
    )

    values = (
        _run(analysis, [result], populations=populations_from_results([result]))
        .statistical_method[0]
        .values
    )

    assert len(values) == 1
    assert values[0].undefined is None
    assert values[0].values == {"value": Decimal("0.10")}


def test_estatistica_da_serie_herda_a_menor_populacao_da_celula() -> None:
    """`mean` não tem período: se algum mês da célula ficou abaixo de k, a média
    (que embute aquele mês) também é suprimida."""

    result = _populated_result(
        "calc1",
        [
            (_subjects("A"), "2026-07-31", Decimal("0.10"), 7),
            (_subjects("A"), "2026-08-31", Decimal("0.11"), 15),
            (_subjects("B"), "2026-07-31", Decimal("0.20"), 40),
            (_subjects("B"), "2026-08-31", Decimal("0.21"), 40),
            (_subjects("C"), "2026-07-31", Decimal("0.30"), 50),
            (_subjects("C"), "2026-08-31", Decimal("0.31"), 50),
        ],
    )
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.MEAN, calculation_plan_ids=["calc1"])]
    )

    values = (
        _run(analysis, [result], populations=populations_from_results([result]))
        .statistical_method[0]
        .values
    )

    suppressed = {
        row.subjects[SEGMENT]
        for row in values
        if row.undefined is UndefinedReason.SMALL_CELL
    }

    assert suppressed == {"A", "B"}

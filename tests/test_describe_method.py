"""A nota "Como calculei" nasce do pacote selado, do resultado e do
catálogo — determinística, sem LLM, sem números do resultado e sem id interno.
Ela diz a fórmula da métrica, o período, o método, as supressões, a base
oficial e o documento aprovado de referência."""

from __future__ import annotations

from decimal import Decimal

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
from contexts.financial_analysis.domain.analysis_result import (
    AnalysisResult,
    MethodResult,
    MethodValue,
    UndefinedReason,
)
from contexts.financial_analysis.domain.services.describe_method import (
    METHOD_NOTE_TITLE,
    describe_method,
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

CATALOG = YamlSemanticCatalogAdapter().load_active()
SEGMENT = "customer_segmentation.segment"


def _ranking_plan() -> AnalysisPlan:

    return AnalysisPlan(
        id="plan",
        statistical_method=[
            StatisticalMethod(
                id="s1",
                method=StatisticalMethodType.NULL,
                calculation_plan_ids=["calc_prof_seg"],
            )
        ],
        operations=[
            Operation(
                id="o1",
                type=OperationType.RANKING,
                refs=["s1"],
                params={"order": "desc", "top_n": 1, "axis": "entity"},
            )
        ],
    )


def _profitability_by_segment(
    sample: tuple[SampleCondition, ...] = (),
) -> CalculationPlan:

    return CalculationPlan(
        calculation_plan_id="calc_prof_seg",
        metric=Metric(
            rule_id=RuleId.PROFITABILITY,
            subjects=[Subject(AxisType.CUSTOMER_SEGMENTATION, AxisLevel.SEGMENT)],
            sample=sample,
        ),
        period=Period("2025-09-01", "2026-08-31", PeriodType.SERIES, Grain.TOTAL),
    )


def _result(*rows: MethodValue) -> AnalysisResult:

    return AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v3",
        dataset_version="2026-08-31#sha256:" + "ab12cd34" + "0" * 56,
        trace_id="t1",
        rule_id="profitability",
        statistical_method=[
            MethodResult(
                id="s1",
                method="null",
                unit="decimal_rate",
                rule_id="profitability",
                values=list(rows),
            )
        ],
    )


def test_nota_cita_formula_periodo_metodo_base_e_referencia() -> None:

    result = _result(
        MethodValue(
            subjects={SEGMENT: "Varejo PF"}, values={"value": Decimal("0.1546")}
        ),
        MethodValue(
            subjects={SEGMENT: "Atacado PJ"}, values={"value": Decimal("0.08")}
        ),
    )

    text = describe_method(
        _ranking_plan(), [_profitability_by_segment()], result, CATALOG
    )

    assert METHOD_NOTE_TITLE == "Como calculei"
    assert text.splitlines() == [
        "- Métrica: rentabilidade = Σ margem anualizada ÷ Σ saldo, re-derivada no "
        "total do período (não é média de taxas).",
        "- Período: set/2025 a ago/2026 (12 meses fechados), por segmento.",
        "- Método: ranking pela rentabilidade do período (ordem decrescente).",
        "- Base: dados oficiais de rentabilidade e carteira, fechamento em 31/08/2026.",
        '- Referência: "Como o banco calcula rentabilidade" (documento aprovado).',
    ]


def test_nota_nao_traz_numero_do_resultado_nem_id_interno() -> None:

    result = _result(
        MethodValue(
            subjects={SEGMENT: "Varejo PF"}, values={"value": Decimal("0.1546")}
        ),
    )

    text = describe_method(
        _ranking_plan(), [_profitability_by_segment()], result, CATALOG
    )

    for forbidden in ("0.1546", "0,1546", "15,46", "15.46", "_", "calc_", "s1", "o1"):
        assert forbidden not in text


def test_nota_conta_celulas_suprimidas_e_cita_a_politica() -> None:

    result = _result(
        MethodValue(subjects={SEGMENT: "Private"}, values={"value": Decimal("0.30")}),
        MethodValue(
            subjects={SEGMENT: "Varejo PF"}, undefined=UndefinedReason.SMALL_CELL
        ),
        MethodValue(
            subjects={SEGMENT: "Atacado PJ"}, undefined=UndefinedReason.SMALL_CELL
        ),
    )
    sample = (
        SampleCondition(
            AxisType.CUSTOMER_PRINCIPALITY, AxisLevel.PRINCIPALITY_DEPTH, "high"
        ),
    )

    text = describe_method(
        _ranking_plan(), [_profitability_by_segment(sample)], result, CATALOG
    )

    assert (
        "- Supressões: 2 células omitidas por ter menos de 10 clientes "
        "(política de célula pequena)." in text
    )
    assert "por segmento, com recorte por alta principalidade" in text
    assert '"Politica de celula pequena (k igual a 10)"' in text
    assert "(documentos aprovados)" in text
    assert "0,30" not in text


def test_nota_descreve_metodo_serie_snapshot_e_serie_macro() -> None:

    trend = AnalysisPlan(
        id="p",
        statistical_method=[
            StatisticalMethod(
                id="s1", method=StatisticalMethodType.TREND, calculation_plan_ids=["c"]
            )
        ],
    )
    balance = CalculationPlan(
        calculation_plan_id="c",
        metric=Metric(
            rule_id=RuleId.OUTSTANDING_BALANCE,
            subjects=[Subject(AxisType.TOTAL, AxisLevel.TOTAL)],
        ),
        period=Period("2026-03-01", "2026-08-31", PeriodType.SERIES, Grain.MONTH),
    )
    cdi = CalculationPlan(
        calculation_plan_id="c",
        metric=Metric(
            rule_id=RuleId.CDI_RATE, subjects=[Subject(AxisType.TOTAL, AxisLevel.TOTAL)]
        ),
        period=Period("2026-08-31", "2026-08-31", PeriodType.SNAPSHOT, Grain.MONTH),
    )
    result = AnalysisResult(
        analysis_plan_id="p",
        catalog_version="v3",
        dataset_version="2026-08-31",
        trace_id="t",
    )

    trend_text = describe_method(trend, [balance], result, CATALOG)
    snapshot_text = describe_method(_ranking_plan(), [cdi], result, CATALOG)

    assert (
        "- Período: mar/2026 a ago/2026 (6 meses fechados, grão mensal), no total."
        in (trend_text)
    )
    assert "regressão linear" in trend_text and "não previsão" in trend_text
    assert '"O que é tendência (regressão linear) e o que não é previsão"' in trend_text
    assert "- Período: posição em 31/08/2026, no total." in snapshot_text
    assert "- Base: dados oficiais de séries de mercado, fechamento em 31/08/2026." in (
        snapshot_text
    )


def test_titulos_de_referencia_existem_como_documentos_aprovados() -> None:
    """Cada referência citada na nota é o `title` de um doc `approved` do
    acervo: a nota nunca aponta para um documento que o RAG não conhece."""

    import re
    from pathlib import Path

    from contexts.financial_analysis.domain.services import describe_method as module

    knowledge = Path(__file__).resolve().parents[1] / "data" / "knowledge"
    titles: set[str] = set()

    for doc in knowledge.glob("*.md"):
        head = doc.read_text(encoding="utf-8")[:600]
        title = re.search(r"^title:\s*(.+)$", head, re.M)
        status = re.search(r"^status:\s*approved$", head, re.M)

        if title and status:
            titles.add(title.group(1).strip())

    referenced = {
        *module._METRIC_REFERENCES.values(),
        *module._METHOD_REFERENCES.values(),
        *module._OPERATION_REFERENCES.values(),
        module._SMALL_CELL_REFERENCE,
    }

    assert referenced <= titles, referenced - titles

"""Agregado `AnalysisRequest`: transições legais e eventos que ele registra.

Os eventos carregam ids, versões e contadores — nunca a pergunta, números ou
dados pessoais. O handler só chama os métodos; quem cria o evento é o agregado.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    StatisticalMethod,
    StatisticalMethodType,
)
from contexts.financial_analysis.domain.analysis_request import (
    AnalysisRequest,
    AnalysisRequestError,
    AnalysisStatus,
)
from contexts.financial_analysis.domain.analysis_result import AnalysisResult
from contexts.financial_analysis.domain.events import (
    AnalysisCompleted,
    InsightGenerated,
    PlanProposed,
    PlanRejected,
    PlanValidated,
    RequestRefused,
)
from contexts.financial_analysis.domain.interpretation import (
    InterpretationRoute,
    RefusalReason,
)
from contexts.financial_analysis.domain.services.validate_plan import ValidatedPlan
from contexts.financial_calculation.domain.calculation import Calculation
from contexts.financial_calculation.domain.calculation_plan import (
    AxisLevel,
    AxisType,
    CalculationPlan,
    Grain,
    Metric,
    Period,
    PeriodType,
    RuleId,
    Subject,
)
from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
)
from contexts.financial_calculation.domain.events import CalculationCompleted

PLAN = CalculationPlan(
    calculation_plan_id="calc_a",
    metric=Metric(
        rule_id=RuleId.PROFITABILITY,
        subjects=[Subject(type=AxisType.TOTAL, level=AxisLevel.TOTAL)],
    ),
    period=Period(
        start="2026-08-31",  # type: ignore[arg-type]
        end="2026-08-31",  # type: ignore[arg-type]
        type=PeriodType.SNAPSHOT,
        grain=Grain.TOTAL,
    ),
)
ANALYSIS = AnalysisPlan(
    id="plan",
    statistical_method=[
        StatisticalMethod(
            id="s1",
            method=StatisticalMethodType.NULL,
            calculation_plan_ids=["calc_a"],
        )
    ],
)


def _request() -> AnalysisRequest:

    return AnalysisRequest(
        trace_id="t1", session_id="s1", user_id="u1", question="pergunta"
    )


def _validated() -> ValidatedPlan:

    return ValidatedPlan(
        analysis_plan=ANALYSIS,
        calculations=(PLAN,),
        catalog_version="v2",
        validated_at=datetime.now(UTC),
    )


def _result(trace_id: str = "t1") -> AnalysisResult:

    return AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v2",
        dataset_version="d1",
        trace_id=trace_id,
    )


def test_caminho_feliz_registra_os_eventos_na_ordem() -> None:

    request = _request()

    request.propose(InterpretationRoute.ANALYTICAL, ANALYSIS, [PLAN])
    request.approve(_validated())
    request.complete(_result())
    request.explain("texto", "| tabela |", grounded=True, attempts=1)

    events = request.pull_events()

    assert request.status is AnalysisStatus.EXPLAINED
    assert [type(event) for event in events] == [
        PlanProposed,
        PlanValidated,
        AnalysisCompleted,
        InsightGenerated,
    ]
    assert all(event.aggregate_id == "t1" for event in events)
    assert events[0].calculation_plan_ids == ("calc_a",)  # type: ignore[attr-defined]
    assert events[1].catalog_version == "v2"  # type: ignore[attr-defined]
    assert request.pull_events() == ()


def test_eventos_nao_carregam_a_pergunta() -> None:

    request = _request()
    request.propose(InterpretationRoute.ANALYTICAL, ANALYSIS, [PLAN])

    (event,) = request.pull_events()
    names = {field.name for field in fields(event)}

    assert "question" not in names
    assert "pergunta" not in repr(event)


def test_rejeicao_permite_nova_proposta_e_conta_tentativas() -> None:

    request = _request()

    request.propose(InterpretationRoute.ANALYTICAL, ANALYSIS, [PLAN])
    request.reject(RefusalReason.CATALOG_MISS, "métrica x")
    request.propose(InterpretationRoute.ANALYTICAL, ANALYSIS, [PLAN])
    request.reject(RefusalReason.CATALOG_MISS, "métrica x")
    request.refuse(RefusalReason.CATALOG_MISS)

    events = request.pull_events()
    rejections = [event for event in events if isinstance(event, PlanRejected)]

    assert request.status is AnalysisStatus.REFUSED
    assert [event.attempt for event in rejections] == [1, 2]
    assert isinstance(events[-1], RequestRefused)


def test_transicoes_ilegais_sao_recusadas() -> None:

    request = _request()

    with pytest.raises(AnalysisRequestError):
        request.approve(_validated())

    with pytest.raises(AnalysisRequestError):
        request.complete(_result())

    request.propose(InterpretationRoute.DOCUMENTAL)

    with pytest.raises(AnalysisRequestError):
        request.approve(_validated())

    with pytest.raises(AnalysisRequestError):
        request.propose(InterpretationRoute.ANALYTICAL, ANALYSIS, [PLAN])


def test_resultado_de_outro_trace_e_recusado() -> None:

    request = _request()
    request.propose(InterpretationRoute.ANALYTICAL, ANALYSIS, [PLAN])
    request.approve(_validated())

    with pytest.raises(AnalysisRequestError):
        request.complete(_result(trace_id="outro"))


def test_calculation_registra_completed_com_reuso() -> None:

    calculation = Calculation("chave", PLAN)
    result = CalculationResult(
        calculation_plan_id="calc_a", rule_id="profitability", unit="decimal_rate"
    )

    calculation.complete(result, reused=True)

    (event,) = calculation.pull_events()

    assert isinstance(event, CalculationCompleted)
    assert event.aggregate_id == "chave"
    assert event.reused is True
    assert event.rows == 0

"""Invariantes de montagem do AnalysisPlan.

O id do StatisticalMethod é uma chave local do DAG do plano: precisa ser único,
toda referência precisa resolver e as `statistic_refs` não podem formar ciclo.
Sem isso, a integridade referencial fica só no prompt e uma ref alucinada só
quebra lá na execução.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from contexts.financial_analysis.adapters.outbound.localized_interpretation_prompt import (
    LocalizedInterpretationPromptAdapter,
)
from contexts.financial_analysis.application.commands.answer_question import (
    InterpretationProposal,
)
from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    Operation,
    OperationType,
    Presentation,
    PresentationAxis,
    PresentationType,
    StatisticalMethod,
    StatisticalMethodType,
)
from contexts.financial_analysis.domain.errors import (
    AmbiguousMethodSourceError,
    CyclicReferenceError,
    DuplicateIdError,
    InvalidPresentationError,
    UnresolvedReferenceError,
)


def _method(
    method_id: str,
    *,
    calculation_plan_ids: list[str] | None = None,
    statistic_refs: list[str] | None = None,
) -> StatisticalMethod:

    if calculation_plan_ids is None and statistic_refs is None:
        calculation_plan_ids = ["calc1"]

    return StatisticalMethod(
        id=method_id,
        method=StatisticalMethodType.MEAN,
        calculation_plan_ids=calculation_plan_ids or [],
        statistic_refs=statistic_refs or [],
    )


def test_plano_valido_constroi() -> None:

    plan = AnalysisPlan(
        id="plan1",
        statistical_method=[_method("s1"), _method("s2", statistic_refs=["s1"])],
        operations=[Operation(id="o1", type=OperationType.RANKING, refs=["s2"])],
    )

    assert plan.id == "plan1"


def test_id_de_metodo_repetido_e_recusado() -> None:

    with pytest.raises(DuplicateIdError):
        AnalysisPlan(id="p", statistical_method=[_method("s1"), _method("s1")])


def test_id_de_operacao_repetido_e_recusado() -> None:

    operations = [
        Operation(id="o1", type=OperationType.RANKING, refs=["s1"]),
        Operation(id="o1", type=OperationType.RANKING, refs=["s1"]),
    ]

    with pytest.raises(DuplicateIdError):
        AnalysisPlan(id="p", statistical_method=[_method("s1")], operations=operations)


def test_statistic_ref_orfa_e_recusada() -> None:

    with pytest.raises(UnresolvedReferenceError):
        AnalysisPlan(
            id="p",
            statistical_method=[_method("s2", statistic_refs=["s9"])],
        )


def test_operation_ref_orfa_e_recusada() -> None:

    operations = [Operation(id="o1", type=OperationType.RANKING, refs=["s9"])]

    with pytest.raises(UnresolvedReferenceError):
        AnalysisPlan(id="p", statistical_method=[_method("s1")], operations=operations)


def test_ciclo_em_statistic_refs_e_recusado() -> None:

    methods = [
        _method("s1", statistic_refs=["s2"]),
        _method("s2", statistic_refs=["s1"]),
    ]

    with pytest.raises(CyclicReferenceError):
        AnalysisPlan(id="p", statistical_method=methods)


def test_autoreferencia_e_recusada_como_ciclo() -> None:

    with pytest.raises(CyclicReferenceError):
        AnalysisPlan(id="p", statistical_method=[_method("s1", statistic_refs=["s1"])])


def test_metodo_com_as_duas_fontes_e_recusado() -> None:

    methods = [
        _method("s1", calculation_plan_ids=["calc1"], statistic_refs=["s2"]),
        _method("s2"),
    ]

    with pytest.raises(AmbiguousMethodSourceError):
        AnalysisPlan(id="p", statistical_method=methods)


def test_metodo_sem_fonte_e_recusado() -> None:

    methods = [_method("s1", calculation_plan_ids=[], statistic_refs=[])]

    with pytest.raises(AmbiguousMethodSourceError):
        AnalysisPlan(id="p", statistical_method=methods)


def test_pydantic_propaga_a_recusa_do_plano() -> None:

    proposal = {
        "route": "analytical",
        "analysis": {
            "id": "p",
            "statistical_method": [
                {
                    "id": "s1",
                    "method": "mean",
                    "statistic_refs": ["s9"],
                }
            ],
            "operations": [],
        },
        "calculations": [],
    }

    with pytest.raises(ValidationError):
        InterpretationProposal.model_validate(proposal)


def test_rota_analytical_exige_planos() -> None:

    with pytest.raises(ValidationError):
        InterpretationProposal.model_validate({"route": "analytical"})


def test_rota_documental_nao_carrega_planos() -> None:

    proposal = InterpretationProposal.model_validate({"route": "documental"})

    assert proposal.analysis is None
    assert proposal.calculations == []


def test_rota_clarify_exige_pergunta() -> None:

    with pytest.raises(ValidationError):
        InterpretationProposal.model_validate({"route": "clarify"})


def test_rota_refuse_exige_motivo() -> None:

    with pytest.raises(ValidationError):
        InterpretationProposal.model_validate({"route": "refuse"})


_CALCULATION = {
    "calculation_plan_id": "calc1",
    "metric": {
        "rule_id": "profitability",
        "subjects": [{"type": "customer_segmentation", "level": "segment"}],
    },
    "period": {
        "start": "2026-08-31",
        "end": "2026-08-31",
        "type": "snapshot",
        "grain": "month",
    },
}


def _analytical_proposal(presentation: dict | None = None) -> dict:

    analysis: dict = {
        "id": "plan1",
        "statistical_method": [
            {"id": "s1", "method": "null", "calculation_plan_ids": ["calc1"]}
        ],
        "operations": [],
    }

    if presentation is not None:
        analysis["presentation"] = presentation

    return {
        "route": "analytical",
        "analysis": analysis,
        "calculations": [_CALCULATION],
    }


def test_presentation_fora_do_catalogo_e_recusada() -> None:

    with pytest.raises(InvalidPresentationError):
        Presentation(type="pie")  # type: ignore[arg-type]


def test_presentation_line_exige_eixo_temporal() -> None:

    with pytest.raises(InvalidPresentationError):
        Presentation(type=PresentationType.LINE, axis=PresentationAxis.ENTITY)


def test_presentation_recusa_titulo_com_id_interno() -> None:

    with pytest.raises(InvalidPresentationError):
        Presentation(type=PresentationType.BAR, title="Ranking de plan_prod_high")

    with pytest.raises(InvalidPresentationError):
        Presentation(type=PresentationType.BAR, title="Top no o1")


def test_presentation_aceita_catalogo_fechado() -> None:

    presentation = Presentation(
        type=PresentationType.RANKING_BAR,
        axis=PresentationAxis.ENTITY,
        title="  Produtos mais rentáveis  ",
    )

    assert presentation.type is PresentationType.RANKING_BAR
    assert presentation.axis is PresentationAxis.ENTITY
    assert presentation.title == "Produtos mais rentáveis"


def test_proposal_degrada_presentation_invalida_para_table() -> None:

    proposal = InterpretationProposal.model_validate(
        _analytical_proposal({"type": "pie", "axis": "entity", "title": "Ranking"})
    )

    assert proposal.analysis is not None
    assert proposal.analysis.presentation == Presentation()
    assert proposal.analysis.presentation is not None
    assert proposal.analysis.presentation.type is PresentationType.TABLE


def test_proposal_degrada_eixo_invalido_e_line_sem_periodo() -> None:

    bad_axis = InterpretationProposal.model_validate(
        _analytical_proposal({"type": "bar", "axis": "diagonal"})
    )
    bad_line = InterpretationProposal.model_validate(
        _analytical_proposal({"type": "line", "axis": "entity"})
    )

    assert bad_axis.analysis is not None and bad_line.analysis is not None
    assert bad_axis.analysis.presentation == Presentation()
    assert bad_line.analysis.presentation == Presentation()


def test_proposal_preserva_presentation_valida_e_ausente() -> None:

    kept = InterpretationProposal.model_validate(
        _analytical_proposal(
            {"type": "line", "axis": "period", "title": "Evolução da carteira"}
        )
    )
    absent = InterpretationProposal.model_validate(_analytical_proposal())

    assert kept.analysis is not None and absent.analysis is not None
    assert kept.analysis.presentation == Presentation(
        type=PresentationType.LINE,
        axis=PresentationAxis.PERIOD,
        title="Evolução da carteira",
    )
    assert absent.analysis.presentation is None


def test_prompt_localizado_substitui_tudo_e_traz_o_catalogo() -> None:

    prompt = LocalizedInterpretationPromptAdapter().build_system_prompt("pt-BR")

    assert "{{" not in prompt
    assert "profitability" in prompt
    assert "varejo_pf" in prompt
    assert "2026-08-31" in prompt
    assert "pt-BR" in prompt
    assert "last_12_months" in prompt
    assert "reference_snapshot" in prompt
    assert "2025-09-01" in prompt


def test_prompt_usa_a_data_de_referencia_injetada() -> None:

    prompt = LocalizedInterpretationPromptAdapter().build_system_prompt(
        "pt-BR", date(2026, 11, 30)
    )

    assert "2026-11-30" in prompt
    assert "`last_12_months`: 2025-12-01 .. 2026-11-30" in prompt

"""Rota `capability`: pergunta sobre o escopo é respondida pelo catálogo.

O planner escolhe a rota; o handler devolve o texto determinístico de
`describe_capabilities` (sanitizado), sem plano, sem cálculo e sem gate de
lastro. O schema rejeita `capability`
que carregue `analysis`/`calculations`, como em `documental`/`refuse`.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from contexts.auth.adapters.outbound.yaml_capabilities import (
    YamlCapabilitiesAdapter,
)
from contexts.auth.application.queries.authorize import AuthorizeQuery
from contexts.auth.domain.user import Role, User
from contexts.financial_analysis.adapters.outbound.auth_capacity_acl import (
    AuthCapacityAcl,
)
from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.application.commands.answer_question import (
    AnswerQuestionHandler,
)
from contexts.financial_analysis.application.commands.execute_pipeline import (
    AnalysisPipeline,
)
from contexts.financial_analysis.application.commands.interpretation_schema import (
    InterpretationProposal,
)
from contexts.financial_analysis.domain.insight_presentation import (
    sanitize_user_text,
)
from contexts.financial_analysis.domain.interpretation import InterpretationRoute
from contexts.financial_analysis.domain.services.describe_capabilities import (
    describe_capabilities,
)
from contexts.financial_analysis.ports.inbound.user_request import (
    ConversationContext,
    Text,
)
from contexts.financial_analysis.ports.outbound.calculation_port import (
    CalculationPort,
)
from contexts.financial_analysis.ports.outbound.insight_port import InsightPort
from contexts.financial_analysis.ports.outbound.knowledge_port import KnowledgePort
from contexts.financial_analysis.ports.outbound.llm_port import (
    LlmPort,
    LlmReply,
)
from contexts.financial_analysis.ports.outbound.snapshot_version_port import (
    SnapshotVersionPort,
)

USER = User(
    id="u1",
    name="Analista",
    email="a@b.com",
    roles=[Role(id="default", name="Analista")],
)

CATALOG = YamlSemanticCatalogAdapter().load_active()

META_QUESTIONS = [
    "O que você faz?",
    "Quais informações posso perguntar sobre clientes?",
    "Você tem regressão?",
]


class _SequenceLlm(LlmPort):
    def __init__(self, payloads: list[dict[str, Any]]):

        self._payloads = payloads
        self.calls = 0

    async def generate(self, messages, session_id: str | None = None) -> LlmReply:

        raise NotImplementedError

    async def generate_structured(
        self, messages, schema, session_id: str | None = None, step: str = "llm"
    ):

        payload = self._payloads[self.calls]
        self.calls += 1

        return schema.model_validate(payload)


class _Calculation(CalculationPort):
    def __init__(self):

        self.calls = 0

    def execute(self, plans, *, catalog_version, snapshot_version):

        self.calls += 1

        raise AssertionError("a rota capability não executa cálculo")


class _Snapshot(SnapshotVersionPort):
    def current(self) -> str:

        return "2026-08-31"


class _Knowledge(KnowledgePort):
    def __init__(self):

        self.calls = 0

    def retrieve(self, question, *, locale, limit=5):

        self.calls += 1

        return []


class _Insight(InsightPort):
    def __init__(self):

        self.calls = 0

    async def explain(
        self,
        *,
        question,
        result,
        excerpts=(),
        caveats=(),
        session_id=None,
        rejected_numbers=(),
    ) -> str:

        self.calls += 1

        return "Texto de resultado que não deveria existir numa rota capability."


class _Prompt:
    def build_system_prompt(
        self, locale: str, reference_date: date | None = None
    ) -> str:

        return "system"


class _ReferenceDate:
    def latest_reference_date(self) -> date:

        return date(2026, 8, 31)


def _pipeline() -> tuple[AnalysisPipeline, _Calculation, _Knowledge, _Insight]:

    calculation = _Calculation()
    knowledge = _Knowledge()
    insight = _Insight()
    pipeline = AnalysisPipeline(
        calculation=calculation,
        snapshot_version=_Snapshot(),
        knowledge=knowledge,
        insight=insight,
    )

    return pipeline, calculation, knowledge, insight


def _query(llm: LlmPort, pipeline: AnalysisPipeline) -> AnswerQuestionHandler:

    return AnswerQuestionHandler(
        llm=llm,
        prompt=_Prompt(),
        reference_date=_ReferenceDate(),
        catalog=YamlSemanticCatalogAdapter(),
        auth_capacity=AuthCapacityAcl(AuthorizeQuery(YamlCapabilitiesAdapter())),
        pipeline=pipeline,
    )


def _expected_capabilities() -> str:

    return sanitize_user_text(describe_capabilities(CATALOG))


def _plans_payload() -> dict[str, Any]:

    return {
        "analysis": {
            "id": "plan",
            "statistical_method": [
                {
                    "id": "s1",
                    "method": "null",
                    "calculation_plan_ids": ["calc_prof_seg"],
                }
            ],
            "operations": [],
        },
        "calculations": [
            {
                "calculation_plan_id": "calc_prof_seg",
                "metric": {
                    "rule_id": "profitability",
                    "subjects": [{"type": "customer_segmentation", "level": "segment"}],
                },
                "period": {
                    "start": "2025-09-01",
                    "end": "2026-08-31",
                    "type": "series",
                    "grain": "total",
                },
            }
        ],
    }


def test_rota_capability_sem_planos_e_aceita() -> None:

    proposal = InterpretationProposal.model_validate({"route": "capability"})

    assert proposal.route is InterpretationRoute.CAPABILITY
    assert proposal.analysis is None
    assert proposal.calculations == []


def test_rota_capability_com_analysis_e_recusada() -> None:

    payload = _plans_payload()
    payload["route"] = "capability"
    payload.pop("calculations")

    with pytest.raises(ValidationError):
        InterpretationProposal.model_validate(payload)


def test_rota_capability_com_calculations_e_recusada() -> None:

    payload = _plans_payload()
    payload["route"] = "capability"
    payload.pop("analysis")

    with pytest.raises(ValidationError):
        InterpretationProposal.model_validate(payload)


def test_rota_capability_com_o_pacote_inteiro_e_recusada() -> None:

    payload = {**_plans_payload(), "route": "capability"}

    with pytest.raises(ValidationError):
        InterpretationProposal.model_validate(payload)


@pytest.mark.parametrize("question", META_QUESTIONS)
def test_pergunta_meta_roteia_para_capability_e_responde_do_catalogo(
    question: str,
) -> None:

    pipeline, calculation, knowledge, insight = _pipeline()
    llm = _SequenceLlm([{"route": "capability"}])

    contents = asyncio.run(
        _query(llm, pipeline).execute(
            USER,
            ConversationContext(session_id="s1", messages=[]),
            question,
        )
    )

    assert llm.calls == 1
    assert contents == [Text(text=_expected_capabilities())]
    assert calculation.calls == 0
    assert knowledge.calls == 0
    assert insight.calls == 0


def test_resposta_de_capacidade_nao_vaza_numero_de_resultado_nem_id_interno() -> None:

    pipeline, _, _, _ = _pipeline()
    llm = _SequenceLlm([{"route": "capability"}])

    contents = asyncio.run(
        _query(llm, pipeline).execute(
            USER,
            ConversationContext(session_id="s1", messages=[]),
            "O que você faz?",
        )
    )

    text = contents[0].text

    assert "R$" not in text
    assert "%" not in text
    assert "calc_" not in text
    assert "_" not in text
    assert "resultado que não deveria existir" not in text

"""`create_plan`: valida o pacote e recusa o LLM uma vez antes de desistir.

A validação determinística é quem decide; o retry dá ao modelo a chance de
corrigir com o erro tipificado. Sem correção, a rota vira `refuse` com motivo.

Falha de schema (o output não casa com o pydantic) tem o mesmo desenho, com
outro desfecho: um retry com a nota de que o JSON anterior não era válido e,
se falhar de novo, um `clarify` fixo.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

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
from contexts.financial_analysis.ports.inbound.user_request import (
    ConversationContext,
    Structured,
    Text,
)
from contexts.financial_analysis.ports.outbound.llm_port import (
    LlmMessage,
    LlmPort,
    LlmReply,
    StructuredOutputError,
)

USER = User(
    id="u1",
    name="Analista",
    email="a@b.com",
    roles=[Role(id="default", name="Analista")],
)
ANALYST = User(
    id="u2",
    name="Restrito",
    email="r@b.com",
    roles=[Role(id="analista", name="Restrito")],
)


class _Prompt:
    def build_system_prompt(
        self, locale: str, reference_date: date | None = None
    ) -> str:
        return "system"


class _ReferenceDate:
    def latest_reference_date(self) -> date:
        return date(2026, 8, 31)


class _SequenceLlm(LlmPort):
    """Devolve um payload por chamada; um `Exception` na sequência é lançado."""

    def __init__(self, payloads: list[dict[str, Any] | Exception]):

        self._payloads = payloads
        self.calls = 0
        self.last_messages: list[LlmMessage] = []

    async def generate(
        self,
        messages,
        session_id: str | None = None,
    ) -> LlmReply:

        raise NotImplementedError

    async def generate_structured(
        self,
        messages,
        schema,
        session_id: str | None = None,
        step: str = "llm",
    ):

        self.last_messages = list(messages)
        payload = self._payloads[self.calls]
        self.calls += 1

        if isinstance(payload, Exception):
            raise payload

        return schema.model_validate(payload)


def _query(llm: LlmPort) -> AnswerQuestionHandler:

    return AnswerQuestionHandler(
        llm=llm,
        prompt=_Prompt(),
        reference_date=_ReferenceDate(),
        catalog=YamlSemanticCatalogAdapter(),
        auth_capacity=AuthCapacityAcl(AuthorizeQuery(YamlCapabilitiesAdapter())),
    )


def _run_contents(llm: LlmPort, user: User = USER) -> list[Any]:

    return asyncio.run(
        _query(llm).execute(
            user,
            ConversationContext(session_id="s1", messages=[]),
            "Qual segmento foi o mais volátil?",
        )
    )


def _run(llm: LlmPort, user: User = USER) -> dict[str, Any]:

    structured = _run_contents(llm, user)[0]

    assert isinstance(structured, Structured)

    return structured.data


def _schema_failure() -> StructuredOutputError:

    return StructuredOutputError(
        attempts=1, detail="route: Input should be 'analytical', 'documental', ..."
    )


def _calculation() -> dict[str, Any]:

    return {
        "calculation_plan_id": "calc_prof_seg",
        "metric": {
            "rule_id": "profitability",
            "subjects": [{"type": "customer_segmentation", "level": "segment"}],
        },
        "period": {
            "start": "2025-09-01",
            "end": "2026-08-31",
            "type": "series",
            "grain": "month",
        },
    }


def _valid_payload() -> dict[str, Any]:

    return {
        "route": "analytical",
        "analysis": {
            "id": "plan",
            "statistical_method": [
                {
                    "id": "s1",
                    "method": "std",
                    "calculation_plan_ids": ["calc_prof_seg"],
                }
            ],
            "operations": [
                {
                    "id": "o1",
                    "type": "ranking",
                    "refs": ["s1"],
                    "params": {"order": "desc", "axis": "entity"},
                }
            ],
        },
        "calculations": [_calculation()],
    }


def _invalid_payload() -> dict[str, Any]:

    payload = _valid_payload()
    payload["analysis"]["statistical_method"] = [
        {
            "id": "s1",
            "method": "mean",
            "calculation_plan_ids": ["calc_prof_seg"],
        }
    ]
    payload["analysis"]["operations"] = []

    return payload


def _clarify_payload() -> dict[str, Any]:

    return {
        "route": "clarify",
        "clarification_question": "De quando?",
    }


def test_pacote_valido_nao_dispara_retry() -> None:

    llm = _SequenceLlm([_valid_payload()])

    data = _run(llm)

    assert data["route"] == "analytical"
    assert llm.calls == 1


def test_pacote_invalido_e_corrigido_no_retry() -> None:

    llm = _SequenceLlm([_invalid_payload(), _valid_payload()])

    data = _run(llm)

    assert data["route"] == "analytical"
    assert llm.calls == 2
    assert "validação determinística" in llm.last_messages[-1].content


def test_pacote_invalido_duas_vezes_vira_recusa_tipificada() -> None:

    llm = _SequenceLlm([_invalid_payload(), _invalid_payload()])

    data = _run(llm)

    assert data["route"] == "refuse"
    assert data["refusal_reason"] == "not_expressible"
    assert llm.calls == 2


def test_rota_clarify_nao_passa_pela_validacao() -> None:

    llm = _SequenceLlm([_clarify_payload()])

    data = _run(llm)

    assert data["route"] == "clarify"
    assert llm.calls == 1


def test_clarify_com_metrica_sem_acesso_vira_recusa() -> None:
    """A autorização antecede o pedido de esclarecimento: sem acesso à métrica
    citada, a rota `clarify` vira `refuse`/unauthorized sem chamar o LLM de novo."""

    payload = _clarify_payload()
    payload["resolved_terms"] = [
        {"term": "rentabilidade", "canonical": "profitability"}
    ]

    llm = _SequenceLlm([payload])

    data = _run(llm, ANALYST)

    assert data["route"] == "refuse"
    assert data["refusal_reason"] == "unauthorized"
    assert "rentabilidade" in data["refusal_message"]
    assert llm.calls == 1


def test_clarify_com_eixo_sem_acesso_vira_recusa() -> None:
    """`analista` só quebra por produto/total; segmento é negado antes do clarify."""

    payload = _clarify_payload()
    payload["resolved_terms"] = [
        {"term": "carteira", "canonical": "outstanding_balance"},
        {"term": "segmento", "canonical": "customer_segmentation.segment"},
    ]

    data = _run(_SequenceLlm([payload]), ANALYST)

    assert data["route"] == "refuse"
    assert data["refusal_reason"] == "unauthorized"


def test_clarify_com_metrica_autorizada_permanece_clarify() -> None:
    """Sem termo negado, o esclarecimento segue normal."""

    payload = _clarify_payload()
    payload["resolved_terms"] = [
        {"term": "carteira", "canonical": "outstanding_balance"}
    ]

    data = _run(_SequenceLlm([payload]), ANALYST)

    assert data["route"] == "clarify"


def test_falha_de_schema_e_corrigida_no_retry() -> None:
    """Output fora do schema: um retry com a nota de JSON inválido; se o modelo
    corrige, o fluxo segue analítico e o LLM foi chamado duas vezes."""

    llm = _SequenceLlm([_schema_failure(), _valid_payload()])

    data = _run(llm)

    assert data["route"] == "analytical"
    assert llm.calls == 2
    assert "não era um JSON válido" in llm.last_messages[-1].content
    # Nota vai como `user`: alguns provedores OpenAI-compatíveis rejeitam
    # `system` fora da primeira posição.
    assert llm.last_messages[-1].role == "user"


def test_falha_de_schema_duas_vezes_vira_clarify_sem_excecao() -> None:
    """Segunda falha de schema: `clarify` fixo em texto, exatamente duas
    chamadas ao LLM e nenhuma exceção chega ao usuário."""

    llm = _SequenceLlm([_schema_failure(), _schema_failure()])

    contents = _run_contents(llm)

    assert llm.calls == 2
    assert len(contents) == 1
    assert isinstance(contents[0], Text)
    assert contents[0].text.startswith(
        "Não consegui estruturar sua pergunta com segurança."
    )
    assert "rentabilidade, saldo, contratos ou clientes" in contents[0].text


def test_falha_de_schema_no_retry_semantico_vira_clarify() -> None:
    """Plano inválido, e o retry semântico devolve output fora do schema: o
    orçamento de retries já acabou, então a resposta é o `clarify` fixo."""

    llm = _SequenceLlm([_invalid_payload(), _schema_failure()])

    contents = _run_contents(llm)

    assert llm.calls == 2
    assert isinstance(contents[0], Text)
    assert "Não consegui estruturar" in contents[0].text


def test_retry_semantico_com_clarify_negado_e_recusado() -> None:
    """O retry semântico que devolve `clarify` passa pela mesma autorização do
    primeiro passo: termo negado ao perfil vira `refuse`/unauthorized."""

    clarify = _clarify_payload()
    clarify["resolved_terms"] = [
        {"term": "rentabilidade", "canonical": "profitability"}
    ]

    llm = _SequenceLlm([_invalid_payload(), clarify])

    data = _run(llm, ANALYST)

    assert data["route"] == "refuse"
    assert data["refusal_reason"] == "unauthorized"
    assert "rentabilidade" in data["refusal_message"]
    assert llm.calls == 2

"""`SubmitQuestionHandler` e o agregado `Conversation`.

O histórico é do contexto user_interaction: o handler carrega a conversa da
sessão, registra a pergunta JÁ REDIGIDA (nenhum dado pessoal no histórico),
monta o contexto que a análise recebe a partir dos turnos anteriores, registra
a resposta, salva e publica `QuestionSubmitted`/`ResponseDelivered`.
"""

from __future__ import annotations

import asyncio

import pytest

from contexts.auth.domain.user import User
from contexts.financial_analysis.ports.inbound.user_request import (
    ConversationContext,
    MessageRole,
    Text,
)
from contexts.user_interaction.adapters.outbound.in_memory_conversation_store import (
    InMemoryConversationStore,
)
from contexts.user_interaction.application.commands.submit_question import (
    SubmitQuestionHandler,
)
from contexts.user_interaction.domain.conversation import (
    Conversation,
    ConversationError,
)
from contexts.user_interaction.domain.events import (
    QuestionSubmitted,
    ResponseDelivered,
)
from shared.domain_events import DomainEvent, EventDispatcher
from shared.redaction import CPF_PLACEHOLDER

VALID_CPF = "529.982.247-25"
USER = User(id="u1", name="Analista", email="a@b.com", roles=[])


class _RecordingAnalysis:
    def __init__(self) -> None:

        self.contexts: list[ConversationContext] = []
        self.requests: list[str] = []

    async def execute(self, *, user: User, context: ConversationContext, request: str):

        self.contexts.append(context)
        self.requests.append(request)

        return [Text(text=f"Resposta {len(self.requests)}.")]


def _handler() -> tuple[SubmitQuestionHandler, InMemoryConversationStore, list]:

    store = InMemoryConversationStore()
    dispatcher = EventDispatcher()
    published: list[DomainEvent] = []
    dispatcher.subscribe(QuestionSubmitted, published.append)
    dispatcher.subscribe(ResponseDelivered, published.append)

    return (
        SubmitQuestionHandler(_RecordingAnalysis(), store, dispatcher),
        store,
        published,
    )


def _ask(handler: SubmitQuestionHandler, trace_id: str, text: str) -> list:

    return asyncio.run(
        handler.execute(user=USER, session_id="s1", trace_id=trace_id, request=text)
    )


def test_cpf_nao_entra_no_historico_mas_o_port_recebe_o_original() -> None:

    handler, store, _ = _handler()
    question = f"Qual a rentabilidade do cliente {VALID_CPF}?"

    _ask(handler, "t1", question)

    conversation = store.load("s1")
    analysis: _RecordingAnalysis = handler._port  # type: ignore[assignment]

    assert conversation is not None
    (role, contents), _ = conversation.history()
    assert role is MessageRole.USER
    assert all(VALID_CPF not in block.text for block in contents)
    assert any(CPF_PLACEHOLDER in block.text for block in contents)
    assert analysis.requests == [question]


def test_contexto_leva_o_historico_anterior_e_o_trace_do_turno() -> None:

    handler, _, _ = _handler()
    analysis: _RecordingAnalysis = handler._port  # type: ignore[assignment]

    _ask(handler, "t1", "Qual a rentabilidade por segmento?")
    _ask(handler, "t2", "E por produto?")

    first, second = analysis.contexts

    assert first.messages == []
    assert first.trace_id == "t1"
    assert second.trace_id == "t2"
    assert second.session_id == "s1"
    assert [role for role, _ in second.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert second.messages[1][1] == [Text(text="Resposta 1.")]


def test_handler_publica_os_eventos_da_conversa() -> None:

    handler, _, published = _handler()

    _ask(handler, "t1", "Qual a rentabilidade por segmento?")

    assert [type(event) for event in published] == [
        QuestionSubmitted,
        ResponseDelivered,
    ]
    assert all(event.aggregate_id == "s1" for event in published)
    assert published[1].blocks == 1  # type: ignore[attr-defined]


def test_conversa_nao_responde_turno_inexistente_nem_duas_vezes() -> None:

    conversation = Conversation("s1", "u1")

    with pytest.raises(ConversationError):
        conversation.deliver_response("t1", [Text(text="x")])

    conversation.submit_question("t1", [Text(text="pergunta")])
    conversation.deliver_response("t1", [Text(text="resposta")])

    with pytest.raises(ConversationError):
        conversation.deliver_response("t1", [Text(text="de novo")])

    with pytest.raises(ConversationError):
        conversation.submit_question("t1", [Text(text="repetida")])

    assert len(conversation.pull_events()) == 2
    assert conversation.pull_events() == ()

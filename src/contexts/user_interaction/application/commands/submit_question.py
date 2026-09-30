"""Comando `SubmitQuestion`: um turno da conversa, da pergunta à resposta.

O handler carrega (ou cria) a `Conversation` da sessão, registra a pergunta já
redigida, monta o contexto que o contexto de análise espera a partir do
histórico da própria conversa, chama o port inbound da análise, registra a
resposta, salva o agregado e publica os eventos. O adapter de UI só entrega
quem perguntou, em que sessão, o `trace_id` do turno e o texto.
"""

from __future__ import annotations

from contexts.auth.ports.inbound.authorize_port import User
from contexts.financial_analysis.ports.inbound.user_request import (
    Content,
    ConversationContext,
    ProcessUserRequestPort,
    Text,
)
from contexts.user_interaction.domain.conversation import Conversation
from contexts.user_interaction.ports.inbound.user_request_port import UserRequestPort
from contexts.user_interaction.ports.outbound.conversation_store_port import (
    ConversationStorePort,
)
from shared.domain_events import EventDispatcher, EventPublisher
from shared.redaction import redact_personal_identifiers

_MAX_HISTORY_ITEMS = 20


class SubmitQuestionHandler(UserRequestPort):
    """Conduz a `Conversation` de um turno e delega a resposta à análise."""

    def __init__(
        self,
        port: ProcessUserRequestPort,
        store: ConversationStorePort,
        publisher: EventPublisher | None = None,
    ):

        self._port = port
        self._store = store
        self._publisher = publisher or EventDispatcher()

    async def execute(
        self,
        *,
        user: User,
        session_id: str,
        trace_id: str,
        request: str,
        locale: str = "pt-BR",
    ) -> list[Content]:

        conversation = self._store.load(session_id) or Conversation(session_id, user.id)

        # O contexto leva o histórico ANTERIOR ao turno; a pergunta entra na
        # conversa já redigida — o histórico nunca guarda dados pessoais. O
        # port da análise recebe o texto original e o guardrail redige de novo
        # (idempotente) antes de qualquer chamada ao modelo.
        context = ConversationContext(
            session_id=session_id,
            messages=conversation.history(_MAX_HISTORY_ITEMS),
            locale=locale,
            trace_id=trace_id,
        )
        redacted = redact_personal_identifiers(request).text
        conversation.submit_question(trace_id, [Text(text=redacted)])

        contents = await self._port.execute(user=user, context=context, request=request)

        conversation.deliver_response(trace_id, contents)

        self._store.save(conversation)
        self._publisher.publish(conversation.pull_events())

        return contents

"""Agregado `Conversation`: a sessão de um usuário e os seus turnos.

A identidade é o `session_id`. Cada turno tem o `trace_id` do pedido, quem
falou e os blocos de conteúdo. O agregado garante que uma resposta só é
entregue a um turno que existe e ainda não foi respondido, e registra
`QuestionSubmitted` / `ResponseDelivered`. O texto do usuário chega aqui já
redigido (sem dados pessoais): o histórico nunca guarda o original.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from contexts.financial_analysis.ports.inbound.user_request import (
    Content,
    MessageRole,
)
from contexts.user_interaction.domain.events import (
    QuestionSubmitted,
    ResponseDelivered,
)
from shared.domain_events import AggregateRoot

_MAX_TURNS = 40


class ConversationError(ValueError):
    """Transição ilegal da conversa."""


@dataclass(frozen=True)
class Turn:
    """Uma fala na conversa: o turno a que pertence, quem falou e o quê."""

    trace_id: str
    role: MessageRole
    contents: tuple[Content, ...]
    at: datetime

    def __post_init__(self) -> None:

        object.__setattr__(self, "contents", tuple(self.contents))


class Conversation(AggregateRoot):
    """A conversa de uma sessão; guarda os últimos turnos para dar contexto."""

    def __init__(self, session_id: str, user_id: str):

        super().__init__()
        self.session_id = session_id
        self.user_id = user_id
        self.turns: list[Turn] = []

    def submit_question(self, trace_id: str, contents: Sequence[Content]) -> None:
        """Registra a pergunta (já redigida) de um novo turno."""

        if any(turn.trace_id == trace_id for turn in self.turns):
            raise ConversationError(f"o turno '{trace_id}' já existe na conversa.")

        self._append(Turn(trace_id, MessageRole.USER, tuple(contents), _now()))

        self.record(QuestionSubmitted(aggregate_id=self.session_id, trace_id=trace_id))

    def deliver_response(self, trace_id: str, contents: Sequence[Content]) -> None:
        """Registra a resposta do turno; exige a pergunta e proíbe repetir."""

        roles = {turn.role for turn in self.turns if turn.trace_id == trace_id}

        if MessageRole.USER not in roles:
            raise ConversationError(
                f"não há pergunta do turno '{trace_id}' para responder."
            )

        if MessageRole.ASSISTANT in roles:
            raise ConversationError(f"o turno '{trace_id}' já foi respondido.")

        self._append(Turn(trace_id, MessageRole.ASSISTANT, tuple(contents), _now()))

        self.record(
            ResponseDelivered(
                aggregate_id=self.session_id,
                trace_id=trace_id,
                blocks=len(contents),
            )
        )

    def history(
        self, limit: int | None = None
    ) -> list[tuple[MessageRole, list[Content]]]:
        """Os turnos na forma que o contexto de análise espera, do mais antigo."""

        turns = self.turns if limit is None else self.turns[-limit:]

        return [(turn.role, list(turn.contents)) for turn in turns]

    def _append(self, turn: Turn) -> None:

        self.turns = [*self.turns, turn][-_MAX_TURNS:]


def _now() -> datetime:

    return datetime.now(UTC)

"""Eventos de domínio da conversa: identificadores e contadores, nunca texto."""

from __future__ import annotations

from dataclasses import dataclass

from shared.domain_events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class QuestionSubmitted(DomainEvent):
    """O usuário enviou uma pergunta (um turno) na conversa."""

    trace_id: str


@dataclass(frozen=True, kw_only=True)
class ResponseDelivered(DomainEvent):
    """A resposta do turno foi entregue à conversa."""

    trace_id: str
    blocks: int

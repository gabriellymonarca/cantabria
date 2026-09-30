"""Blocos do shared kernel para eventos de domínio.

`DomainEvent` é o fato imutável que um agregado registra ao mudar de estado;
`AggregateRoot` guarda os eventos ainda não publicados; `EventPublisher` é o
contrato que o handler usa para publicá-los; `EventDispatcher` é o roteador
síncrono em processo.

Sem I/O, sem framework e sem palavras do domínio: o que é "PlanProposed" ou
"QuestionSubmitted" pertence a cada contexto.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4


def _new_event_id() -> str:

    return uuid4().hex


def _now() -> datetime:

    return datetime.now(UTC)


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Fato ocorrido em um agregado; carrega identificadores, nunca conteúdo."""

    aggregate_id: str
    event_id: str = field(default_factory=_new_event_id)
    occurred_at: datetime = field(default_factory=_now)


class AggregateRoot:
    """Raiz de agregado: acumula os eventos até o handler os publicar."""

    def __init__(self) -> None:

        self._events: list[DomainEvent] = []

    def record(self, event: DomainEvent) -> None:

        self._events.append(event)

    def pull_events(self) -> tuple[DomainEvent, ...]:
        """Devolve os eventos não confirmados e limpa a lista."""

        events = tuple(self._events)
        self._events.clear()

        return events


class EventPublisher(Protocol):
    """Publica os eventos que um agregado registrou."""

    def publish(self, events: Sequence[DomainEvent]) -> None: ...


EventHandler = Callable[[DomainEvent], None]


class EventDispatcher:
    """Roteador em processo: entrega cada evento aos handlers do seu tipo."""

    def __init__(self) -> None:

        self._handlers: dict[type[DomainEvent], list[EventHandler]] = defaultdict(list)
        self._all: list[EventHandler] = []

    def subscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None:

        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Todo evento, de qualquer tipo (o outbox de auditoria assina assim)."""

        self._all.append(handler)

    def publish(self, events: Sequence[DomainEvent]) -> None:

        for event in events:
            # Os handlers gerais (outbox) veem o evento antes dos reativos: se
            # uma policy falhar, o fato ainda fica na trilha de auditoria.
            for handler in tuple(self._all):
                handler(event)

            for handler in self._handlers.get(type(event), ()):
                handler(event)

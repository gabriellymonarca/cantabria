"""Outbox dos eventos de domínio em MongoDB.

Assina TODOS os eventos publicados no `EventDispatcher` e grava um documento
por evento na coleção `events`: é a trilha de auditoria do barramento. A
escrita é best-effort: uma falha do outbox é registrada no log e o turno segue
(o store de planos/resultados, esse sim, falha alto).
"""

from __future__ import annotations

from dataclasses import asdict

import structlog
from pymongo.database import Database

from cross_cutting.mongo import to_bson_safe
from shared.domain_events import DomainEvent, EventDispatcher

logger = structlog.get_logger(__name__)

_BASE_FIELDS = ("aggregate_id", "event_id", "occurred_at")


class MongoEventOutbox:
    """Persiste cada evento do barramento na coleção `events`."""

    def __init__(self, database: Database, collection: str = "events"):

        self._collection = database[collection]

    def subscribe(self, dispatcher: EventDispatcher) -> None:
        """Passa a registrar todo evento publicado no dispatcher."""

        dispatcher.subscribe_all(self.record)

    def record(self, event: DomainEvent) -> None:

        payload = {
            key: value
            for key, value in asdict(event).items()
            if key not in _BASE_FIELDS
        }

        document = {
            "_id": event.event_id,
            "event": type(event).__name__,
            "aggregate_id": event.aggregate_id,
            "occurred_at": event.occurred_at,
            "payload": to_bson_safe(payload),
        }

        try:
            self._collection.insert_one(document)
        except Exception as error:
            logger.warning(
                "Event outbox write failed",
                event_type=type(event).__name__,
                error=str(error),
            )

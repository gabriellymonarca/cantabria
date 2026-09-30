"""Conversation Store em MongoDB.

Uma conversa é um documento da coleção `conversations` com `_id = session_id`,
o `user_id` e os turnos. O adapter serializa e reconstrói o agregado; o formato
vive em `adapters/conversation_document.py`, compartilhado com a barra lateral.

O `save` faz `$set` nos campos do agregado para preservar o
subdocumento `thread` que a UI mantém na mesma coleção.
"""

from __future__ import annotations

from dataclasses import dataclass

from pymongo.database import Database

from contexts.user_interaction.adapters.conversation_document import (
    conversation_from_document,
    conversation_to_document,
)
from contexts.user_interaction.domain.conversation import Conversation
from contexts.user_interaction.ports.outbound.conversation_store_port import (
    ConversationStorePort,
)
from cross_cutting.mongo import upsert_document


@dataclass
class MongoConversationStore(ConversationStorePort):
    """Persiste a `Conversation` por `session_id`."""

    database: Database
    collection_name: str = "conversations"

    def __post_init__(self) -> None:

        self._collection = self.database[self.collection_name]

    def load(self, session_id: str) -> Conversation | None:

        document = self._collection.find_one({"_id": session_id})

        if document is None or "turns" not in document:
            return None

        return conversation_from_document(document)

    def save(self, conversation: Conversation) -> None:

        upsert_document(
            self._collection,
            {"_id": conversation.session_id},
            {"$set": conversation_to_document(conversation)},
        )

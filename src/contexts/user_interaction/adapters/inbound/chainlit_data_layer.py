"""Data layer do Chainlit sobre a coleção de conversas.

O Chainlit só mostra a barra lateral de sessões quando existe um
`data_layer`; este adapter lê e escreve a MESMA coleção `conversations` que o
`MongoConversationStore`, num subdocumento `thread` (nome, dono, metadados) que
o store preserva. Os passos da UI são derivados dos turnos do agregado na
leitura; passo, elemento e feedback não têm store próprio (no-op) — a fonte do
histórico continua sendo a `Conversation`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from chainlit.data import BaseDataLayer
from chainlit.types import (
    Feedback,
    PageInfo,
    PaginatedResponse,
    Pagination,
    ThreadDict,
    ThreadFilter,
)
from chainlit.user import PersistedUser, User
from pymongo.database import Database

from contexts.financial_analysis.ports.inbound.user_request import MessageRole, Text
from contexts.user_interaction.adapters.conversation_document import (
    conversation_from_document,
)
from contexts.user_interaction.domain.conversation import Turn
from cross_cutting.mongo import upsert_document

if TYPE_CHECKING:
    from chainlit.element import Element, ElementDict
    from chainlit.step import StepDict

_NAME_MAX_CHARS = 60
_NO_NAME = "Nova conversa"


class CantabriaDataLayer(BaseDataLayer):
    """Sessões do Chainlit persistidas no MongoDB, ao lado das conversas."""

    def __init__(self, database: Database, collection_name: str = "conversations"):

        self._collection = database[collection_name]
        self._users = database["users"]

    async def get_user(self, identifier: str) -> PersistedUser | None:
        """Usuário persistido no login — inclui os roles em `metadata`."""

        document = self._users.find_one({"_id": identifier})

        if document is None:
            return None

        return _persisted_user(
            identifier,
            display_name=document.get("display_name"),
            metadata=document.get("metadata"),
        )

    async def create_user(self, user: User) -> PersistedUser | None:
        """Grava o usuário (com os roles) para as conexões seguintes do Chainlit."""

        self._users.update_one(
            {"_id": user.identifier},
            {
                "$set": {
                    "display_name": user.display_name,
                    "metadata": user.metadata,
                }
            },
            upsert=True,
        )

        return _persisted_user(
            user.identifier, display_name=user.display_name, metadata=user.metadata
        )

    async def delete_feedback(self, feedback_id: str) -> bool:

        return False

    async def upsert_feedback(self, feedback: Feedback) -> str:

        return feedback.id or ""

    async def create_element(self, element: Element) -> None:

        return None

    async def get_element(self, thread_id: str, element_id: str) -> ElementDict | None:

        return None

    async def delete_element(
        self, element_id: str, thread_id: str | None = None
    ) -> None:

        return None

    async def create_step(self, step_dict: StepDict) -> None:

        return None

    async def update_step(self, step_dict: StepDict) -> None:

        return None

    async def delete_step(self, step_id: str) -> None:

        return None

    async def get_thread_author(self, thread_id: str) -> str:

        document = self._collection.find_one({"_id": thread_id}, {"thread.user_id": 1})

        return _thread_metadata(document).get("user_id") or ""

    async def delete_thread(self, thread_id: str) -> None:

        self._collection.delete_one({"_id": thread_id})

    async def list_threads(
        self, pagination: Pagination, filters: ThreadFilter
    ) -> PaginatedResponse[ThreadDict]:
        """Lista as conversas do usuário, da mais recente à mais antiga.

        A página seguinte usa o `endCursor` opaco (`updated_at|_id`), que
        ordena de forma estável mesmo com timestamps repetidos.
        """

        if not filters.userId:
            return _page([])

        query: dict[str, Any] = {
            "thread.user_id": filters.userId,
            "turns.0": {"$exists": True},
        }

        if filters.search:
            query["thread.name"] = {
                "$regex": re.escape(filters.search),
                "$options": "i",
            }

        if pagination.cursor:
            window = _cursor_window(pagination.cursor)

            if window is not None:
                query.update(window)

        first = max(pagination.first, 1)
        documents = list(
            self._collection.find(query)
            .sort([("updated_at", -1), ("_id", -1)])
            .limit(first + 1)
        )
        has_next = len(documents) > first
        documents = documents[:first]
        end_cursor = _encode_cursor(documents[-1]) if documents else None

        return _page(
            [_thread(document) for document in documents], has_next, end_cursor
        )

    async def get_thread(self, thread_id: str) -> ThreadDict | None:
        """A thread com o histórico derivado dos turnos da conversa."""

        document = self._collection.find_one({"_id": thread_id})

        return _thread(document, include_steps=True) if document else None

    async def update_thread(
        self,
        thread_id: str,
        name: str | None = None,
        user_id: str | None = None,
        metadata: dict | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Upserta só o subdocumento `thread`; o agregado tem o seu próprio save."""

        fields: dict[str, Any] = {"thread.updated_at": _now_iso()}

        if name is not None:
            fields["thread.name"] = name

        if user_id is not None:
            fields["thread.user_id"] = user_id

        if metadata is not None:
            fields["thread.metadata"] = metadata

        if tags is not None:
            fields["thread.tags"] = tags

        upsert_document(self._collection, {"_id": thread_id}, {"$set": fields})

    async def build_debug_url(self) -> str:

        return ""

    async def close(self) -> None:

        return None

    async def get_favorite_steps(self, user_id: str) -> list[StepDict]:

        return []


def _persisted_user(
    identifier: str,
    display_name: str | None = None,
    metadata: dict | None = None,
) -> PersistedUser:

    return PersistedUser(
        id=identifier,
        identifier=identifier,
        display_name=display_name,
        metadata=metadata or {},
        createdAt=_now_iso(),
    )


def _page(
    data: list[ThreadDict],
    has_next: bool = False,
    end_cursor: str | None = None,
) -> PaginatedResponse[ThreadDict]:

    return PaginatedResponse(
        pageInfo=PageInfo(hasNextPage=has_next, startCursor=None, endCursor=end_cursor),
        data=data,
    )


def _encode_cursor(document: dict) -> str:

    return f"{_iso(document.get('updated_at'))}|{document['_id']}"


def _cursor_window(cursor: str) -> dict | None:
    """O que veio depois do cursor: `updated_at` estritamente menor."""

    encoded, _, identifier = cursor.partition("|")
    updated_at = _parse_iso(encoded)

    if updated_at is None or not identifier:
        return None

    return {
        "$or": [
            {"updated_at": {"$lt": updated_at}},
            {"updated_at": updated_at, "_id": {"$lt": identifier}},
        ]
    }


def _thread(document: dict, include_steps: bool = False) -> ThreadDict:
    """Documento -> `ThreadDict`, com os turnos virando passos na leitura."""

    metadata = _thread_metadata(document)

    if "turns" not in document:
        turns: list[Turn] = []
    else:
        turns = conversation_from_document(document).turns

    created_at = turns[0].at if turns else _parse_iso(metadata.get("updated_at"))

    return {
        "id": str(document["_id"]),
        "createdAt": _iso(created_at),
        "name": metadata.get("name") or _derived_name(turns),
        "userId": metadata.get("user_id"),
        "userIdentifier": metadata.get("user_id"),
        "tags": metadata.get("tags"),
        "metadata": metadata.get("metadata") or {},
        "steps": (
            [step for turn in turns if (step := _step(turn, str(document["_id"])))]
            if include_steps
            else []
        ),
        "elements": [],
    }


def _thread_metadata(document: dict | None) -> dict:

    return (document or {}).get("thread") or {}


def _step(turn: Turn, thread_id: str) -> StepDict | None:
    """Só turnos com texto viram passo; o resto é artefato, não mensagem."""

    text = "\n\n".join(
        content.text for content in turn.contents if isinstance(content, Text)
    )

    if not text:
        return None

    return {
        "id": f"{turn.trace_id}:{turn.role}",
        "threadId": thread_id,
        "type": (
            "user_message" if turn.role is MessageRole.USER else "assistant_message"
        ),
        "output": text,
        "createdAt": _iso(turn.at),
        "metadata": {},
    }


def _derived_name(turns: list[Turn]) -> str:
    """O nome da sessão é a primeira fala do usuário, encurtada."""

    for turn in turns:
        if turn.role is not MessageRole.USER:
            continue

        for content in turn.contents:
            if isinstance(content, Text) and content.text.strip():
                return _truncate(" ".join(content.text.split()))

    return _NO_NAME


def _truncate(text: str) -> str:

    return (
        text if len(text) <= _NAME_MAX_CHARS else text[:_NAME_MAX_CHARS].rstrip() + "…"
    )


def _iso(value: datetime | None) -> str:

    return value.isoformat() if value is not None else ""


def _now_iso() -> str:

    return datetime.now(UTC).isoformat()


def _parse_iso(value: str | None) -> datetime | None:

    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

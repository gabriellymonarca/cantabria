"""Mapeamento `Conversation` <-> documento MongoDB.

Módulo neutro dos adapters do `user_interaction`: o store outbound e o data
layer inbound da barra lateral compartilham o mesmo formato de documento. O
documento é o da coleção `conversations` (`_id = session_id`); o subdocumento
`thread` pertence à UI.
"""

from __future__ import annotations

from datetime import UTC, datetime

from contexts.financial_analysis.ports.inbound.user_request import (
    Content,
    Dataframe,
    Image,
    MessageRole,
    MethodNote,
    Plotly,
    Structured,
    Text,
)
from contexts.user_interaction.domain.conversation import Conversation, Turn
from cross_cutting.mongo import from_bson_safe, to_bson_safe


class ConversationDocumentError(ValueError):
    """Documento de conversa com forma inesperada."""


def conversation_to_document(conversation: Conversation) -> dict:
    """A parte do documento que pertence ao agregado (sem o `thread` da UI)."""

    turns = [
        {
            "trace_id": turn.trace_id,
            "role": str(turn.role),
            "contents": [_content_to_document(content) for content in turn.contents],
            "at": turn.at,
        }
        for turn in conversation.turns
    ]
    timestamps = [turn.at for turn in conversation.turns]

    return {
        "user_id": conversation.user_id,
        "turns": turns,
        "created_at": timestamps[0] if timestamps else None,
        "updated_at": timestamps[-1] if timestamps else None,
    }


def conversation_from_document(document: dict) -> Conversation:
    """Reconstrói o agregado a partir do documento, sem emitir eventos."""

    conversation = Conversation(str(document["_id"]), document.get("user_id", ""))
    conversation.turns = [
        _turn_from_document(turn) for turn in document.get("turns", [])
    ]

    return conversation


def _turn_from_document(document: dict) -> Turn:

    return Turn(
        trace_id=document["trace_id"],
        role=MessageRole(document["role"]),
        contents=tuple(_content_from_document(item) for item in document["contents"]),
        at=_as_utc(document["at"]),
    )


def _content_to_document(content: Content) -> dict:
    """Bloco com tag `type`; os dados passam pelo encoder BSON exato."""

    match content:
        case Text():
            return {"type": "text", "text": content.text}

        case Image():
            return {
                "type": "image",
                "data": content.data,
                "mime_type": content.mime_type,
            }

        case Dataframe():
            return {
                "type": "dataframe",
                "columns": list(content.columns),
                "rows": to_bson_safe(content.rows),
            }

        case Plotly():
            return {"type": "plotly", "figure": to_bson_safe(content.figure)}

        case Structured():
            return {"type": "structured", "data": to_bson_safe(content.data)}

        case MethodNote():
            return {"type": "method_note", "title": content.title, "text": content.text}

    raise ConversationDocumentError(
        f"conteúdo de tipo desconhecido: {type(content).__name__}."
    )


def _content_from_document(document: dict) -> Content:

    kind = document.get("type")

    match kind:
        case "text":
            return Text(text=document["text"])

        case "image":
            return Image(data=bytes(document["data"]), mime_type=document["mime_type"])

        case "dataframe":
            return Dataframe(
                columns=list(document["columns"]),
                rows=from_bson_safe(document["rows"]),
            )

        case "plotly":
            return Plotly(figure=from_bson_safe(document["figure"]))

        case "structured":
            return Structured(data=from_bson_safe(document["data"]))

        case "method_note":
            return MethodNote(title=document["title"], text=document["text"])

    raise ConversationDocumentError(f"bloco de tipo desconhecido: '{kind}'.")


def _as_utc(value: datetime) -> datetime:
    """BSON devolve `datetime` sem tz; o agregado usa UTC explícito."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value

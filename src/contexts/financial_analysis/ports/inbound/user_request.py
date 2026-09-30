from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from contexts.auth.ports.inbound.authorize_port import User


@dataclass(frozen=True)
class Text:
    """A plain-text block."""

    text: str


@dataclass(frozen=True)
class Image:
    """An image block, carried as raw bytes and their media type."""

    data: bytes
    mime_type: str


@dataclass(frozen=True)
class Dataframe:
    """A tabular block, carried as column names and rows."""

    columns: list[str]
    rows: list[list[Any]]


@dataclass(frozen=True)
class Plotly:
    """A chart block, carried as a Plotly figure dictionary."""

    figure: dict[str, Any]


@dataclass(frozen=True)
class Structured:
    """A structured block, carried as a JSON-serializable dictionary."""

    data: dict[str, Any]


@dataclass(frozen=True)
class MethodNote:
    """A collapsible note explaining how the numbers were produced.

    Deterministic text (metric formula, period, method, suppressions, data
    source, reference document); never part of the message body and never a
    carrier of result numbers.
    """

    title: str
    text: str


Content = Text | Image | Dataframe | Plotly | Structured | MethodNote


class MessageRole(StrEnum):
    """Who produced a message in the conversation."""

    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ConversationContext:
    """The conversation a request belongs to: its session, history and locale.

    Older messages come first. ``session_id`` identifies the conversation for
    the providers that route or cache by session. ``locale`` is the user's
    language/region (BCP-47, e.g. ``pt-BR``): it selects the localized surface
    (synonyms, examples, clarification and refusal wording) while the plan ids
    stay canonical. ``trace_id`` identifies the turn: the inbound adapter
    creates it once and it travels through plans, results, insight and trace.
    """

    session_id: str
    messages: list[tuple[MessageRole, list[Content]]]
    locale: str = "pt-BR"
    trace_id: str = ""


class ProcessUserRequestPort(ABC):
    """Processes a user request and returns the content to present."""

    @abstractmethod
    async def execute(
        self,
        user: User,
        context: ConversationContext,
        request: str,
    ) -> list[Content]: ...

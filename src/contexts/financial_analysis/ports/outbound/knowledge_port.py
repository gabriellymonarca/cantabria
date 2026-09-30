from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeExcerpt:
    """A retrieved, approved document excerpt with its provenance."""

    document_id: str
    title: str
    section: str
    text: str
    version: str | None = None


# Outbound (driven) port: approved corporate knowledge is retrieved only to
# support the explanation. It never defines a plan parameter.
class KnowledgePort(ABC):
    """Retrieves approved knowledge excerpts for a question."""

    @abstractmethod
    def retrieve(
        self,
        question: str,
        *,
        locale: str,
        limit: int = 5,
    ) -> Sequence[KnowledgeExcerpt]: ...

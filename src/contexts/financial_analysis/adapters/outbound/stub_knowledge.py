"""Stub de RAG: devolve lista vazia de trechos, sem I/O."""

from __future__ import annotations

from collections.abc import Sequence

from contexts.financial_analysis.ports.outbound.knowledge_port import (
    KnowledgeExcerpt,
    KnowledgePort,
)


class StubKnowledgeAdapter(KnowledgePort):
    """Devolve uma lista vazia de trechos."""

    def retrieve(
        self,
        question: str,
        *,
        locale: str,
        limit: int = 5,
    ) -> Sequence[KnowledgeExcerpt]:

        return []

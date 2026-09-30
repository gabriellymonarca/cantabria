"""Primário semântico com fallback lexical.

Se o primário (Qdrant + embeddings) explodir ou voltar vazio, a mesma pergunta
segue para o fallback (BM25 local). Se ambos voltarem vazios, devolve vazio; a
abstenção é decisão da rota. O primário é opcional: sem Qdrant e sem embeddings
a busca continua lexical.
"""

from __future__ import annotations

from collections.abc import Sequence

import structlog

from contexts.financial_analysis.ports.outbound.knowledge_port import (
    KnowledgeExcerpt,
    KnowledgePort,
)

logger = structlog.get_logger(__name__)


class ResilientKnowledgeAdapter(KnowledgePort):
    """Tenta o acervo semântico; em falha ou vazio, cai no lexical."""

    def __init__(self, primary: KnowledgePort, fallback: KnowledgePort):

        self._primary = primary
        self._fallback = fallback

    def retrieve(
        self,
        question: str,
        *,
        locale: str,
        limit: int = 5,
    ) -> Sequence[KnowledgeExcerpt]:

        try:
            excerpts = self._primary.retrieve(question, locale=locale, limit=limit)
        except Exception as error:
            logger.warning(
                "semantic_knowledge_failed",
                error=str(error),
                error_type=type(error).__name__,
                fallback="bm25",
            )
            excerpts = []

        if excerpts:
            return excerpts

        return self._fallback.retrieve(question, locale=locale, limit=limit)

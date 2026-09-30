"""RAG semântico: trechos aprovados por similaridade no Qdrant.

A ingestão (offline) é quem cria a coleção e os pontos, com payload
`{document_id, title, section, text, version, status, locale}`; aqui só se lê.
`retrieve` embeda a pergunta, busca com filtro `status == "approved"` (e o
locale pedido) e mapeia o payload para `KnowledgeExcerpt`. O `score_threshold`
corta vizinhos fracos: sem trecho relevante a busca volta vazia e a rota decide
entre o fallback lexical e a abstenção.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from qdrant_client import QdrantClient, models

from contexts.financial_analysis.ports.outbound.embedding_port import EmbeddingPort
from contexts.financial_analysis.ports.outbound.knowledge_port import (
    KnowledgeExcerpt,
    KnowledgePort,
)

_STATUS_APPROVED = "approved"
_DEFAULT_COLLECTION = "knowledge"
# Similaridade de cosseno mínima (embeddings normalizados): abaixo disso o
# trecho é vizinho fraco e não lastreia resposta; o vazio devolve a decisão
# para a rota (fallback BM25 ou abstenção).
_DEFAULT_SCORE_THRESHOLD = 0.35
_LOCALE_ALIASES = {"pt": "pt-BR", "pt-br": "pt-BR"}


class QdrantKnowledgeAdapter(KnowledgePort):
    """Busca trechos aprovados por similaridade de cosseno no Qdrant."""

    def __init__(
        self,
        client: QdrantClient,
        embeddings: EmbeddingPort,
        collection: str = _DEFAULT_COLLECTION,
        limit: int = 5,
        score_threshold: float = _DEFAULT_SCORE_THRESHOLD,
    ):

        self._client = client
        self._embeddings = embeddings
        self._collection = collection
        self._limit = limit
        self._score_threshold = score_threshold

    def retrieve(
        self,
        question: str,
        *,
        locale: str,
        limit: int = 5,
    ) -> Sequence[KnowledgeExcerpt]:

        effective_limit = min(limit, self._limit)

        if effective_limit <= 0 or not question.strip():
            return []

        vector = self._embeddings.embed_query(question)

        if not vector:
            return []

        response = self._client.query_points(
            collection_name=self._collection,
            query=vector,
            query_filter=_approved_filter(locale),
            limit=effective_limit,
            score_threshold=self._score_threshold,
            with_payload=True,
        )

        return [
            excerpt
            for point in response.points
            if (excerpt := _to_excerpt(point)) is not None
        ]


def _approved_filter(locale: str) -> models.Filter:

    conditions = [
        models.FieldCondition(
            key="status",
            match=models.MatchValue(value=_STATUS_APPROVED),
        )
    ]

    if locale.strip():
        conditions.append(
            models.FieldCondition(
                key="locale",
                match=models.MatchValue(value=_payload_locale(locale)),
            )
        )

    return models.Filter(must=conditions)


def _payload_locale(locale: str) -> str:

    normalized = locale.strip().lower().replace("_", "-")

    return _LOCALE_ALIASES.get(normalized, locale)


def _to_excerpt(point: Any) -> KnowledgeExcerpt | None:

    payload = point.payload or {}
    document_id = payload.get("document_id")
    text = payload.get("text")

    if not document_id or not text:
        return None

    version = payload.get("version")

    return KnowledgeExcerpt(
        document_id=str(document_id),
        title=str(payload.get("title") or document_id),
        section=str(payload.get("section") or ""),
        text=str(text),
        version=str(version) if version is not None else None,
    )

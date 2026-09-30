"""Embeddings via endpoint OpenAI-compatível (LangChain).

Usado pelo RAG semântico (Qdrant) e pela ingestão de documentos. O endpoint é
o mesmo do `llm` quando `embeddings` não define `base_url`/`api_key` próprios
(ver `cross_cutting.config.AppConfig.resolved_embeddings`).
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_openai import OpenAIEmbeddings

from contexts.financial_analysis.ports.outbound.embedding_port import EmbeddingPort


class LangChainEmbeddingsAdapter(EmbeddingPort):
    """Cliente de embeddings do endpoint configurado."""

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
    ):

        # `check_embedding_ctx_length=False` evita o fatiamento por tiktoken:
        # endpoints compatíveis fora da OpenAI não aceitam o tokenizador.
        # `timeout` curto + sem retry: o caminho de resposta prefere cair no
        # BM25 a segurar a demo num endpoint de embeddings pendurado.
        self._client = OpenAIEmbeddings(
            model=model,
            base_url=base_url,
            api_key=api_key or "not-needed",
            check_embedding_ctx_length=False,
            timeout=5,
            max_retries=0,
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:

        return self._client.embed_documents(list(texts))

    def embed_query(self, text: str) -> list[float]:

        return self._client.embed_query(text)

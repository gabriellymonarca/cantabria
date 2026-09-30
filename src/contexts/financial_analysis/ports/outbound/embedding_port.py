from abc import ABC, abstractmethod
from collections.abc import Sequence


# Outbound (driven) port: transformar texto em vetor para o RAG semântico.
# O fallback lexical (BM25) não usa este port; ele é opcional por construção.
class EmbeddingPort(ABC):
    """Gera embeddings de trechos e de perguntas."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]: ...

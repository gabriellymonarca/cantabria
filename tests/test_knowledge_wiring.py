"""Fiação do RAG: semântico quando configurado; lexical quando não.

A escolha é do composition root e precisa ser à prova de store ausente
(degradação graciosa): sem `QDRANT_URL`, sem a seção
`embeddings` ou com o Qdrant fora do ar, a busca continua sendo o BM25 local.
"""

from __future__ import annotations

from contexts.financial_analysis.adapters.outbound.local_knowledge import (
    LocalKnowledgeAdapter,
)
from cross_cutting.config import (
    AppConfig,
    AuthConfig,
    EmbeddingsConfig,
    LlmConfig,
    LoggingConfig,
    ObservabilityConfig,
)
from entrypoints.composition import build_knowledge


def _config(embeddings: EmbeddingsConfig | None = None) -> AppConfig:

    return AppConfig(
        llm=LlmConfig(
            model="gpt-test",
            base_url="http://127.0.0.1:9/v1",
            api_key="test",
            temperature=0.0,
            timeout=1.0,
            headers={},
            session_header="",
        ),
        embeddings=embeddings,
        auth=AuthConfig(allowed_domains=[]),
        logging=LoggingConfig(level="INFO"),
        observability=ObservabilityConfig(
            enabled=False,
            host="",
            public_key="",
            secret_key="",
            environment="",
            release="",
        ),
    )


def test_sem_qdrant_a_busca_e_lexical(monkeypatch) -> None:

    # String vazia (e não delenv): o `.env` real do host não deve reativar o
    # Qdrant no meio do teste — `load_dotenv` não sobrescreve chave existente.
    monkeypatch.setenv("QDRANT_URL", "")

    assert isinstance(
        build_knowledge(_config(EmbeddingsConfig(model="embed-test"))),
        LocalKnowledgeAdapter,
    )


def test_sem_embeddings_a_busca_e_lexical(monkeypatch) -> None:

    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:6333")

    assert isinstance(build_knowledge(_config()), LocalKnowledgeAdapter)


def test_qdrant_fora_do_ar_cai_no_lexical(monkeypatch) -> None:

    import qdrant_client

    class _UnreachableClient:
        def __init__(self, **kwargs) -> None:

            pass

        def get_collections(self):

            raise ConnectionError("qdrant fora do ar")

    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setattr(qdrant_client, "QdrantClient", _UnreachableClient)

    knowledge = build_knowledge(_config(EmbeddingsConfig(model="embed-test")))

    assert isinstance(knowledge, LocalKnowledgeAdapter)

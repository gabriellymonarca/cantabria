"""RAG semântico no Qdrant e resiliência com fallback BM25.

O client Qdrant é um dublê que devolve pontos fixos: o teste fixa o contrato
(payload aprovado → `KnowledgeExcerpt`), o filtro `status == "approved"`, o teto
do limite e o `score_threshold`. Os três caminhos do adapter resiliente
(primário ok, vazio, exceção) e a composição real com o BM25 local também são
cobertos aqui.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from contexts.financial_analysis.adapters.outbound.local_knowledge import (
    LocalKnowledgeAdapter,
)
from contexts.financial_analysis.adapters.outbound.qdrant_knowledge import (
    QdrantKnowledgeAdapter,
)
from contexts.financial_analysis.adapters.outbound.resilient_knowledge import (
    ResilientKnowledgeAdapter,
)
from contexts.financial_analysis.ports.outbound.embedding_port import EmbeddingPort
from contexts.financial_analysis.ports.outbound.knowledge_port import (
    KnowledgeExcerpt,
    KnowledgePort,
)

_QUESTION = "como se calcula rentabilidade?"


@dataclass
class _Point:
    payload: dict[str, Any]
    score: float = 0.87


class _FakeQdrant:
    def __init__(self, points: list[_Point]):

        self.points = points
        self.calls: list[dict[str, Any]] = []

    def query_points(self, **kwargs: Any) -> SimpleNamespace:

        self.calls.append(kwargs)

        return SimpleNamespace(points=self.points)


class _Embeddings(EmbeddingPort):
    def __init__(self, vector: list[float] | None = None):

        self.vector = vector if vector is not None else [0.1, 0.2, 0.3]
        self.query_calls: list[str] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:

        return [self.vector for _ in texts]

    def embed_query(self, text: str) -> list[float]:

        self.query_calls.append(text)

        return self.vector


class _RecordingKnowledge(KnowledgePort):
    def __init__(
        self,
        excerpts: Sequence[KnowledgeExcerpt] = (),
        error: Exception | None = None,
    ):

        self.excerpts = list(excerpts)
        self.error = error
        self.calls: list[tuple[str, str, int]] = []

    def retrieve(
        self,
        question: str,
        *,
        locale: str,
        limit: int = 5,
    ) -> Sequence[KnowledgeExcerpt]:

        self.calls.append((question, locale, limit))

        if self.error is not None:
            raise self.error

        return self.excerpts[:limit]


def _payload(**overrides: Any) -> dict[str, Any]:

    payload = {
        "document_id": "doc-rentabilidade",
        "title": "Como o banco calcula rentabilidade",
        "section": "Definição",
        "text": "A rentabilidade é o retorno sobre o saldo.",
        "version": "v1",
        "status": "approved",
        "locale": "pt-BR",
    }
    payload.update(overrides)

    return payload


def test_retrieve_embeda_a_pergunta_e_mapeia_o_payload() -> None:

    embeddings = _Embeddings()
    client = _FakeQdrant([_Point(_payload())])
    adapter = QdrantKnowledgeAdapter(client, embeddings)

    excerpts = adapter.retrieve(_QUESTION, locale="pt-BR")

    assert embeddings.query_calls == [_QUESTION]
    assert excerpts == [
        KnowledgeExcerpt(
            document_id="doc-rentabilidade",
            title="Como o banco calcula rentabilidade",
            section="Definição",
            text="A rentabilidade é o retorno sobre o saldo.",
            version="v1",
        )
    ]

    call = client.calls[0]

    assert call["collection_name"] == "knowledge"
    assert call["query"] == [0.1, 0.2, 0.3]
    assert call["limit"] == 5
    assert call["score_threshold"] == 0.35
    assert call["with_payload"] is True


def test_filtro_exige_status_aprovado_e_locale() -> None:

    client = _FakeQdrant([])
    adapter = QdrantKnowledgeAdapter(client, _Embeddings())

    adapter.retrieve("o que é vinculação?", locale="pt_BR")

    conditions = client.calls[0]["query_filter"].must
    matches = {condition.key: condition.match.value for condition in conditions}

    assert matches == {"status": "approved", "locale": "pt-BR"}


def test_limit_e_limitado_ao_teto_do_adapter() -> None:

    client = _FakeQdrant([])
    adapter = QdrantKnowledgeAdapter(client, _Embeddings(), limit=3)

    adapter.retrieve(_QUESTION, locale="pt-BR", limit=10)

    assert client.calls[0]["limit"] == 3


def test_limite_zero_e_pergunta_vazia_nao_chamam_qdrant_nem_embeddings() -> None:

    embeddings = _Embeddings()
    client = _FakeQdrant([])
    adapter = QdrantKnowledgeAdapter(client, embeddings)

    assert adapter.retrieve(_QUESTION, locale="pt-BR", limit=0) == []
    assert adapter.retrieve("   ", locale="pt-BR") == []
    assert embeddings.query_calls == []
    assert client.calls == []


def test_ponto_sem_payload_obrigatorio_e_ignorado() -> None:

    client = _FakeQdrant(
        [_Point(_payload(text=None)), _Point({"document_id": "doc-x"})]
    )
    adapter = QdrantKnowledgeAdapter(client, _Embeddings())

    assert adapter.retrieve(_QUESTION, locale="pt-BR") == []


def test_score_threshold_customizado_e_repassado() -> None:

    client = _FakeQdrant([])
    adapter = QdrantKnowledgeAdapter(client, _Embeddings(), score_threshold=0.7)

    adapter.retrieve(_QUESTION, locale="pt-BR")

    assert client.calls[0]["score_threshold"] == 0.7


def test_resiliente_usa_o_primario_quando_ele_acha() -> None:

    excerpt = KnowledgeExcerpt("doc-a", "Título", "Seção", "texto")
    primary = _RecordingKnowledge([excerpt])
    fallback = _RecordingKnowledge([KnowledgeExcerpt("doc-b", "Outro", "S", "t")])
    adapter = ResilientKnowledgeAdapter(primary, fallback)

    assert adapter.retrieve(_QUESTION, locale="pt-BR") == [excerpt]
    assert fallback.calls == []


def test_resiliente_cai_no_fallback_quando_o_primario_e_vazio() -> None:

    excerpt = KnowledgeExcerpt("doc-b", "Outro", "S", "t")
    primary = _RecordingKnowledge([])
    fallback = _RecordingKnowledge([excerpt])
    adapter = ResilientKnowledgeAdapter(primary, fallback)

    assert adapter.retrieve(_QUESTION, locale="pt-BR", limit=2) == [excerpt]
    assert primary.calls == [(_QUESTION, "pt-BR", 2)]
    assert fallback.calls == [(_QUESTION, "pt-BR", 2)]


def test_resiliente_cai_no_fallback_quando_o_primario_explode() -> None:

    excerpt = KnowledgeExcerpt("doc-b", "Outro", "S", "t")
    primary = _RecordingKnowledge(error=RuntimeError("qdrant fora"))
    fallback = _RecordingKnowledge([excerpt])
    adapter = ResilientKnowledgeAdapter(primary, fallback)

    assert adapter.retrieve(_QUESTION, locale="pt-BR") == [excerpt]


def test_resiliente_devolve_vazio_quando_ambos_sao_vazios() -> None:

    adapter = ResilientKnowledgeAdapter(
        _RecordingKnowledge([]), _RecordingKnowledge([])
    )

    assert adapter.retrieve(_QUESTION, locale="pt-BR") == []


def test_resiliente_com_bm25_local_recupera_mesmo_sem_qdrant() -> None:

    qdrant = QdrantKnowledgeAdapter(_FakeQdrant([]), _Embeddings())
    adapter = ResilientKnowledgeAdapter(qdrant, LocalKnowledgeAdapter())

    excerpts = adapter.retrieve(_QUESTION, locale="pt-BR")

    assert excerpts
    assert excerpts[0].document_id == "doc-rentabilidade"

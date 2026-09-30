"""Ingestão dos documentos aprovados no Qdrant.

Cobre o contrato sem Docker e sem endpoint: chunk por seção `##` no mesmo
formato do `local_knowledge.py` (texto indexado = título + cabeçalho + corpo),
id de ponto determinístico, skip de não aprovados, upsert idempotente com
fakes e falha clara quando `config.yaml` não tem a seção `embeddings`.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import yaml
from utils.generate_reference_documents import (
    ReferenceDocument,
    generate_documents,
    load_knowledge_documents,
    parse_docx_document,
    parse_pptx_document,
)
from utils.ingest_documents import (
    POINT_NAMESPACE,
    IngestError,
    IngestReport,
    LocalMarkdownSource,
    MinioDocumentSource,
    chunk_documents,
    embedder_from_config,
    ingest_documents,
    point_id,
)

from contexts.financial_analysis.ports.outbound.embedding_port import EmbeddingPort

_APPROVED = """---
document_id: doc-rentabilidade
title: Como o banco calcula rentabilidade
version: v2
status: approved
locale: pt-BR
---

## O que é rentabilidade

Rentabilidade é a taxa anual que mede o retorno da carteira.

## Fórmula de rentabilidade

A margem oficial já é anualizada em reais por ano.
"""

_DRAFT = """---
document_id: doc-rascunho
title: Rascunho de método
version: v1
status: draft
locale: pt-BR
---

## Seção não aprovada

Conteúdo que não pode ser indexado.
"""


class _Embedder(EmbeddingPort):
    def __init__(self, size: int = 3):

        self._size = size
        self.calls: list[list[str]] = []

    def embed(self, texts):

        batch = list(texts)
        self.calls.append(batch)

        return [[float(index + 1)] * self._size for index, _ in enumerate(batch)]

    def embed_query(self, text):

        return [0.0] * self._size


class _Store:
    def __init__(self):

        self.collections: list[tuple[str, int]] = []
        self.upserts: list[tuple[str, list]] = []

    def ensure_collection(self, collection: str, *, size: int) -> None:

        self.collections.append((collection, size))

    def upsert(self, collection: str, points) -> None:

        self.upserts.append((collection, list(points)))


class _FakeObject:
    def __init__(self, name: str):

        self.object_name = name


class _FakeBody:
    def __init__(self, data: bytes):

        self._data = data

    def read(self) -> bytes:

        return self._data

    def close(self) -> None:

        pass

    def release_conn(self) -> None:

        pass


class _FakeMinioReader:
    def __init__(self, objects: dict[str, bytes]):

        self._objects = objects

    def list_objects(self, bucket: str, recursive: bool = False):

        return [_FakeObject(name) for name in self._objects]

    def get_object(self, bucket: str, name: str):

        return _FakeBody(self._objects[name])


def _corpus(tmp_path: Path) -> Path:

    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "01-rentabilidade.md").write_text(_APPROVED, encoding="utf-8")
    (knowledge / "02-rascunho.md").write_text(_DRAFT, encoding="utf-8")

    return knowledge


def _base_config() -> dict:

    return {
        "llm": {
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "api_key": "CHANGE_ME",
            "temperature": 0.0,
            "timeout": 60.0,
            "headers": {},
            "session_header": "",
        },
        "auth": {"allowed_domains": []},
        "logging": {"level": "INFO"},
        "observability": {
            "enabled": False,
            "host": "http://localhost:3000",
            "public_key": "",
            "secret_key": "",
            "environment": "local",
            "release": "",
        },
    }


def test_source_local_carrega_apenas_aprovados(tmp_path: Path) -> None:

    documents = LocalMarkdownSource(_corpus(tmp_path)).load()

    assert [document.document_id for document in documents] == ["doc-rentabilidade"]


def test_chunk_por_secao_com_texto_indexado(tmp_path: Path) -> None:

    documents = LocalMarkdownSource(_corpus(tmp_path)).load()
    chunks = chunk_documents(documents)

    assert [(chunk.document_id, chunk.section) for chunk in chunks] == [
        ("doc-rentabilidade", "O que é rentabilidade"),
        ("doc-rentabilidade", "Fórmula de rentabilidade"),
    ]

    first = chunks[0]

    assert first.embedding_text == (
        "Como o banco calcula rentabilidade O que é rentabilidade "
        "Rentabilidade é a taxa anual que mede o retorno da carteira."
    )
    assert first.payload() == {
        "document_id": "doc-rentabilidade",
        "title": "Como o banco calcula rentabilidade",
        "section": "O que é rentabilidade",
        "text": "Rentabilidade é a taxa anual que mede o retorno da carteira.",
        "version": "v2",
        "status": "approved",
        "locale": "pt-BR",
    }


def test_nao_aprovado_e_ignorado(tmp_path: Path) -> None:

    documents = LocalMarkdownSource(_corpus(tmp_path)).load()
    documents.append(
        ReferenceDocument(
            document_id="doc-x",
            title="Não aprovado",
            version="v1",
            status="draft",
            locale="pt-BR",
            sections=(("Seção", "Corpo"),),
        )
    )

    chunks = chunk_documents(documents)

    assert all(chunk.document_id != "doc-x" for chunk in chunks)
    assert len(chunks) == 2


def test_id_de_ponto_e_deterministico() -> None:

    expected = str(
        uuid.uuid5(POINT_NAMESPACE, "doc-rentabilidade::O que é rentabilidade")
    )

    assert point_id("doc-rentabilidade", "O que é rentabilidade") == expected
    assert point_id("doc-rentabilidade", "O que é rentabilidade") == point_id(
        "doc-rentabilidade", "O que é rentabilidade"
    )
    assert point_id("doc-rentabilidade", "Fórmula") != expected
    assert point_id("doc-outro", "O que é rentabilidade") != expected


def test_upsert_idempotente_com_fakes(tmp_path: Path) -> None:

    documents = LocalMarkdownSource(_corpus(tmp_path)).load()
    embedder = _Embedder()
    store = _Store()

    report = ingest_documents(
        documents, embedder=embedder, store=store, collection="knowledge"
    )

    assert report == IngestReport(documents=1, chunks=2)
    assert store.collections == [("knowledge", 3)]

    collection, points = store.upserts[0]
    chunks = chunk_documents(documents)

    assert collection == "knowledge"
    assert [point.point_id for point in points] == [chunk.point_id for chunk in chunks]
    assert points[0].payload["status"] == "approved"
    assert points[0].vector == (1.0, 1.0, 1.0)
    assert embedder.calls == [[chunk.embedding_text for chunk in chunks]]

    ingest_documents(documents, embedder=embedder, store=store)

    assert [point.point_id for point in store.upserts[1][1]] == [
        point.point_id for point in points
    ]


def test_dry_run_nao_chama_embeddings_nem_store(tmp_path: Path) -> None:

    documents = LocalMarkdownSource(_corpus(tmp_path)).load()
    embedder = _Embedder()
    store = _Store()

    report = ingest_documents(documents, embedder=embedder, store=store, dry_run=True)

    assert report == IngestReport(documents=1, chunks=2)
    assert embedder.calls == []
    assert store.collections == []
    assert store.upserts == []


def test_embeddings_ausentes_falha_com_mensagem_clara(tmp_path: Path) -> None:

    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(_base_config()), encoding="utf-8")

    with pytest.raises(IngestError, match="embeddings"):
        embedder_from_config(config)


def test_embeddings_configurados_montam_o_adapter(tmp_path: Path) -> None:

    raw = _base_config()
    raw["embeddings"] = {"model": "text-embedding-3-small"}
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(raw), encoding="utf-8")

    assert isinstance(embedder_from_config(config), EmbeddingPort)


def test_minio_source_reconstroi_os_mesmos_trechos(tmp_path: Path) -> None:

    knowledge = _corpus(tmp_path)
    reference = tmp_path / "reference"
    generate_documents(knowledge, reference)

    approved = load_knowledge_documents(knowledge)
    # Chave canônica do Value Object Store (a mesma do upload do gerador).
    objects = {
        "documents/doc-rentabilidade/v2/doc-rentabilidade.docx": (
            reference / "doc-rentabilidade__v2.docx"
        ).read_bytes(),
        "documents/doc-rentabilidade/v2/doc-rentabilidade.pptx": (
            reference / "doc-rentabilidade__v2.pptx"
        ).read_bytes(),
    }

    source = MinioDocumentSource(
        bucket="cantabria-docs", client=_FakeMinioReader(objects)
    )
    parsed = source.load()

    assert parsed == approved
    assert [chunk.point_id for chunk in chunk_documents(parsed)] == [
        chunk.point_id for chunk in chunk_documents(approved)
    ]

    docx = parse_docx_document(
        objects["documents/doc-rentabilidade/v2/doc-rentabilidade.docx"]
    )
    pptx = parse_pptx_document(
        objects["documents/doc-rentabilidade/v2/doc-rentabilidade.pptx"]
    )

    assert docx == approved[0]
    assert pptx == approved[0]

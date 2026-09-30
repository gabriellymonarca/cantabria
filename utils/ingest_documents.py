#!/usr/bin/env python3
"""Ingestão dos documentos aprovados no Qdrant (RAG semântico).

Fora do caminho de resposta: este CLI roda como passo separado
do seed/demo. Lê os documentos aprovados — `--source local` (default), os
`data/knowledge/*.md`; ou `--source minio`, os `.docx`/`.pptx` publicados no
bucket — e quebra cada seção `##` em um trecho. O texto indexado é
`título + cabeçalho + corpo`, o MESMO formato do `local_knowledge.py` (BM25);
o payload guarda o corpo em `text`.

Embeddings vêm do endpoint OpenAI-compatível configurado em `config.yaml`
(`embeddings`; sem a seção o CLI falha com mensagem clara). O upsert no Qdrant
(collection `knowledge`, `QDRANT_URL`) é idempotente: o id do ponto é
determinístico (`uuid5` de `document_id` + seção), então re-ingerir atualiza o
payload do mesmo ponto. Documentos com `status != approved` são ignorados.

Uso:
    python utils/ingest_documents.py                        # acervo local
    python utils/ingest_documents.py --source minio         # docs do MinIO
    python utils/ingest_documents.py --dry-run              # só lista o plano
    python utils/ingest_documents.py --collection knowledge
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from utils.generate_reference_documents import (  # noqa: E402
    DEFAULT_BUCKET,
    DEFAULT_KNOWLEDGE_DIR,
    ReferenceDocument,
    load_knowledge_documents,
    minio_client_from_env,
    parse_docx_document,
    parse_pptx_document,
)

from contexts.financial_analysis.ports.outbound.embedding_port import (  # noqa: E402
    EmbeddingPort,
)
from cross_cutting.config import ConfigError, load_config  # noqa: E402

DEFAULT_COLLECTION = "knowledge"
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_BATCH_SIZE = 32

# Namespace fixo do uuid5: nunca mudar, senão os pontos passam a duplicar.
POINT_NAMESPACE = uuid.UUID("8ce0f00d-4344-4b38-ac34-49a0504f1c6b")


class IngestError(RuntimeError):
    """Falha de configuração/contrato da ingestão."""


@dataclass(frozen=True)
class KnowledgeChunk:
    """Uma seção `##` aprovada, pronta para embeddar e indexar."""

    document_id: str
    title: str
    section: str
    text: str
    version: str
    status: str
    locale: str

    @property
    def point_id(self) -> str:

        return point_id(self.document_id, self.section)

    @property
    def embedding_text(self) -> str:
        """Mesmo texto que o BM25 do `local_knowledge` indexa."""

        return f"{self.title} {self.section} {self.text}"

    def payload(self) -> dict[str, str]:

        return {
            "document_id": self.document_id,
            "title": self.title,
            "section": self.section,
            "text": self.text,
            "version": self.version,
            "status": self.status,
            "locale": self.locale,
        }


@dataclass(frozen=True)
class VectorPoint:
    """Ponto já vetorizado, no contrato mínimo do store."""

    point_id: str
    vector: tuple[float, ...]
    payload: dict[str, str]


@dataclass(frozen=True)
class IngestReport:
    """Resumo do que foi (ou seria) indexado."""

    documents: int
    chunks: int


class VectorStore(Protocol):
    """Contrato mínimo do índice vetorial (Qdrant real ou fake de teste)."""

    def ensure_collection(self, collection: str, *, size: int) -> None: ...

    def upsert(self, collection: str, points: Sequence[VectorPoint]) -> None: ...


def point_id(document_id: str, section: str) -> str:
    """Id determinístico do trecho: re-ingerir substitui, não duplica."""

    return str(uuid.uuid5(POINT_NAMESPACE, f"{document_id}::{section}"))


def chunk_document(document: ReferenceDocument) -> list[KnowledgeChunk]:

    chunks: list[KnowledgeChunk] = []

    for section, text in document.sections:
        if not text.strip():
            continue

        chunks.append(
            KnowledgeChunk(
                document_id=document.document_id,
                title=document.title,
                section=section,
                text=text,
                version=document.version,
                status=document.status,
                locale=document.locale,
            )
        )

    return chunks


def chunk_documents(
    documents: Sequence[ReferenceDocument],
) -> list[KnowledgeChunk]:
    """Quebra os aprovados em trechos por seção, ordenados e estáveis."""

    chunks: list[KnowledgeChunk] = []

    for document in sorted(documents, key=lambda item: item.document_id):
        if document.status != "approved":
            continue

        chunks.extend(chunk_document(document))

    return chunks


def ingest_documents(
    documents: Sequence[ReferenceDocument],
    *,
    embedder: EmbeddingPort | None = None,
    store: VectorStore | None = None,
    collection: str = DEFAULT_COLLECTION,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
) -> IngestReport:
    """Embeds e faz upsert idempotente dos trechos aprovados."""

    chunks = chunk_documents(documents)
    report = IngestReport(
        documents=len({chunk.document_id for chunk in chunks}),
        chunks=len(chunks),
    )

    if dry_run:
        return report

    if embedder is None or store is None:
        raise IngestError("embedder e store são obrigatórios fora do --dry-run.")

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors = embedder.embed([chunk.embedding_text for chunk in batch])

        if len(vectors) != len(batch):
            raise IngestError(
                f"embeddings retornaram {len(vectors)} vetores para "
                f"{len(batch)} trechos."
            )

        store.ensure_collection(collection, size=len(vectors[0]))
        store.upsert(
            collection,
            [
                VectorPoint(
                    point_id=chunk.point_id,
                    vector=tuple(vector),
                    payload=chunk.payload(),
                )
                for chunk, vector in zip(batch, vectors, strict=False)
            ],
        )

    return report


def embedder_from_config(config_path: Path = Path("config.yaml")) -> EmbeddingPort:
    """Monta o adapter de embeddings; exige a seção `embeddings` preenchida."""

    config = load_config(config_path)
    embeddings = config.resolved_embeddings()

    if embeddings is None:
        raise IngestError(
            f"config {config_path} sem a seção `embeddings`: preencha "
            "`embeddings.model` (e `base_url`/`api_key`, se próprios) para "
            "habilitar o RAG semântico, ou rode com --dry-run."
        )

    from contexts.financial_analysis.adapters.outbound.langchain_embeddings import (
        LangChainEmbeddingsAdapter,
    )

    return LangChainEmbeddingsAdapter(
        model=embeddings.model,
        base_url=embeddings.base_url,
        api_key=embeddings.api_key,
    )


class LocalMarkdownSource:
    """Acervo `data/knowledge/*.md` (só aprovados)."""

    def __init__(self, knowledge_dir: Path = DEFAULT_KNOWLEDGE_DIR):

        self._knowledge_dir = knowledge_dir

    def load(self) -> list[ReferenceDocument]:

        return load_knowledge_documents(self._knowledge_dir)


class MinioDocumentSource:
    """Documentos de referência `.docx`/`.pptx` publicados no bucket.

    O par docx/pptx representa o mesmo documento; a primeira ocorrência (docx,
    na ordem lexicográfica) vence, para não repetir embeddings/trechos — os
    ids de ponto seriam os mesmos de qualquer forma.
    """

    def __init__(self, *, bucket: str, client):

        self._bucket = bucket
        self._client = client

    def load(self) -> list[ReferenceDocument]:

        names = sorted(
            item.object_name
            for item in self._client.list_objects(self._bucket, recursive=True)
        )
        documents: list[ReferenceDocument] = []
        seen: set[str] = set()

        for name in names:
            suffix = Path(name).suffix.lower()

            if suffix not in (".docx", ".pptx"):
                continue

            data = _download(self._client, self._bucket, name)
            document = (
                parse_docx_document(data)
                if suffix == ".docx"
                else parse_pptx_document(data)
            )

            if document is None or document.document_id in seen:
                continue

            seen.add(document.document_id)
            documents.append(document)

        return sorted(documents, key=lambda item: item.document_id)


def _download(client, bucket: str, name: str) -> bytes:

    response = client.get_object(bucket, name)

    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


class QdrantVectorStore:
    """Wrapper fino do `QdrantClient`; import preguiçoso (testes sem Docker)."""

    def __init__(self, url: str, client=None):

        if client is not None:
            self._client = client
            return

        from qdrant_client import QdrantClient

        self._client = QdrantClient(url=url)

    def ensure_collection(self, collection: str, *, size: int) -> None:

        from qdrant_client.models import Distance, VectorParams

        if self._client.collection_exists(collection):
            return

        self._client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=size, distance=Distance.COSINE),
        )

    def upsert(self, collection: str, points: Sequence[VectorPoint]) -> None:

        from qdrant_client.models import PointStruct

        self._client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=point.point_id,
                    vector=list(point.vector),
                    payload=point.payload,
                )
                for point in points
            ],
            wait=True,
        )


def main() -> int:

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("local", "minio"), default="local")
    parser.add_argument(
        "--config", type=Path, default=Path("config.yaml"), help="config do app"
    )
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=DEFAULT_KNOWLEDGE_DIR,
        help="diretório do acervo (--source local)",
    )
    parser.add_argument(
        "--bucket",
        default=None,
        help="bucket MinIO (--source minio; default MINIO_BUCKET/cantabria-docs)",
    )
    parser.add_argument("--url", default=None, help="QDRANT_URL")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="lista os trechos sem chamar embeddings/Qdrant",
    )
    args = parser.parse_args()

    from entrypoints.env import load_dotenv

    load_dotenv()

    if args.source == "local":
        source = LocalMarkdownSource(args.knowledge)
    else:
        bucket = args.bucket or os.environ.get("MINIO_BUCKET") or DEFAULT_BUCKET
        source = MinioDocumentSource(bucket=bucket, client=minio_client_from_env())

    embedder: EmbeddingPort | None = None
    store: VectorStore | None = None

    if not args.dry_run:
        try:
            embedder = embedder_from_config(args.config)
        except (ConfigError, IngestError) as error:
            raise SystemExit(f"erro: {error}") from None

        store = QdrantVectorStore(
            url=args.url or os.environ.get("QDRANT_URL") or DEFAULT_QDRANT_URL
        )

    try:
        report = ingest_documents(
            source.load(),
            embedder=embedder,
            store=store,
            collection=args.collection,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as error:
        raise SystemExit(f"erro: {error}") from None

    prefix = "dry-run" if args.dry_run else "OK"
    print(
        f"{prefix}: {report.documents} documentos e {report.chunks} trechos/"
        f"seções no acervo (collection '{args.collection}')."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())

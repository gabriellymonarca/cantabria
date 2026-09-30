#!/usr/bin/env python3
"""Gera os documentos de referência (.docx/.pptx) determinísticos do acervo.

Lê `data/knowledge/*.md` com `status: approved` e materializa, um par por
documento, `<document_id>__<version>.docx` e `<document_id>__<version>.pptx`
em `data/reference/` (`--out` configurável). Título, versão, document_id e
status aparecem no corpo e no nome do arquivo; cada seção `##` vira um
título de divisão (docx) ou um slide (pptx), de modo que a ingestão consegue
reconstruir os mesmos trechos do markdown.

Determinismo: para o mesmo insumo os bytes são idênticos. As core properties
recebem data fixa e o pacote OOXML é reempacotado com timestamps de ZIP fixos
(`canonical_zip`); nenhum `date.today()`/`datetime.now()` entra no artefato.

`--upload` envia os arquivos ao MinIO (bucket default `cantabria-docs`,
sobrescrevível por `MINIO_BUCKET`) na chave do Value Object Store
(`documents/<document_id>/<version>/...`); o modo default só grava em disco —
a demo roda offline.

Uso:
    python utils/generate_reference_documents.py
    python utils/generate_reference_documents.py --out data/reference
    python utils/generate_reference_documents.py --upload
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml
from docx import Document
from pptx import Presentation

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

DEFAULT_KNOWLEDGE_DIR = REPO_ROOT / "data" / "knowledge"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "reference"
DEFAULT_BUCKET = "cantabria-docs"

# Fixos por contrato: mudar qualquer um dos dois quebra a reprodutibilidade
# byte a byte dos artefatos (coberto por testes).
FIXED_DATETIME = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
AUTHOR = "Cantabria (ficticio)"

_CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

_HEADING = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_METADATA_FIELDS = (
    ("title", "Título"),
    ("version", "Versão"),
    ("document_id", "Documento"),
    ("status", "Status"),
    ("locale", "Locale"),
)
_LABEL_TO_FIELD = {label: field for field, label in _METADATA_FIELDS}


@dataclass(frozen=True)
class ReferenceDocument:
    """Documento aprovado do acervo, parseado para geração e ingestão."""

    document_id: str
    title: str
    version: str
    status: str
    locale: str
    sections: tuple[tuple[str, str], ...]


def split_frontmatter(raw: str) -> tuple[dict, str]:
    """Separa o frontmatter YAML do corpo (mesma regra do `local_knowledge`)."""

    if not raw.startswith("---\n"):
        return {}, raw

    end = raw.find("\n---\n", 4)

    if end == -1:
        return {}, raw

    try:
        front = yaml.safe_load(raw[4:end]) or {}
    except yaml.YAMLError:
        return {}, raw

    if not isinstance(front, dict):
        return {}, raw

    return front, raw[end + 5 :]


def split_sections(body: str) -> tuple[tuple[str, str], ...]:
    """Divide o corpo nas seções `##` (mesma regra do `local_knowledge`)."""

    matches = list(_HEADING.finditer(body))

    if not matches:
        return (("geral", body.strip()),)

    sections: list[tuple[str, str]] = []

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append((match.group(1).strip(), body[start:end].strip()))

    return tuple(sections)


def parse_markdown_document(path: Path) -> ReferenceDocument | None:
    """Lê um `.md` aprovado; devolve `None` para não aprovado ou sem id."""

    front, body = split_frontmatter(path.read_text(encoding="utf-8"))

    if front.get("status") != "approved":
        return None

    document_id = str(front.get("document_id", "")).strip()

    if not document_id:
        return None

    return ReferenceDocument(
        document_id=document_id,
        title=str(front.get("title", document_id)),
        version=str(front.get("version", "v1")),
        status="approved",
        locale=str(front.get("locale", "pt-BR")),
        sections=tuple(
            (section, text) for section, text in split_sections(body) if text.strip()
        ),
    )


def load_knowledge_documents(knowledge_dir: Path) -> list[ReferenceDocument]:
    """Carrega, por `document_id`, apenas os documentos aprovados do acervo."""

    if not knowledge_dir.is_dir():
        raise FileNotFoundError(f"acervo não encontrado em {knowledge_dir}")

    documents: list[ReferenceDocument] = []

    for path in sorted(knowledge_dir.glob("*.md")):
        document = parse_markdown_document(path)

        if document is not None:
            documents.append(document)

    return sorted(documents, key=lambda item: item.document_id)


def canonical_zip(data: bytes) -> bytes:
    """Reempacota o OOXML com entradas ordenadas e datas fixas.

    O `zipfile` grava o horário corrente em cada entrada; sem normalizar, o
    mesmo documento gerado duas vezes teria bytes diferentes. A ordem das
    entradas também é fixada (lexicográfica) pelo mesmo motivo.
    """

    with zipfile.ZipFile(io.BytesIO(data)) as source:
        entries = sorted(
            (info.filename, source.read(info.filename)) for info in source.infolist()
        )

    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name, payload in entries:
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o644 << 16
            target.writestr(info, payload)

    return buffer.getvalue()


def _paragraphs(text: str) -> list[str]:
    """Quebra o corpo em parágrafos (blocos separados por linha em branco)."""

    blocks = re.split(r"\n\s*\n", text.strip())

    return [" ".join(block.split()) for block in blocks if block.strip()]


def render_docx(document: ReferenceDocument) -> bytes:
    """Monta o `.docx` do documento com metadados visíveis e seções `##`."""

    doc = Document()
    doc.add_heading(document.title, level=0)

    for field, label in _METADATA_FIELDS:
        doc.add_paragraph(f"{label}: {getattr(document, field)}")

    for section, text in document.sections:
        doc.add_heading(section, level=2)

        for block in _paragraphs(text):
            doc.add_paragraph(block)

    core = doc.core_properties
    core.author = AUTHOR
    core.last_modified_by = AUTHOR
    core.title = document.title
    core.revision = 1
    core.created = FIXED_DATETIME
    core.modified = FIXED_DATETIME

    buffer = io.BytesIO()
    doc.save(buffer)

    return canonical_zip(buffer.getvalue())


def render_pptx(document: ReferenceDocument) -> bytes:
    """Monta o `.pptx`: capa com metadados e um slide por seção `##`."""

    presentation = Presentation()
    cover = presentation.slides.add_slide(presentation.slide_layouts[0])
    cover.shapes.title.text = document.title
    cover.placeholders[1].text = "\n".join(
        f"{label}: {getattr(document, field)}" for field, label in _METADATA_FIELDS
    )

    for section, text in document.sections:
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = section
        blocks = _paragraphs(text) or [""]
        body = slide.placeholders[1].text_frame
        body.text = blocks[0]

        for block in blocks[1:]:
            body.add_paragraph().text = block

    core = presentation.core_properties
    core.author = AUTHOR
    core.last_modified_by = AUTHOR
    core.title = document.title
    core.revision = 1
    core.created = FIXED_DATETIME
    core.modified = FIXED_DATETIME

    buffer = io.BytesIO()
    presentation.save(buffer)

    return canonical_zip(buffer.getvalue())


RENDERERS = {"docx": render_docx, "pptx": render_pptx}


def parse_docx_document(data: bytes) -> ReferenceDocument | None:
    """Reconstrói o documento a partir do `.docx` gerado (round-trip)."""

    doc = Document(io.BytesIO(data))
    metadata: dict[str, str] = {}
    heading: str | None = None
    sections: list[tuple[str, list[str]]] = []

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()

        if not text:
            continue

        if paragraph.style.name == "Title":
            metadata.setdefault("title", text)
            continue

        if paragraph.style.name == "Heading 2":
            heading = text
            sections.append((heading, []))
            continue

        label, separator, value = text.partition(":")

        if heading is None and separator and label.strip() in _LABEL_TO_FIELD:
            metadata[_LABEL_TO_FIELD[label.strip()]] = value.strip()
        elif heading is not None:
            sections[-1][1].append(text)

    document_id = metadata.get("document_id", "").strip()

    if not document_id:
        return None

    return ReferenceDocument(
        document_id=document_id,
        title=metadata.get("title", document_id),
        version=metadata.get("version", "v1"),
        status=metadata.get("status", ""),
        locale=metadata.get("locale", "pt-BR"),
        sections=tuple((section, "\n\n".join(blocks)) for section, blocks in sections),
    )


def parse_pptx_document(data: bytes) -> ReferenceDocument | None:
    """Reconstrói o documento a partir do `.pptx` gerado (round-trip)."""

    presentation = Presentation(io.BytesIO(data))
    slides = list(presentation.slides)

    if not slides:
        return None

    metadata: dict[str, str] = {}

    for shape in slides[0].shapes:
        if not shape.has_text_frame:
            continue

        for paragraph in shape.text_frame.paragraphs:
            label, separator, value = paragraph.text.strip().partition(":")

            if separator and label.strip() in _LABEL_TO_FIELD:
                metadata[_LABEL_TO_FIELD[label.strip()]] = value.strip()

    if slides[0].shapes.title is not None:
        metadata.setdefault("title", slides[0].shapes.title.text.strip())

    document_id = metadata.get("document_id", "").strip()

    if not document_id:
        return None

    sections: list[tuple[str, str]] = []

    for slide in slides[1:]:
        title = slide.shapes.title.text.strip() if slide.shapes.title else ""
        body = next(
            (
                shape
                for shape in slide.shapes
                if shape.has_text_frame and shape != slide.shapes.title
            ),
            None,
        )
        blocks = []

        if body is not None:
            blocks = [
                paragraph.text.strip()
                for paragraph in body.text_frame.paragraphs
                if paragraph.text.strip()
            ]

        sections.append((title, "\n\n".join(blocks)))

    return ReferenceDocument(
        document_id=document_id,
        title=metadata.get("title", document_id),
        version=metadata.get("version", "v1"),
        status=metadata.get("status", ""),
        locale=metadata.get("locale", "pt-BR"),
        sections=tuple(sections),
    )


def document_filename(document: ReferenceDocument, fmt: str) -> str:

    return f"{document.document_id}__{document.version}.{fmt}"


def generate_documents(
    knowledge_dir: Path = DEFAULT_KNOWLEDGE_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> list[Path]:
    """Gera os pares docx/pptx dos aprovados; devolve os caminhos escritos.

    O diretório de saída é tratado como artefato gerado: os pares antigos são
    apagados para uma versão removida ou desaprovada não sobreviver no bucket.
    """

    documents = load_knowledge_documents(knowledge_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for stale in (*out_dir.glob("*.docx"), *out_dir.glob("*.pptx")):
        stale.unlink()

    written: list[Path] = []

    for document in documents:
        for fmt, render in RENDERERS.items():
            path = out_dir / document_filename(document, fmt)
            path.write_bytes(render(document))
            written.append(path)

    return written


def minio_client_from_env():
    """Cliente MinIO a partir do ambiente (`.env`); import preguiçoso da lib."""

    try:
        from minio import Minio
    except ImportError:
        raise SystemExit("erro: instale minio (pip install minio).") from None

    endpoint = os.environ.get("MINIO_ENDPOINT", "http://127.0.0.1:9002")
    parsed = urlparse(endpoint)
    access_key = os.environ.get("MINIO_ROOT_USER", "")
    secret_key = os.environ.get("MINIO_ROOT_PASSWORD", "")

    if not parsed.netloc or not access_key or not secret_key:
        raise SystemExit(
            "erro: defina MINIO_ENDPOINT, MINIO_ROOT_USER e MINIO_ROOT_PASSWORD "
            "no ambiente/.env (ver .env.example)."
        )

    return Minio(
        endpoint=parsed.netloc,
        access_key=access_key,
        secret_key=secret_key,
        secure=parsed.scheme == "https",
    )


def resolve_bucket() -> str:

    return os.environ.get("MINIO_BUCKET") or DEFAULT_BUCKET


def _object_parts(path: Path) -> tuple[str, str, str] | None:
    """Desmonta `<document_id>__<version>.<ext>`; `None` se fora do padrão."""

    stem, _, extension = path.name.partition(".")
    document_id, separator, version = stem.partition("__")

    if not separator or not document_id or not version or not extension:
        return None

    return document_id, version, extension


def upload_documents(files: Sequence[Path], *, bucket: str, client) -> int:
    """Sobe os arquivos ao bucket (criando-o, se preciso); devolve o total.

    A chave segue o layout do Value Object Store
    (`documents/<document_id>/<version>/<document_id>.<ext>`), o mesmo do
    `MinioDocumentStoreAdapter`, então a aplicação lê o que a ingestão publica.
    """

    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

    for path in files:
        parts = _object_parts(path)

        if parts is None:
            client.fput_object(bucket, path.name, str(path))
            continue

        document_id, version, extension = parts
        client.fput_object(
            bucket,
            f"documents/{document_id}/{version}/{document_id}.{extension}",
            str(path),
            content_type=_CONTENT_TYPES.get(extension),
            metadata={
                "document_id": document_id,
                "version": version,
                "status": "approved",
            },
        )

    return len(files)


def main() -> int:

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=DEFAULT_KNOWLEDGE_DIR,
        help="diretório do acervo markdown aprovado",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_DIR, help="diretório de saída"
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="envia os arquivos ao MinIO (bucket cantabria-docs/MINIO_BUCKET)",
    )
    args = parser.parse_args()

    from entrypoints.env import load_dotenv

    load_dotenv()

    try:
        written = generate_documents(args.knowledge, args.out)
    except FileNotFoundError as error:
        raise SystemExit(f"erro: {error}") from None

    print(f"OK: {len(written)} documentos gerados em {args.out}")

    if args.upload:
        bucket = resolve_bucket()
        uploaded = upload_documents(
            written, bucket=bucket, client=minio_client_from_env()
        )
        print(f"OK: {uploaded} objetos enviados ao bucket '{bucket}'.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

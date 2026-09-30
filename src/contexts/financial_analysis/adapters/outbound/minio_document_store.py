"""Value Object Store versionado em MinIO.

O arquivo oficial de cada documento aprovado mora aqui; o Qdrant guarda só os
trechos. A chave é determinística — `documents/<document_id>/<version>/...` —
então regravar a mesma versão sobrescreve o mesmo objeto (idempotente) e a
ingestão pode rodar de novo sem duplicar. O client MinIO e o bucket são
injetados pelo composition root; o import deste módulo não abre rede.
"""

from __future__ import annotations

import io
from dataclasses import asdict

from minio import Minio

from contexts.financial_analysis.ports.outbound.document_store_port import (
    DocumentMetadata,
    DocumentStorePort,
)

_LOCATION_SCHEME = "s3://"
_DEFAULT_PREFIX = "documents"
_FALLBACK_EXTENSION = "bin"
_DEFAULT_CONTENT_TYPE = "application/octet-stream"
_EXTENSIONS = {
    "text/markdown": "md",
    "text/plain": "txt",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}


class MinioDocumentStoreAdapter(DocumentStorePort):
    """Grava e lê documentos versionados com chave determinística."""

    def __init__(self, client: Minio, bucket: str, prefix: str = _DEFAULT_PREFIX):

        self._client = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._bucket_ready = False

    def put(
        self,
        document_id: str,
        version: str,
        data: bytes,
        content_type: str,
    ) -> str:

        key = self._key_for(document_id, version, content_type)

        self._ensure_bucket()
        self._client.put_object(
            self._bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type or _DEFAULT_CONTENT_TYPE,
            metadata=asdict(DocumentMetadata(document_id=document_id, version=version)),
        )

        return f"{_LOCATION_SCHEME}{self._bucket}/{key}"

    def get(self, location: str) -> bytes:

        bucket, key = self._split_location(location)
        response = self._client.get_object(bucket, key)

        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def _ensure_bucket(self) -> None:

        if self._bucket_ready:
            return

        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

        self._bucket_ready = True

    def _key_for(self, document_id: str, version: str, content_type: str) -> str:

        document = _safe_segment(document_id, "document_id")
        revision = _safe_segment(version, "version")
        extension = _extension(content_type)

        return f"{self._prefix}/{document}/{revision}/{document}.{extension}"

    def _split_location(self, location: str) -> tuple[str, str]:

        if not location.startswith(_LOCATION_SCHEME):
            raise ValueError(f"location fora do scheme s3: {location!r}")

        remainder = location[len(_LOCATION_SCHEME) :]
        bucket, _, key = remainder.partition("/")

        if bucket != self._bucket or not key:
            raise ValueError(f"location fora do bucket {self._bucket!r}: {location!r}")

        return bucket, key


def _safe_segment(value: str, field: str) -> str:

    segment = value.strip()

    if not segment or "/" in segment or segment in {".", ".."}:
        raise ValueError(f"{field} inválido para chave de documento: {value!r}")

    return segment


def _extension(content_type: str) -> str:

    media_type = content_type.split(";")[0].strip().lower()

    return _EXTENSIONS.get(media_type, _FALLBACK_EXTENSION)

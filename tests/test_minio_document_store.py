"""Value Object Store MinIO: chave determinística, metadados e round-trip.

O client MinIO é substituído por um dublê em memória: nenhum container sobe e
nenhuma rede é tocada. O que se fixa é o contrato do port — location
`s3://<bucket>/<key>`, idempotência por versão, metadados de aprovação e
extensão derivada do content type.
"""

from __future__ import annotations

import pytest

from contexts.financial_analysis.adapters.outbound.minio_document_store import (
    MinioDocumentStoreAdapter,
)

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class _FakeResponse:
    def __init__(self, payload: bytes):

        self._payload = payload
        self.closed = False
        self.released = False

    def read(self) -> bytes:

        return self._payload

    def close(self) -> None:

        self.closed = True

    def release_conn(self) -> None:

        self.released = True


class _FakeMinio:
    def __init__(self):

        self.buckets: set[str] = set()
        self.objects: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}
        self.content_types: dict[tuple[str, str], str] = {}
        self.responses: list[_FakeResponse] = []

    def bucket_exists(self, bucket: str) -> bool:

        return bucket in self.buckets

    def make_bucket(self, bucket: str) -> None:

        self.buckets.add(bucket)

    def put_object(
        self,
        bucket: str,
        key: str,
        data,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> None:

        payload = data.read()
        assert len(payload) == length

        self.objects[(bucket, key)] = payload
        self.metadata[(bucket, key)] = dict(metadata or {})
        self.content_types[(bucket, key)] = content_type

    def get_object(self, bucket: str, key: str) -> _FakeResponse:

        response = _FakeResponse(self.objects[(bucket, key)])
        self.responses.append(response)

        return response


def _adapter(client: _FakeMinio) -> MinioDocumentStoreAdapter:

    return MinioDocumentStoreAdapter(client, "cantabria-docs")


def test_put_grava_com_chave_deterministica_e_metadados() -> None:

    client = _FakeMinio()

    location = _adapter(client).put(
        "doc-rentabilidade", "v1", b"conteudo", "text/markdown"
    )

    key = ("cantabria-docs", "documents/doc-rentabilidade/v1/doc-rentabilidade.md")

    assert location == (
        "s3://cantabria-docs/documents/doc-rentabilidade/v1/doc-rentabilidade.md"
    )
    assert client.objects[key] == b"conteudo"
    assert client.metadata[key] == {
        "document_id": "doc-rentabilidade",
        "version": "v1",
        "status": "approved",
    }
    assert client.content_types[key] == "text/markdown"
    assert client.buckets == {"cantabria-docs"}


def test_put_da_mesma_versao_e_idempotente() -> None:

    client = _FakeMinio()
    adapter = _adapter(client)

    first = adapter.put("doc-x", "v1", b"a", "text/markdown")
    second = adapter.put("doc-x", "v1", b"b", "text/markdown")

    assert first == second
    assert len(client.objects) == 1
    assert client.objects[("cantabria-docs", "documents/doc-x/v1/doc-x.md")] == b"b"


def test_get_faz_round_trip_e_fecha_a_resposta() -> None:

    client = _FakeMinio()
    adapter = _adapter(client)
    location = adapter.put("doc-x", "v2", b"\x89PNG", "application/pdf")

    assert adapter.get(location) == b"\x89PNG"
    assert client.responses[0].closed is True
    assert client.responses[0].released is True


@pytest.mark.parametrize(
    ("document_id", "version"),
    [
        ("", "v1"),
        ("   ", "v1"),
        ("../escape", "v1"),
        ("doc-x", ""),
        ("doc-x", "v1/../v2"),
    ],
)
def test_put_rejeita_segmentos_invalidos(document_id: str, version: str) -> None:

    adapter = _adapter(_FakeMinio())

    with pytest.raises(ValueError):
        adapter.put(document_id, version, b"x", "text/markdown")


def test_get_rejeita_location_fora_do_bucket() -> None:

    adapter = _adapter(_FakeMinio())

    with pytest.raises(ValueError):
        adapter.get("s3://outro-bucket/documents/doc-x/v1/doc-x.md")

    with pytest.raises(ValueError):
        adapter.get("http://cantabria-docs/documents/doc-x/v1/doc-x.md")


def test_extensao_vem_do_content_type() -> None:

    client = _FakeMinio()
    adapter = _adapter(client)

    docx = adapter.put("doc-a", "v1", b"a", _DOCX)
    pptx = adapter.put("doc-b", "v1", b"b", _PPTX)
    unknown = adapter.put("doc-c", "v1", b"c", "application/octet-stream")

    assert docx.endswith("/doc-a.docx")
    assert pptx.endswith("/doc-b.pptx")
    assert unknown.endswith("/doc-c.bin")

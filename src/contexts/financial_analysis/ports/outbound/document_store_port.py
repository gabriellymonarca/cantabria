from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentMetadata:
    """Identidade de um documento aprovado no Value Object Store."""

    document_id: str
    version: str
    status: str = "approved"


# Outbound (driven) port: o Value Object Store (MinIO) guarda o arquivo oficial
# versionado; o Vector Index (Qdrant) guarda os trechos. Ao domínio só chega a
# location `s3://<bucket>/<key>`; client e bucket são do composition root.
class DocumentStorePort(ABC):
    """Armazena e recupera documentos oficiais versionados e aprovados."""

    @abstractmethod
    def put(
        self,
        document_id: str,
        version: str,
        data: bytes,
        content_type: str,
    ) -> str: ...

    @abstractmethod
    def get(self, location: str) -> bytes: ...

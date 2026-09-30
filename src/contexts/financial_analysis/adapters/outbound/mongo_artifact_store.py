"""Artifact Store em MongoDB.

Só os metadados dos artefatos moram aqui: id, tipo, onde o conteúdo está
(Object Store) e a que turno pertencem. O conteúdo fica no Object Store; este
store é a referência para rastreabilidade.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pymongo.database import Database

from contexts.financial_analysis.domain.artifacts import ArtifactRef
from contexts.financial_analysis.ports.outbound.artifact_store_port import (
    ArtifactStorePort,
)
from cross_cutting.mongo import upsert_document


def _utc_now() -> datetime:

    return datetime.now(UTC)


@dataclass
class MongoArtifactStore(ArtifactStorePort):
    """Persiste as referências dos artefatos de um turno."""

    database: Database
    collection_name: str = "artifacts"
    clock: Callable[[], datetime] = field(default=_utc_now)

    def __post_init__(self) -> None:

        self._collection = self.database[self.collection_name]

    def save_artifacts(self, trace_id: str, artifacts: Sequence[ArtifactRef]) -> None:

        for artifact in artifacts:
            upsert_document(
                self._collection,
                {"_id": artifact.artifact_id},
                {
                    "_id": artifact.artifact_id,
                    "type": "artifact",
                    "artifact_id": artifact.artifact_id,
                    "kind": str(artifact.kind),
                    "location": artifact.location,
                    "trace_id": trace_id,
                    "timestamp": self.clock(),
                },
                replace=True,
            )

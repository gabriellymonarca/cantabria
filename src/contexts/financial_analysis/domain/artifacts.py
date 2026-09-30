"""Referência a um artefato gerado a partir de um resultado verificado."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ArtifactKind(StrEnum):
    CHART = "chart"
    TABLE = "table"


@dataclass(frozen=True)
class ArtifactRef:
    """Onde o artefato está e o que ele é; o conteúdo fica no Artifact Store."""

    artifact_id: str
    kind: ArtifactKind
    location: str

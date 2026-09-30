from abc import ABC, abstractmethod
from collections.abc import Sequence

from contexts.financial_analysis.domain.artifacts import ArtifactRef


# Outbound (driven) port: os metadados dos artefatos gerados (gráficos, tabelas)
# ficam no Artifact Store; o conteúdo mora no Object Store (MinIO). O port
# guarda onde cada artefato está e a que turno ele pertence.
class ArtifactStorePort(ABC):
    """Persiste as referências dos artefatos de um turno."""

    @abstractmethod
    def save_artifacts(
        self, trace_id: str, artifacts: Sequence[ArtifactRef]
    ) -> None: ...

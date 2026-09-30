from abc import ABC, abstractmethod


# Outbound (driven) port: the version of the official dataset a result was
# computed against. It is part of the reuse key and of the AnalysisResult
# provenance.
class SnapshotVersionPort(ABC):
    """Identifies the snapshot (data version) currently served."""

    @abstractmethod
    def current(self) -> str: ...

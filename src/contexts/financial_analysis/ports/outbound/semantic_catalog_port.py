from abc import ABC, abstractmethod

from contexts.financial_analysis.domain.semantic_catalog import SemanticCatalog


# Outbound (driven) port: the application depends on this interface to obtain
# the governed semantic catalog. The domain never reads YAML; the adapter
# compiles the versioned file into the typed graph. `load_active` serves the
# hot path; `load(version)` pins a version for audit and replay.
class SemanticCatalogPort(ABC):
    """Loads the active governed catalog, and a pinned version for replay."""

    @abstractmethod
    def load_active(self) -> SemanticCatalog:
        """Compiles and returns the active catalog version."""
        ...

    @abstractmethod
    def load(self, catalog_version: str) -> SemanticCatalog:
        """Compiles and returns a specific catalog version (audit/replay)."""
        ...

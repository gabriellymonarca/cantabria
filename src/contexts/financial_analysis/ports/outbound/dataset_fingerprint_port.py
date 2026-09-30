from abc import ABC, abstractmethod


# Outbound (driven) port: the content fingerprint of the official dataset
# currently served. It is a pure content hash (row counts, money sums,
# reference month per table), collected by an adapter and hashed by the
# shared kernel, so the same content yields the same digest from Python or
# from ClickHouse.
class DatasetFingerprintPort(ABC):
    """Computes the content hash of the official dataset."""

    @abstractmethod
    def digest(self) -> str: ...

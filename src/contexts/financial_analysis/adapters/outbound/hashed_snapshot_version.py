"""Adapter outbound: a versão do snapshot é data de referência + hash.

Decora o `SnapshotVersionPort` baseado em data com a impressão digital de
conteúdo (`DatasetFingerprintPort`): `2026-08-31#sha256:<digest>`. A data
mantém a leitura humana e a chave de reuso legível; o hash garante que
qualquer mudança no conteúdo invalida o reuso e identifica o dado que gerou
o `AnalysisResult`. Se o fingerprint falhar, cai para a versão da base.
"""

from __future__ import annotations

import structlog

from contexts.financial_analysis.ports.outbound.dataset_fingerprint_port import (
    DatasetFingerprintPort,
)
from contexts.financial_analysis.ports.outbound.snapshot_version_port import (
    SnapshotVersionPort,
)
from shared.dataset_version import format_snapshot_version

logger = structlog.get_logger(__name__)


class HashedSnapshotVersionAdapter(SnapshotVersionPort):
    """Compõe data de referência e hash de conteúdo na versão do snapshot."""

    def __init__(
        self,
        base: SnapshotVersionPort,
        fingerprint: DatasetFingerprintPort,
    ):

        self._base = base
        self._fingerprint = fingerprint

    def current(self) -> str:

        version = self._base.current()

        try:
            digest = self._fingerprint.digest()
        except Exception as error:
            logger.warning(
                "Dataset fingerprint unavailable; falling back to the base version",
                error=str(error),
            )

            return version

        return format_snapshot_version(version, digest)

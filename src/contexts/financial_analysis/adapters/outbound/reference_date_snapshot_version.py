"""Adapter outbound: a versão do snapshot é a data de referência do dado.

A última `mes_ref` com dado oficial é o marcador do snapshot: avança sozinha
quando um mês novo entra e mantém a chave de reuso coerente com o dado lido. A
porta vive em
`financial_analysis`; a leitura (e o fallback) da data fica no
`ReferenceDatePort`.
"""

from __future__ import annotations

from contexts.financial_analysis.ports.outbound.reference_date_port import (
    ReferenceDatePort,
)
from contexts.financial_analysis.ports.outbound.snapshot_version_port import (
    SnapshotVersionPort,
)

_UNKNOWN = "unknown"


class ReferenceDateSnapshotVersionAdapter(SnapshotVersionPort):
    """Deriva a versão do snapshot da data de referência do dado."""

    def __init__(self, reference_date: ReferenceDatePort):

        self._reference_date = reference_date

    def current(self) -> str:

        reference = self._reference_date.latest_reference_date()

        return reference.isoformat() if reference is not None else _UNKNOWN

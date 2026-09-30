"""Adapter outbound (ACL): implementa o `CalculationPort` sobre o port inbound
publicado pelo motor (`ExecuteCalculationsPort`).

O núcleo da análise vê só o seu próprio port; o motor publica só o seu port
inbound. A linguagem é a mesma, então a tradução é uma delegação; qualquer
conversão entre as duas mora aqui.
"""

from __future__ import annotations

from collections.abc import Sequence

from contexts.financial_analysis.ports.outbound.calculation_port import (
    CalculationPort,
)
from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    CalculationPlan,
    CalculationResult,
    ExecuteCalculationsPort,
)


class CalculationService(CalculationPort):
    """Delega a execução dos planos ao contexto de cálculo."""

    def __init__(self, engine: ExecuteCalculationsPort):

        self._engine = engine

    def execute(
        self,
        plans: Sequence[CalculationPlan],
        *,
        catalog_version: str,
        snapshot_version: str,
    ) -> Sequence[CalculationResult]:

        return self._engine.execute(
            plans,
            catalog_version=catalog_version,
            snapshot_version=snapshot_version,
        )

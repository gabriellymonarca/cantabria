"""Port: CalculationStore (outbound / driven).

Guarda e recupera CalculationResults por chave de reuso, para auditoria e
reprodutibilidade. O core conhece só este contrato.
"""

from __future__ import annotations

from typing import Protocol

from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
)


class CalculationStore(Protocol):
    def find(self, reuse_key: str) -> CalculationResult | None:
        """Devolve o resultado já calculado para a chave, se existir."""
        ...

    def save(self, reuse_key: str, result: CalculationResult) -> None:
        """Persiste o resultado sob a chave de reuso."""
        ...

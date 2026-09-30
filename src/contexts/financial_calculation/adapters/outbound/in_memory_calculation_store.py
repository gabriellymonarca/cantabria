# Adapter: InMemoryCalculationStore (outbound / driven)
#
# Implementação em memória do Port CalculationStore (fallback sem MongoDB).

from __future__ import annotations

from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
)


class InMemoryCalculationStore:
    def __init__(self) -> None:

        self._by_key: dict[str, CalculationResult] = {}

    def find(self, reuse_key: str) -> CalculationResult | None:

        return self._by_key.get(reuse_key)

    def save(self, reuse_key: str, result: CalculationResult) -> None:

        self._by_key[reuse_key] = result

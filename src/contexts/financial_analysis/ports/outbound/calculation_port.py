from abc import ABC, abstractmethod
from collections.abc import Sequence

from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    CalculationPlan,
    CalculationResult,
)


# Outbound (driven) port: the analysis context hands the validated
# CalculationPlans to this port and receives the verified CalculationResults.
# The adapter (composition) bridges to the
# financial_calculation context; the versions are policy, so they travel with
# the call (catalog version for the plan, snapshot version for the data).
class CalculationPort(ABC):
    """Executes validated CalculationPlans and returns their results."""

    @abstractmethod
    def execute(
        self,
        plans: Sequence[CalculationPlan],
        *,
        catalog_version: str,
        snapshot_version: str,
    ) -> Sequence[CalculationResult]: ...

from abc import ABC, abstractmethod
from collections.abc import Sequence

from contexts.financial_analysis.domain.analysis_plan import AnalysisPlan
from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    CalculationPlan,
)


# Outbound (driven) port: approved plans are persisted for audit and
# reproducibility.
class PlanStorePort(ABC):
    """Guarda o pacote aprovado de um turno."""

    @abstractmethod
    def save_plans(
        self,
        trace_id: str,
        analysis_plan: AnalysisPlan,
        calculation_plans: Sequence[CalculationPlan],
        catalog_version: str,
    ) -> None: ...

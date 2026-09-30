"""Plan Store em memória: determinístico, sem I/O (fallback sem MongoDB)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from contexts.financial_analysis.domain.analysis_plan import AnalysisPlan
from contexts.financial_analysis.ports.outbound.plan_store_port import PlanStorePort
from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    CalculationPlan,
)


@dataclass(frozen=True)
class StoredPlans:
    """O pacote aprovado de um turno, como foi selado."""

    trace_id: str
    analysis_plan: AnalysisPlan
    calculation_plans: tuple[CalculationPlan, ...]
    catalog_version: str


@dataclass
class InMemoryPlanStore(PlanStorePort):
    """Acumula os pacotes aprovados por `trace_id`."""

    plans: dict[str, StoredPlans] = field(default_factory=dict)

    def save_plans(
        self,
        trace_id: str,
        analysis_plan: AnalysisPlan,
        calculation_plans: Sequence[CalculationPlan],
        catalog_version: str,
    ) -> None:

        self.plans[trace_id] = StoredPlans(
            trace_id=trace_id,
            analysis_plan=analysis_plan,
            calculation_plans=tuple(calculation_plans),
            catalog_version=catalog_version,
        )

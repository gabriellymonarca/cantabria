"""Plan Store em MongoDB.

Dois stores lógicos: o Analysis Store guarda o
`AnalysisPlan` e o Calculation Store guarda cada `CalculationPlan`, ambos como
registros `type: plan` com a descrição serializada (`plan_dsc`) e o instante
da gravação. Os documentos são a trilha de auditoria do que foi aprovado.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from pymongo.database import Database

from contexts.financial_analysis.domain.analysis_plan import AnalysisPlan
from contexts.financial_analysis.ports.outbound.plan_store_port import PlanStorePort
from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    CalculationPlan,
)
from cross_cutting.mongo import to_bson_safe, upsert_document


def _utc_now() -> datetime:

    return datetime.now(UTC)


@dataclass
class MongoPlanStore(PlanStorePort):
    """Persiste o pacote aprovado de um turno no Analysis/Calculation Store."""

    database: Database
    analysis_collection: str = "analysis_store"
    calculation_collection: str = "calculation_store"
    clock: Callable[[], datetime] = field(default=_utc_now)

    def __post_init__(self) -> None:

        self._analysis = self.database[self.analysis_collection]
        self._calculation = self.database[self.calculation_collection]

    def save_plans(
        self,
        trace_id: str,
        analysis_plan: AnalysisPlan,
        calculation_plans: Sequence[CalculationPlan],
        catalog_version: str,
    ) -> None:

        timestamp = self.clock()

        upsert_document(
            self._analysis,
            {"_id": f"{trace_id}:plan"},
            {
                "_id": f"{trace_id}:plan",
                "type": "plan",
                "plan_id": analysis_plan.id,
                "calculation_plan_ids": [
                    plan.calculation_plan_id for plan in calculation_plans
                ],
                "plan_dsc": to_bson_safe(asdict(analysis_plan)),
                "trace_id": trace_id,
                "catalog_version": catalog_version,
                "timestamp": timestamp,
            },
            replace=True,
        )

        for plan in calculation_plans:
            upsert_document(
                self._calculation,
                {"_id": plan.calculation_plan_id},
                {
                    "_id": plan.calculation_plan_id,
                    "type": "plan",
                    "plan_id": plan.calculation_plan_id,
                    "plan_dsc": to_bson_safe(asdict(plan)),
                    "trace_id": trace_id,
                    "catalog_version": catalog_version,
                    "timestamp": timestamp,
                },
                replace=True,
            )

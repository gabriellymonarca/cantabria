"""Port inbound publicado do motor de cálculo (Open Host Service).

É a única porta pela qual outro contexto fala com `financial_calculation`. O
módulo reexporta a linguagem publicada — os tipos de plano, os enums fechados,
o resultado e a base dos erros — de que os consumidores dependem.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from contexts.financial_calculation.domain.calculation_plan import (
    AxisLevel,
    AxisType,
    CalculationPlan,
    Grain,
    Metric,
    Period,
    PeriodType,
    RuleId,
    SampleCondition,
    Subject,
)
from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
    CalculationResultRow,
)
from contexts.financial_calculation.domain.errors import (
    CalculationError,
    InvalidPeriodError,
    InvalidPlanError,
    UnknownAxisError,
)

__all__ = [
    "AxisLevel",
    "AxisType",
    "CalculationError",
    "CalculationPlan",
    "CalculationResult",
    "CalculationResultRow",
    "ExecuteCalculationsPort",
    "Grain",
    "InvalidPeriodError",
    "InvalidPlanError",
    "Metric",
    "Period",
    "PeriodType",
    "RuleId",
    "SampleCondition",
    "Subject",
    "UnknownAxisError",
]


class ExecuteCalculationsPort(ABC):
    """Executa planos de cálculo já validados e devolve os resultados."""

    @abstractmethod
    def execute(
        self,
        plans: Sequence[CalculationPlan],
        *,
        catalog_version: str,
        snapshot_version: str,
    ) -> Sequence[CalculationResult]: ...

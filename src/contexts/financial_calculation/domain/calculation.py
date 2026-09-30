"""Agregado `Calculation`: um plano e o resultado que o cumpre.

A identidade é a chave de reuso (o que o cálculo É, não como foi rotulado):
dois pedidos semanticamente iguais sobre o mesmo snapshot são o mesmo
agregado. O agregado registra `CalculationCompleted` quando recebe o seu
resultado, tenha ele sido computado agora ou reaproveitado do store.
"""

from __future__ import annotations

from contexts.financial_calculation.domain.calculation_plan import CalculationPlan
from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
)
from contexts.financial_calculation.domain.errors import CalculationError
from contexts.financial_calculation.domain.events import CalculationCompleted
from shared.domain_events import AggregateRoot


class CalculationStateError(CalculationError):
    """Transição ilegal do agregado (ex.: completar duas vezes)."""


class Calculation(AggregateRoot):
    """Um CalculationPlan em execução, identificado pela chave de reuso."""

    def __init__(self, reuse_key: str, plan: CalculationPlan):

        super().__init__()
        self.reuse_key = reuse_key
        self.plan = plan
        self.result: CalculationResult | None = None

    def complete(self, result: CalculationResult, *, reused: bool) -> None:
        """Recebe o resultado do plano e registra `CalculationCompleted`."""

        if self.result is not None:
            raise CalculationStateError(
                f"o cálculo '{self.reuse_key}' já tem resultado."
            )

        if result.calculation_plan_id != self.plan.calculation_plan_id:
            raise CalculationStateError(
                f"resultado de '{result.calculation_plan_id}' não pertence ao plano "
                f"'{self.plan.calculation_plan_id}'."
            )

        self.result = result

        self.record(
            CalculationCompleted(
                aggregate_id=self.reuse_key,
                calculation_plan_id=self.plan.calculation_plan_id,
                rule_id=str(self.plan.metric.rule_id),
                reused=reused,
                rows=len(result.values),
            )
        )

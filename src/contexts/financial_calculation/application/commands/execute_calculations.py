"""Handler do port inbound `ExecuteCalculationsPort`.

Executa cada plano do pacote no motor (com reuso pelo `CalculationStore`),
publica os `CalculationCompleted` que os agregados registraram e devolve os
resultados na ordem dos planos. Planos independentes rodam em paralelo.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from contexts.financial_calculation.application.commands.run_calculation import (
    calculate,
)
from contexts.financial_calculation.domain.calculation import Calculation
from contexts.financial_calculation.domain.calculation_plan import CalculationPlan
from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
)
from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    ExecuteCalculationsPort,
)
from contexts.financial_calculation.ports.outbound.calculation_store import (
    CalculationStore,
)
from contexts.financial_calculation.ports.outbound.official_data_repository import (
    OfficialDataRepository,
)
from shared.domain_events import EventDispatcher, EventPublisher

_MAX_WORKERS = 4


class ExecuteCalculationsHandler(ExecuteCalculationsPort):
    """Executa cada plano no motor, reaproveitando resultados pela reuse key."""

    def __init__(
        self,
        repository: OfficialDataRepository,
        store: CalculationStore,
        publisher: EventPublisher | None = None,
    ):

        self._repository = repository
        self._store = store
        self._publisher = publisher or EventDispatcher()

    def execute(
        self,
        plans: Sequence[CalculationPlan],
        *,
        catalog_version: str,
        snapshot_version: str,
    ) -> Sequence[CalculationResult]:

        if len(plans) <= 1:
            calculations = [
                self._calculate(plan, catalog_version, snapshot_version)
                for plan in plans
            ]
        else:
            workers = min(_MAX_WORKERS, len(plans))

            with ThreadPoolExecutor(max_workers=workers) as pool:
                calculations = list(
                    pool.map(
                        self._calculate,
                        plans,
                        [catalog_version] * len(plans),
                        [snapshot_version] * len(plans),
                    )
                )

        for calculation in calculations:
            self._publisher.publish(calculation.pull_events())

        return [_result_of(calculation) for calculation in calculations]

    def _calculate(
        self,
        plan: CalculationPlan,
        catalog_version: str,
        snapshot_version: str,
    ) -> Calculation:

        return calculate(
            plan,
            self._repository,
            self._store,
            catalog_version,
            snapshot_version,
        )


def _result_of(calculation: Calculation) -> CalculationResult:

    assert calculation.result is not None

    return calculation.result

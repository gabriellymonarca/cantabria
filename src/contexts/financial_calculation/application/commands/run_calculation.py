"""Orquestra a execução COM reuso: consulta o CalculationStore antes de
recalcular e persiste o resultado sob a chave de reuso.

`execute_calculation` permanece puro (recebe plano e Port, devolve resultado).
A política de cache/reuso é uma decisão de aplicação e vive aqui; o agregado
`Calculation` registra `CalculationCompleted` em qualquer dos dois caminhos.
"""

from __future__ import annotations

from contexts.financial_calculation.application.commands.execute_calculation import (
    execute_calculation,
)
from contexts.financial_calculation.domain.calculation import Calculation
from contexts.financial_calculation.domain.calculation_plan import CalculationPlan
from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
)
from contexts.financial_calculation.domain.reuse_key import compute_reuse_key
from contexts.financial_calculation.ports.outbound.calculation_store import (
    CalculationStore,
)
from contexts.financial_calculation.ports.outbound.official_data_repository import (
    OfficialDataRepository,
)


def calculate(
    plan: CalculationPlan,
    repository: OfficialDataRepository,
    store: CalculationStore,
    catalog_version: str,
    snapshot_version: str,
) -> Calculation:
    """Executa (ou reaproveita) um plano e devolve o agregado completo."""

    reuse_key = compute_reuse_key(plan, catalog_version, snapshot_version)
    calculation = Calculation(reuse_key, plan)

    cached = store.find(reuse_key)

    # As linhas são as mesmas, mas o rótulo é do plano que pediu: o resultado
    # é procurado pelo `calculation_plan_id` do plano atual na análise.
    if cached is not None:
        relabeled = CalculationResult(
            calculation_plan_id=plan.calculation_plan_id,
            rule_id=cached.rule_id,
            unit=cached.unit,
            values=cached.values,
        )
        calculation.complete(relabeled, reused=True)

        return calculation

    result = execute_calculation(plan, repository)
    store.save(reuse_key, result)

    calculation.complete(result, reused=False)

    return calculation


def run_calculation(
    plan: CalculationPlan,
    repository: OfficialDataRepository,
    store: CalculationStore,
    catalog_version: str,
    snapshot_version: str,
) -> CalculationResult:
    """Executa um plano reusando o resultado se a chave já existir."""

    calculation = calculate(plan, repository, store, catalog_version, snapshot_version)

    assert calculation.result is not None

    return calculation.result

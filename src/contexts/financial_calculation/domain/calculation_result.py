from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

Number = Decimal | int


@dataclass(frozen=True)
class CalculationResultRow:
    """Uma medição: (combinação de subjects, período) -> value.

    `subjects` tem chave qualificada por `type.level` (ex.:
    {"customer_segmentation.segment": "Varejo PF"}). Série agregada
    (`total.total`) tem `subjects` vazio.
    `value` é `None` quando a população elegível do grupo é vazia — ausência,
    nunca 0.0.
    `population` é a contagem de clientes distintos que sustenta a medição
    (insumo da supressão small-cell, k = 10); `None` quando a fonte não a
    informa — desconhecida, não zero. Nunca carrega identificadores.
    """

    subjects: dict[str, str | None]
    period: str
    value: Number | None
    population: int | None = None


@dataclass
class CalculationResult:
    """O pacote de linhas produzido por um CalculationPlan.

    Como o plano carrega uma única métrica, o cabeçalho traz a identidade da
    série (`rule_id`, `unit`).
    """

    calculation_plan_id: str
    rule_id: str
    unit: str
    values: list[CalculationResultRow] = field(default_factory=list)

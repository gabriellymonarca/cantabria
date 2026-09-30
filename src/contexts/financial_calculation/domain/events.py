"""Eventos de domínio do motor de cálculo.

Carregam identificadores, versões e contadores — nunca números calculados nem
identificadores de cliente.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.domain_events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class CalculationCompleted(DomainEvent):
    """Um CalculationPlan produziu (ou reaproveitou) o seu CalculationResult."""

    calculation_plan_id: str
    rule_id: str
    reused: bool
    rows: int

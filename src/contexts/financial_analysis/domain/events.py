"""Eventos de domínio do pedido de análise.

Cada transição relevante do `AnalysisRequest` vira um fato registrável. Os
eventos carregam ids, versões e contadores — nunca a pergunta, números do
resultado ou dados pessoais: o conteúdo mora no agregado e nos stores.
"""

from __future__ import annotations

from dataclasses import dataclass

from contexts.financial_analysis.domain.interpretation import (
    InterpretationRoute,
    RefusalReason,
)
from shared.domain_events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class PlanProposed(DomainEvent):
    """O planner propôs uma rota (e, se analítica, os planos)."""

    route: InterpretationRoute
    calculation_plan_ids: tuple[str, ...]
    analysis_plan_id: str | None


@dataclass(frozen=True, kw_only=True)
class PlanValidated(DomainEvent):
    """O pacote passou na validação determinística e foi selado."""

    catalog_version: str
    calculation_plan_ids: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class PlanRejected(DomainEvent):
    """A validação determinística recusou o pacote proposto."""

    reason: RefusalReason
    attempt: int


@dataclass(frozen=True, kw_only=True)
class RequestRefused(DomainEvent):
    """O pedido foi recusado com motivo tipificado."""

    reason: RefusalReason


@dataclass(frozen=True, kw_only=True)
class ClarificationRequested(DomainEvent):
    """O pedido pediu esclarecimento ao usuário antes de seguir."""


@dataclass(frozen=True, kw_only=True)
class AnalysisCompleted(DomainEvent):
    """O pacote foi executado e o resultado verificado existe."""

    analysis_plan_id: str
    dataset_version: str
    catalog_version: str


@dataclass(frozen=True, kw_only=True)
class InsightGenerated(DomainEvent):
    """O redator produziu o texto; `grounded` diz se passou no lastro."""

    grounded: bool
    attempts: int

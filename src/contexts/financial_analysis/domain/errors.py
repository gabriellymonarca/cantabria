"""Erros de domínio da montagem do AnalysisPlan.

A taxonomia cobre os modos de falha da montagem: id repetido, referência
órfã, ciclo e fonte ambígua são erros do proponente (malformed), distintos de
catálogo ou autorização.
"""

from __future__ import annotations

from contexts.financial_analysis.domain.interpretation import RefusalReason


class InvalidAnalysisPlanError(ValueError):
    """Base dos erros de montagem do AnalysisPlan."""


class DuplicateIdError(InvalidAnalysisPlanError):
    """Id repetido dentro do plano — a referência fica ambígua."""


class UnresolvedReferenceError(InvalidAnalysisPlanError):
    """Referência a um id que não foi declarado no mesmo plano."""


class CyclicReferenceError(InvalidAnalysisPlanError):
    """statistic_refs formam um ciclo — a leitura não tem começo."""


class AmbiguousMethodSourceError(InvalidAnalysisPlanError):
    """Método lê as duas fontes, ou nenhuma: exatamente uma é obrigatória."""


class InvalidPresentationError(InvalidAnalysisPlanError):
    """A apresentação proposta não pertence ao catálogo fechado."""


class InvalidCatalogError(ValueError):
    """O catálogo versionado está inconsistente e não pode ser compilado."""


class PlanValidationError(ValueError):
    """O pacote desrespeitou uma regra determinística de validação."""

    def __init__(self, reason: RefusalReason, message: str):

        super().__init__(message)
        self.reason = reason


class AnalysisExecutionError(ValueError):
    """O execute_analysis recebeu um plano que não passou na validação."""

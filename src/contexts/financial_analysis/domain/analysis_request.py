"""Agregado `AnalysisRequest`: um turno de pergunta, do recebimento à resposta.

A identidade é o `trace_id` do turno. O agregado guarda o estado (rota,
planos propostos, pacote selado, resultado, insight) e faz cumprir as
transições legais; cada transição registra o seu evento de domínio. O handler
chama os métodos, salva o agregado e publica os eventos registrados.

    RECEIVED ─propose→ PROPOSED ─approve→ VALIDATED ─complete→ CALCULATED ─explain→ EXPLAINED
                 │          ├─reject→ REJECTED ─propose→ PROPOSED
                 ├──────────┼─ask_clarification→ CLARIFYING (também de REJECTED)
                 └──────────┴─refuse→ REFUSED (também de REJECTED)
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from contexts.financial_analysis.domain.analysis_plan import AnalysisPlan
from contexts.financial_analysis.domain.analysis_result import AnalysisResult
from contexts.financial_analysis.domain.events import (
    AnalysisCompleted,
    ClarificationRequested,
    InsightGenerated,
    PlanProposed,
    PlanRejected,
    PlanValidated,
    RequestRefused,
)
from contexts.financial_analysis.domain.interpretation import (
    InterpretationRoute,
    RefusalReason,
)
from contexts.financial_analysis.domain.services.validate_plan import ValidatedPlan
from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    CalculationPlan,
)
from shared.domain_events import AggregateRoot


class AnalysisStatus(StrEnum):
    RECEIVED = "received"
    PROPOSED = "proposed"
    VALIDATED = "validated"
    REJECTED = "rejected"
    CALCULATED = "calculated"
    EXPLAINED = "explained"
    REFUSED = "refused"
    CLARIFYING = "clarifying"


class AnalysisRequestError(ValueError):
    """Transição ilegal do agregado."""


class AnalysisRequest(AggregateRoot):
    """O pedido de análise de um turno e o que já se sabe sobre ele."""

    def __init__(
        self,
        *,
        trace_id: str,
        session_id: str,
        user_id: str,
        question: str,
    ):

        super().__init__()
        self.trace_id = trace_id
        self.session_id = session_id
        self.user_id = user_id
        self.question = question
        self.status = AnalysisStatus.RECEIVED
        self.route: InterpretationRoute | None = None
        self.analysis_plan: AnalysisPlan | None = None
        self.calculations: tuple[CalculationPlan, ...] = ()
        self.validated: ValidatedPlan | None = None
        self.result: AnalysisResult | None = None
        self.insight: str | None = None
        self.verified_table: str | None = None
        self.rejections = 0
        self.refusal_reason: RefusalReason | None = None
        self.clarification: str | None = None

    def propose(
        self,
        route: InterpretationRoute,
        analysis_plan: AnalysisPlan | None = None,
        calculations: Sequence[CalculationPlan] = (),
    ) -> None:
        """Registra a rota proposta pelo planner (e os planos, se analítica)."""

        self._expect(AnalysisStatus.RECEIVED, AnalysisStatus.REJECTED)

        self.route = route
        self.analysis_plan = analysis_plan
        self.calculations = tuple(calculations)
        self.status = AnalysisStatus.PROPOSED

        self.record(
            PlanProposed(
                aggregate_id=self.trace_id,
                route=route,
                calculation_plan_ids=tuple(
                    plan.calculation_plan_id for plan in self.calculations
                ),
                analysis_plan_id=analysis_plan.id if analysis_plan else None,
            )
        )

    def approve(self, validated: ValidatedPlan) -> None:
        """Sela o pacote aprovado pela validação determinística."""

        self._expect(AnalysisStatus.PROPOSED)

        if self.route is not InterpretationRoute.ANALYTICAL:
            raise AnalysisRequestError("só a rota analytical tem pacote a aprovar.")

        self.validated = validated
        self.status = AnalysisStatus.VALIDATED

        self.record(
            PlanValidated(
                aggregate_id=self.trace_id,
                catalog_version=validated.catalog_version,
                calculation_plan_ids=tuple(
                    plan.calculation_plan_id for plan in validated.calculations
                ),
            )
        )

    def reject(self, reason: RefusalReason, detail: str) -> None:
        """A validação recusou o pacote; o planner pode propor de novo."""

        self._expect(AnalysisStatus.PROPOSED)

        self.rejections += 1
        self.status = AnalysisStatus.REJECTED

        self.record(
            PlanRejected(
                aggregate_id=self.trace_id,
                reason=reason,
                attempt=self.rejections,
            )
        )

    def refuse(self, reason: RefusalReason) -> None:
        """Encerra o pedido com recusa tipificada."""

        self._expect(
            AnalysisStatus.RECEIVED,
            AnalysisStatus.PROPOSED,
            AnalysisStatus.REJECTED,
        )

        self.refusal_reason = reason
        self.status = AnalysisStatus.REFUSED

        self.record(RequestRefused(aggregate_id=self.trace_id, reason=reason))

    def ask_clarification(self, question: str) -> None:
        """Devolve uma pergunta de esclarecimento ao usuário.

        Também vale sem proposta válida (RECEIVED ou REJECTED): é o caso em que
        o planner não conseguiu estruturar a pergunta e pedimos reformulação."""

        self._expect(
            AnalysisStatus.RECEIVED,
            AnalysisStatus.PROPOSED,
            AnalysisStatus.REJECTED,
        )

        self.clarification = question
        self.status = AnalysisStatus.CLARIFYING

        self.record(ClarificationRequested(aggregate_id=self.trace_id))

    def complete(self, result: AnalysisResult) -> None:
        """Recebe o resultado verificado do pacote selado."""

        self._expect(AnalysisStatus.VALIDATED)

        if result.trace_id != self.trace_id:
            raise AnalysisRequestError(
                f"resultado do trace '{result.trace_id}' não pertence ao pedido "
                f"'{self.trace_id}'."
            )

        self.result = result
        self.status = AnalysisStatus.CALCULATED

        self.record(
            AnalysisCompleted(
                aggregate_id=self.trace_id,
                analysis_plan_id=result.analysis_plan_id,
                dataset_version=result.dataset_version,
                catalog_version=result.catalog_version,
            )
        )

    def explain(
        self,
        insight: str,
        verified_table: str,
        *,
        grounded: bool,
        attempts: int,
    ) -> None:
        """Recebe o texto do redator (ou a tabela verificada, se ele falhou)."""

        self._expect(AnalysisStatus.CALCULATED)

        self.insight = insight
        self.verified_table = verified_table
        self.status = AnalysisStatus.EXPLAINED

        self.record(
            InsightGenerated(
                aggregate_id=self.trace_id,
                grounded=grounded,
                attempts=attempts,
            )
        )

    def _expect(self, *allowed: AnalysisStatus) -> None:

        if self.status not in allowed:
            raise AnalysisRequestError(
                f"transição ilegal a partir de '{self.status}' "
                f"(esperado: {', '.join(str(status) for status in allowed)})."
            )

"""Policy: "sempre que AnalysisCompleted / InsightGenerated, então persistir".

Os eventos carregam só identificadores; a policy carrega o agregado pelo
`trace_id` no repositório (o handler o salvou antes de publicar) e persiste o
pacote aprovado, o resultado verificado e o insight nos stores.
"""

from __future__ import annotations

from contexts.financial_analysis.domain.analysis_request import AnalysisRequest
from contexts.financial_analysis.domain.events import (
    AnalysisCompleted,
    InsightGenerated,
)
from contexts.financial_analysis.ports.outbound.analysis_request_repository_port import (
    AnalysisRequestRepository,
)
from contexts.financial_analysis.ports.outbound.plan_store_port import PlanStorePort
from contexts.financial_analysis.ports.outbound.result_store_port import (
    ResultStorePort,
)
from shared.domain_events import DomainEvent, EventDispatcher


class PersistResultsPolicy:
    """Persiste planos, resultado e insight quando o agregado os produz."""

    def __init__(
        self,
        *,
        repository: AnalysisRequestRepository,
        plan_store: PlanStorePort,
        result_store: ResultStorePort,
    ):

        self._repository = repository
        self._plan_store = plan_store
        self._result_store = result_store

    def subscribe(self, dispatcher: EventDispatcher) -> None:

        dispatcher.subscribe(AnalysisCompleted, self.on_analysis_completed)
        dispatcher.subscribe(InsightGenerated, self.on_insight_generated)

    def on_analysis_completed(self, event: DomainEvent) -> None:

        request = self._load(event.aggregate_id)

        if request is None or request.validated is None or request.result is None:
            return

        self._plan_store.save_plans(
            request.trace_id,
            request.validated.analysis_plan,
            request.validated.calculations,
            request.validated.catalog_version,
        )
        self._result_store.save_result(request.trace_id, request.result)

    def on_insight_generated(self, event: DomainEvent) -> None:

        request = self._load(event.aggregate_id)

        if request is None or request.insight is None:
            return

        self._result_store.save_insight(
            request.trace_id, request.insight, request.verified_table or ""
        )

    def _load(self, trace_id: str) -> AnalysisRequest | None:

        return self._repository.get(trace_id)

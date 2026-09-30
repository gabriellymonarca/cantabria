"""Policy: "sempre que InsightGenerated, então gerar artefatos".

Carrega o agregado pelo `trace_id` e pede ao `ArtifactBuilderPort` a tabela e o
gráfico do resultado verificado, na apresentação selada do plano. O conteúdo
vai para a resposta; aqui ficam as referências, persistidas no Artifact Store.
"""

from __future__ import annotations

from contexts.financial_analysis.domain.artifacts import ArtifactRef
from contexts.financial_analysis.domain.events import InsightGenerated
from contexts.financial_analysis.ports.outbound.analysis_request_repository_port import (
    AnalysisRequestRepository,
)
from contexts.financial_analysis.ports.outbound.artifact_builder_port import (
    ArtifactBuilderPort,
)
from contexts.financial_analysis.ports.outbound.artifact_store_port import (
    ArtifactStorePort,
)
from shared.domain_events import DomainEvent, EventDispatcher


class BuildArtifactsPolicy:
    """Gera artefatos a partir do resultado quando o insight é produzido."""

    def __init__(
        self,
        *,
        repository: AnalysisRequestRepository,
        builder: ArtifactBuilderPort,
        artifact_store: ArtifactStorePort | None = None,
    ):

        self._repository = repository
        self._builder = builder
        self._artifact_store = artifact_store
        self.built: dict[str, tuple[ArtifactRef, ...]] = {}

    def subscribe(self, dispatcher: EventDispatcher) -> None:

        dispatcher.subscribe(InsightGenerated, self.on_insight_generated)

    def on_insight_generated(self, event: DomainEvent) -> None:

        request = self._repository.get(event.aggregate_id)

        if request is None or request.result is None or request.insight is None:
            return

        plan = (
            request.validated.analysis_plan
            if request.validated is not None
            else request.analysis_plan
        )
        presentation = plan.presentation if plan is not None else None

        refs = self._builder.build(request.trace_id, request.result, presentation).refs

        self.built[request.trace_id] = tuple(refs)

        if self._artifact_store is not None and refs:
            self._artifact_store.save_artifacts(request.trace_id, refs)

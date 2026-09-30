"""Repositório em memória do agregado `AnalysisRequest`."""

from __future__ import annotations

from dataclasses import dataclass, field

from contexts.financial_analysis.domain.analysis_request import AnalysisRequest
from contexts.financial_analysis.ports.outbound.analysis_request_repository_port import (
    AnalysisRequestRepository,
)


@dataclass
class InMemoryAnalysisRequestRepository(AnalysisRequestRepository):
    """Guarda os pedidos por `trace_id`; serve aos testes e ao dev local."""

    requests: dict[str, AnalysisRequest] = field(default_factory=dict)

    def get(self, trace_id: str) -> AnalysisRequest | None:

        return self.requests.get(trace_id)

    def save(self, request: AnalysisRequest) -> None:

        self.requests[request.trace_id] = request

from abc import ABC, abstractmethod

from contexts.financial_analysis.domain.analysis_request import AnalysisRequest


# Outbound (driven) port: the handler saves the aggregate before publishing its
# events; policies load it by id when they need more than the event carries.
class AnalysisRequestRepository(ABC):
    """Persistência do agregado `AnalysisRequest` por `trace_id`."""

    @abstractmethod
    def get(self, trace_id: str) -> AnalysisRequest | None: ...

    @abstractmethod
    def save(self, request: AnalysisRequest) -> None: ...

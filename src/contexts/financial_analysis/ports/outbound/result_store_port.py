from abc import ABC, abstractmethod

from contexts.financial_analysis.domain.analysis_result import AnalysisResult


# Outbound (driven) port: the verified result and the text that explains it
# are persisted per turn, so every number delivered can be traced back.
class ResultStorePort(ABC):
    """Guarda o resultado verificado e o insight de um turno."""

    @abstractmethod
    def save_result(self, trace_id: str, result: AnalysisResult) -> None: ...

    @abstractmethod
    def save_insight(
        self, trace_id: str, insight: str, verified_table: str
    ) -> None: ...

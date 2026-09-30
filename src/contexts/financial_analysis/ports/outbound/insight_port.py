from abc import ABC, abstractmethod
from collections.abc import Sequence

from contexts.financial_analysis.domain.analysis_result import AnalysisResult
from contexts.financial_analysis.ports.outbound.knowledge_port import KnowledgeExcerpt


# Outbound (driven) port: the explanation is written over verified numbers. It
# may restate them and cite approved documents; it never computes, invents or
# elects causes. `rejected_numbers` lists the numbers a previous attempt cited
# without grounding, so the writer can regenerate once knowing what was refused.
class InsightPort(ABC):
    """Writes the explanation over an AnalysisResult."""

    @abstractmethod
    async def explain(
        self,
        *,
        question: str,
        result: AnalysisResult,
        excerpts: Sequence[KnowledgeExcerpt] = (),
        caveats: Sequence[str] = (),
        session_id: str | None = None,
        rejected_numbers: Sequence[str] = (),
    ) -> str: ...

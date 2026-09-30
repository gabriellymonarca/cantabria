from abc import ABC, abstractmethod
from collections.abc import Sequence

from contexts.financial_analysis.ports.outbound.knowledge_port import (
    KnowledgeExcerpt,
)


# Outbound (driven) port: the approved excerpts are synthesized into an answer
# by the LLM; if it is absent or fails, the pipeline falls back to the raw
# concatenation of the excerpts.
class DocumentalSynthesisPort(ABC):
    """Turns retrieved excerpts into a question-focused answer."""

    @abstractmethod
    async def synthesize(
        self,
        *,
        question: str,
        excerpts: Sequence[KnowledgeExcerpt],
        locale: str,
    ) -> str: ...

from abc import ABC, abstractmethod
from dataclasses import dataclass

from contexts.financial_analysis.domain.analysis_plan import Presentation
from contexts.financial_analysis.domain.analysis_result import AnalysisResult
from contexts.financial_analysis.domain.artifacts import ArtifactRef
from contexts.financial_analysis.ports.inbound.user_request import Dataframe, Plotly


@dataclass(frozen=True)
class ArtifactBundle:
    """O que um turno mostra e o que fica registrado.

    `contents` alimenta a resposta (o Chainlit renderiza `Dataframe`/`Plotly`);
    `refs` são os metadados persistíveis no Artifact Store. O conteúdo é
    construído apenas com números do `AnalysisResult` verificado."""

    contents: tuple[Dataframe | Plotly, ...] = ()
    refs: tuple[ArtifactRef, ...] = ()


# Outbound (driven) port: builds charts/tables from a verified result and the
# presentation chosen in the plan. The renderer is deterministic: no
# aggregation, no rounding, no new numbers. The only LLM-authored text is the
# title, grounded against the result before rendering; an unverified number
# drops the title.
class ArtifactBuilderPort(ABC):
    """Gera os artefatos de um resultado verificado, sem inventar número."""

    @abstractmethod
    def build(
        self,
        trace_id: str,
        result: AnalysisResult,
        presentation: Presentation | None,
    ) -> ArtifactBundle: ...

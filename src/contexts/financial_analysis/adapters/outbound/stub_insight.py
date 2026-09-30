"""Stub de insight: texto determinístico sobre números já verificados.

Devolve uma explicação mínima com os métodos do resultado, os títulos dos
documentos aprovados e as ressalvas recebidas.
"""

from __future__ import annotations

from collections.abc import Sequence

from contexts.financial_analysis.domain.analysis_result import AnalysisResult
from contexts.financial_analysis.ports.outbound.insight_port import InsightPort
from contexts.financial_analysis.ports.outbound.knowledge_port import KnowledgeExcerpt


class StubInsightAdapter(InsightPort):
    """Escreve uma explicação mínima e honesta sobre o resultado."""

    async def explain(
        self,
        *,
        question: str,
        result: AnalysisResult,
        excerpts: Sequence[KnowledgeExcerpt] = (),
        caveats: Sequence[str] = (),
        session_id: str | None = None,
        rejected_numbers: Sequence[str] = (),
    ) -> str:

        methods = (
            ", ".join(entry.method for entry in result.statistical_method)
            or "nenhum método"
        )
        lines = [
            f"Resultado verificado ({methods}) para a pergunta: {question}.",
        ]

        if excerpts:
            titles = "; ".join(excerpt.title for excerpt in excerpts)
            lines.append(f"Documentos aprovados: {titles}.")

        if caveats:
            lines.append("Ressalvas: " + "; ".join(caveats) + ".")

        lines.append(
            "O texto não infere causa: associação e contribuição não são causalidade."
        )

        return "\n".join(lines)

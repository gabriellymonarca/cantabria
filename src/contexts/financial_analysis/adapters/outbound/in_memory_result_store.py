"""Result Store em memória: determinístico, sem I/O (fallback sem MongoDB)."""

from __future__ import annotations

from dataclasses import dataclass, field

from contexts.financial_analysis.domain.analysis_result import AnalysisResult
from contexts.financial_analysis.ports.outbound.result_store_port import (
    ResultStorePort,
)


@dataclass(frozen=True)
class StoredInsight:
    """O texto entregue e a tabela verificada de um turno."""

    insight: str
    verified_table: str


@dataclass
class InMemoryResultStore(ResultStorePort):
    """Acumula resultados e insights por `trace_id`."""

    results: dict[str, AnalysisResult] = field(default_factory=dict)
    insights: dict[str, StoredInsight] = field(default_factory=dict)

    def save_result(self, trace_id: str, result: AnalysisResult) -> None:

        self.results[trace_id] = result

    def save_insight(self, trace_id: str, insight: str, verified_table: str) -> None:

        self.insights[trace_id] = StoredInsight(
            insight=insight, verified_table=verified_table
        )

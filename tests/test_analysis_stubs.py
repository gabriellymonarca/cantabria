"""Portas e stubs de RAG/insight/entrega rodam sem infra externa.

O pipeline fecha ponta a ponta nos testes: o stub de conhecimento não inventa
documento, o de insight não calcula número, e o result store guarda o turno
para auditoria.
"""

from __future__ import annotations

import asyncio

from contexts.financial_analysis.adapters.outbound.in_memory_result_store import (
    InMemoryResultStore,
)
from contexts.financial_analysis.adapters.outbound.stub_insight import (
    StubInsightAdapter,
)
from contexts.financial_analysis.adapters.outbound.stub_knowledge import (
    StubKnowledgeAdapter,
)
from contexts.financial_analysis.domain.analysis_result import (
    AnalysisResult,
    MethodResult,
    MethodValue,
)


def _result() -> AnalysisResult:

    return AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v2",
        dataset_version="d1",
        trace_id="t1",
        statistical_method=[
            MethodResult(
                id="s1",
                method="std",
                values=[
                    MethodValue({"customer_segmentation.segment": "A"}, {"value": 1})
                ],
            )
        ],
    )


def test_stub_de_conhecimento_nao_inventa_documento() -> None:

    assert StubKnowledgeAdapter().retrieve("pergunta", locale="pt-BR") == []


def test_stub_de_insight_e_deterministico_e_nao_afirma_causa() -> None:

    adapter = StubInsightAdapter()
    answer = asyncio.run(adapter.explain(question="Qual o desvio?", result=_result()))
    again = asyncio.run(adapter.explain(question="Qual o desvio?", result=_result()))

    assert answer == again
    assert "std" in answer
    assert "não" in answer and "causa" in answer


def test_result_store_em_memoria_guarda_o_turno() -> None:

    store = InMemoryResultStore()

    store.save_result("t1", _result())
    store.save_insight("t1", "resposta", "| tabela |")

    assert store.results["t1"].analysis_plan_id == "plan"
    assert store.insights["t1"].insight == "resposta"

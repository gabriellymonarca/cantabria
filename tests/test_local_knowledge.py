"""Acervo local e retrieval deterministico: relevancia, limite, locale e abstencao.

O adapter le `data/knowledge/*.md` (somentes aprovados) e responde com BM25
offline, sem rede. A rota documental responde a partir dos trechos; a rota
analitica injeta os trechos no insight. Perguntas fora do escopo nao vazam
documento: voltam vazias e a rota documental se absteem.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from contexts.financial_analysis.adapters.outbound.local_knowledge import (
    LocalKnowledgeAdapter,
)
from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.application.commands.execute_pipeline import (
    AnalysisPipeline,
)
from contexts.financial_analysis.ports.outbound.calculation_port import (
    CalculationPort,
)
from contexts.financial_analysis.ports.outbound.insight_port import InsightPort
from contexts.financial_analysis.ports.outbound.snapshot_version_port import (
    SnapshotVersionPort,
)

_CASES = [
    ("Como o banco calcula rentabilidade?", "doc-rentabilidade"),
    ("O que é Principalidade? Como é apurada?", "doc-principalidade"),
    (
        "Qual a diferença entre Vinculação e Principalidade?",
        "doc-vinculacao-principalidade",
    ),
    (
        "Quais produtos são permitidos para o segmento Private?",
        "doc-matriz-segmento-produto",
    ),
    ("Qual a metodologia de segmentação de clientes?", "doc-segmentacao"),
]


def test_perguntas_f49_a_f53_recuperam_o_documento_correto() -> None:

    adapter = LocalKnowledgeAdapter()

    for question, document_id in _CASES:
        excerpts = adapter.retrieve(question, locale="pt-BR")

        assert excerpts, f"sem trechos para {question!r}"
        assert excerpts[0].document_id == document_id
        assert all(excerpt.version == "v1" for excerpt in excerpts)


def test_trechos_carregam_proveniencia() -> None:

    excerpts = LocalKnowledgeAdapter().retrieve(
        "Como o banco calcula rentabilidade?", locale="pt-BR", limit=1
    )

    assert excerpts[0].title
    assert excerpts[0].section
    assert excerpts[0].text


def test_limit_e_respeitado() -> None:

    adapter = LocalKnowledgeAdapter()

    assert (
        len(
            adapter.retrieve(
                "Como o banco calcula rentabilidade?", locale="pt-BR", limit=1
            )
        )
        == 1
    )
    assert (
        len(
            adapter.retrieve(
                "Como o banco calcula rentabilidade?", locale="pt-BR", limit=2
            )
        )
        == 2
    )


def test_locale_fora_do_pt_br_nao_recupera() -> None:

    adapter = LocalKnowledgeAdapter()

    assert adapter.retrieve("Como o banco calcula rentabilidade?", locale="en-US") == []
    assert adapter.retrieve("Como o banco calcula rentabilidade?", locale="pt-BR")


def test_corpus_vazio_responde_vazio(tmp_path: Path) -> None:

    adapter = LocalKnowledgeAdapter(knowledge_dir=tmp_path)

    assert adapter.retrieve("Como o banco calcula rentabilidade?", locale="pt-BR") == []


def test_pergunta_fora_do_escopo_nao_vaza_documento() -> None:

    adapter = LocalKnowledgeAdapter()

    # Os probes não compartilham termo de conteúdo com o acervo: a recusa é
    # por ausência de lastro documental, não por limiar apertado. Limitar o
    # vocabulário dos docs para derrubar um probe lexical seria a solução
    # errada (a pergunta legítima é que precisa recuperar).
    assert adapter.retrieve("Qual é a capital da França?", locale="pt-BR") == []
    assert (
        adapter.retrieve("Qual o CPF do titular João da Silva?", locale="pt-BR") == []
    )


def test_apenas_documento_aprovado_e_indexado(tmp_path: Path) -> None:

    body = (
        "Rentabilidade xyzw de mentirinha. A rentabilidade xyzw segue a regra "
        "xyzw de rentabilidade."
    )
    (tmp_path / "aprovado.md").write_text(
        "---\n"
        "document_id: doc-aprovado\n"
        "title: Rentabilidade xyzw aprovada\n"
        "version: v1\n"
        "status: approved\n"
        "locale: pt-BR\n"
        "---\n\n"
        f"## Rentabilidade xyzw\n\n{body}",
        encoding="utf-8",
    )
    (tmp_path / "outro.md").write_text(
        "---\n"
        "document_id: doc-outro\n"
        "title: Janela qwrt aprovada\n"
        "version: v1\n"
        "status: approved\n"
        "locale: pt-BR\n"
        "---\n\n"
        "## Janela qwrt\n\n"
        "Janela qwrt de mentirinha. A janela qwrt segue a regra qwrt de janela.",
        encoding="utf-8",
    )
    (tmp_path / "rascunho.md").write_text(
        "---\n"
        "document_id: doc-rascunho\n"
        "title: Rentabilidade xyzw rascunho\n"
        "version: v1\n"
        "status: draft\n"
        "locale: pt-BR\n"
        "---\n\n"
        f"## Rentabilidade xyzw\n\n{body}",
        encoding="utf-8",
    )

    excerpts = LocalKnowledgeAdapter(knowledge_dir=tmp_path).retrieve(
        "palavra rara xyzw rentabilidade?", locale="pt-BR"
    )

    assert [excerpt.document_id for excerpt in excerpts] == ["doc-aprovado"]


def test_retrieval_e_deterministico() -> None:

    adapter = LocalKnowledgeAdapter()
    question = "Qual a diferença entre Vinculação e Principalidade?"

    first = adapter.retrieve(question, locale="pt-BR")
    second = adapter.retrieve(question, locale="pt-BR")

    assert [(excerpt.document_id, excerpt.section) for excerpt in first] == [
        (excerpt.document_id, excerpt.section) for excerpt in second
    ]


def test_rota_documental_responde_a_partir_dos_trechos() -> None:

    pipeline = _pipeline()

    answer = asyncio.run(
        pipeline.documental(
            question="O que é Principalidade? Como é apurada?", locale="pt-BR"
        )
    )

    assert "principalidade_score" in answer
    assert "Principalidade" in answer


def test_rota_documental_abstem_se_sem_trecho() -> None:

    pipeline = _pipeline()

    answer = asyncio.run(
        pipeline.documental(question="Qual é a capital da França?", locale="pt-BR")
    )

    assert answer.startswith("Não encontrei documentação aprovada")


def test_rota_analitica_injeta_trechos_no_insight() -> None:

    insight = _Insight()
    pipeline = AnalysisPipeline(
        calculation=_Calculation(),
        snapshot_version=_Snapshot(),
        knowledge=LocalKnowledgeAdapter(),
        insight=insight,
    )

    asyncio.run(
        pipeline.run(
            question="Qual a rentabilidade por segmento?",
            locale="pt-BR",
            session_id="s1",
            analysis_plan=_analysis_plan(),
            calculations=[_calculation_plan()],
            catalog=YamlSemanticCatalogAdapter().load_active(),
        )
    )

    assert insight.excerpts, "o insight analitico deve receber trechos"
    assert all(excerpt.version == "v1" for excerpt in insight.excerpts)


class _Calculation(CalculationPort):
    def execute(
        self,
        plans,
        *,
        catalog_version: str,
        snapshot_version: str,
    ):

        from decimal import Decimal

        from contexts.financial_calculation.domain.calculation_result import (
            CalculationResult,
            CalculationResultRow,
        )

        return [
            CalculationResult(
                calculation_plan_id="calc_prof_seg",
                rule_id="profitability",
                unit="decimal_rate",
                values=[
                    CalculationResultRow(
                        subjects={"customer_segmentation.segment": "Varejo PF"},
                        period="2026-08-31",
                        value=Decimal("0.12"),
                    ),
                ],
            )
        ]


class _Snapshot(SnapshotVersionPort):
    def current(self) -> str:

        return "2026-08-31"


class _Insight(InsightPort):
    def __init__(self):

        self.excerpts: list = []

    async def explain(
        self, *, question, result, excerpts=(), caveats=(), session_id=None
    ) -> str:

        self.excerpts = list(excerpts)

        return "Explicação do LLM."


def _pipeline() -> AnalysisPipeline:

    return AnalysisPipeline(
        calculation=_Calculation(),
        snapshot_version=_Snapshot(),
        knowledge=LocalKnowledgeAdapter(),
        insight=_Insight(),
    )


def _analysis_plan():

    from contexts.financial_analysis.domain.analysis_plan import (
        AnalysisPlan,
        StatisticalMethod,
        StatisticalMethodType,
    )

    return AnalysisPlan(
        id="plan",
        statistical_method=[
            StatisticalMethod(
                id="s1",
                method=StatisticalMethodType.NULL,
                calculation_plan_ids=["calc_prof_seg"],
            )
        ],
    )


def _calculation_plan():

    from contexts.financial_analysis.application.commands.answer_question import (
        InterpretationProposal,
    )

    payload: dict[str, Any] = {
        "calculation_plan_id": "calc_prof_seg",
        "metric": {
            "rule_id": "profitability",
            "subjects": [{"type": "customer_segmentation", "level": "segment"}],
        },
        "period": {
            "start": "2025-09-01",
            "end": "2026-08-31",
            "type": "series",
            "grain": "total",
        },
    }

    proposal = InterpretationProposal.model_validate(
        {
            "route": "analytical",
            "analysis": {
                "id": "plan",
                "statistical_method": [
                    {
                        "id": "s1",
                        "method": "null",
                        "calculation_plan_ids": ["calc_prof_seg"],
                    }
                ],
                "operations": [],
            },
            "calculations": [payload],
        }
    )

    return proposal.calculations[0]

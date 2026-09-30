"""Síntese da rota documental: a resposta é composta a partir dos trechos.

O pipeline aceita um port de síntese opcional: com ele, a resposta é o texto
sintetizado (que cita os documentos pelo título); sem ele, ou quando o LLM
falha, a resposta é a concatenação dos trechos. Sem trechos, a rota se abstém.
O gate de lastro analítico não se aplica (não há números de resultado);
`sanitize_user_text` continua no call site existente.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from contexts.financial_analysis.adapters.outbound.langchain_documental import (
    _PROMPTS_SUBDIR,
    DocumentalPromptError,
    LangChainDocumentalSynthesisAdapter,
)
from contexts.financial_analysis.adapters.outbound.local_knowledge import (
    LocalKnowledgeAdapter,
)
from contexts.financial_analysis.adapters.outbound.stub_knowledge import (
    StubKnowledgeAdapter,
)
from contexts.financial_analysis.application.commands.execute_pipeline import (
    _NO_DOCUMENTS,
    AnalysisPipeline,
)
from contexts.financial_analysis.ports.outbound.calculation_port import (
    CalculationPort,
)
from contexts.financial_analysis.ports.outbound.documental_synthesis_port import (
    DocumentalSynthesisPort,
)
from contexts.financial_analysis.ports.outbound.insight_port import InsightPort
from contexts.financial_analysis.ports.outbound.knowledge_port import (
    KnowledgeExcerpt,
    KnowledgePort,
)
from contexts.financial_analysis.ports.outbound.llm_port import (
    LlmMessage,
    LlmPort,
    LlmReply,
)
from contexts.financial_analysis.ports.outbound.snapshot_version_port import (
    SnapshotVersionPort,
)
from cross_cutting.config import DataConfig

_QUESTION = "O que é Principalidade? Como é apurada?"
_LOCALE = "pt-BR"
_PROMPTS = Path(__file__).resolve().parents[1] / "data" / "prompts" / "documental"


class _Calculation(CalculationPort):
    def execute(self, plans, *, catalog_version, snapshot_version):

        raise AssertionError("a rota documental não calcula")


class _Snapshot(SnapshotVersionPort):
    def current(self) -> str:

        return "2026-08-31"


class _Insight(InsightPort):
    async def explain(
        self,
        *,
        question,
        result,
        excerpts=(),
        caveats=(),
        session_id=None,
        rejected_numbers=(),
    ) -> str:

        raise AssertionError("a rota documental não chama o redator")


class _TitleCitingSynthesis(DocumentalSynthesisPort):
    """Sintetizador de teste: devolve os títulos recebidos, sem documento bruto."""

    def __init__(self) -> None:

        self.calls: list[dict] = []

    async def synthesize(
        self,
        *,
        question: str,
        excerpts: Sequence[KnowledgeExcerpt],
        locale: str,
    ) -> str:

        titles = [excerpt.title for excerpt in excerpts]
        self.calls.append({"question": question, "locale": locale, "titles": titles})

        return "Fontes: " + "; ".join(titles)


class _FailingLlm(LlmPort):
    def __init__(self) -> None:

        self.steps: list[str] = []

    async def generate(
        self,
        messages: Sequence[LlmMessage],
        session_id: str | None = None,
        step: str = "llm",
    ) -> LlmReply:

        self.steps.append(step)

        raise RuntimeError("provedor fora do ar")

    async def generate_structured(
        self,
        messages: Sequence[LlmMessage],
        schema,
        session_id: str | None = None,
        step: str = "llm",
    ):

        raise NotImplementedError


class _CapturingLlm(LlmPort):
    def __init__(self) -> None:

        self.messages: list[LlmMessage] = []
        self.steps: list[str] = []

    async def generate(
        self,
        messages: Sequence[LlmMessage],
        session_id: str | None = None,
        step: str = "llm",
    ) -> LlmReply:

        self.messages = list(messages)
        self.steps.append(step)

        return LlmReply(text="resposta sintetizada", model="fake", usage=None)

    async def generate_structured(
        self,
        messages: Sequence[LlmMessage],
        schema,
        session_id: str | None = None,
        step: str = "llm",
    ):

        raise NotImplementedError


def _pipeline(
    knowledge: KnowledgePort | None = None,
    synthesis: DocumentalSynthesisPort | None = None,
) -> AnalysisPipeline:

    return AnalysisPipeline(
        calculation=_Calculation(),
        snapshot_version=_Snapshot(),
        knowledge=knowledge or LocalKnowledgeAdapter(),
        insight=_Insight(),
        documental_synthesis=synthesis,
    )


def test_sintese_substitui_o_despejo_e_cita_titulos() -> None:

    synthesis = _TitleCitingSynthesis()
    pipeline = _pipeline(synthesis=synthesis)

    answer = asyncio.run(pipeline.documental(question=_QUESTION, locale=_LOCALE))

    excerpt_titles = [
        excerpt.title
        for excerpt in LocalKnowledgeAdapter().retrieve(_QUESTION, locale=_LOCALE)
    ]

    assert answer == "Fontes: " + "; ".join(excerpt_titles)
    assert "Principalidade" in answer
    assert synthesis.calls[0]["question"] == _QUESTION
    assert synthesis.calls[0]["locale"] == _LOCALE


def test_sem_sintese_mantem_a_concatenacao_crua() -> None:

    pipeline = _pipeline()
    excerpts = LocalKnowledgeAdapter().retrieve(_QUESTION, locale=_LOCALE)

    answer = asyncio.run(pipeline.documental(question=_QUESTION, locale=_LOCALE))

    assert answer.startswith(f"{excerpts[0].title} — {excerpts[0].section}")
    assert excerpts[0].text in answer


def test_llm_que_falha_cai_na_concatenacao_sem_ficar_mudo() -> None:

    llm = _FailingLlm()
    pipeline = _pipeline(synthesis=LangChainDocumentalSynthesisAdapter(llm))

    answer = asyncio.run(pipeline.documental(question=_QUESTION, locale=_LOCALE))

    assert answer
    assert "principalidade_score" in answer
    assert " — " in answer
    assert llm.steps == ["documental"]


def test_sem_trechos_nao_chama_a_sintese_e_se_abstem() -> None:

    synthesis = _TitleCitingSynthesis()
    pipeline = _pipeline(knowledge=StubKnowledgeAdapter(), synthesis=synthesis)

    answer = asyncio.run(
        pipeline.documental(question="Qual é a capital da França?", locale=_LOCALE)
    )

    assert answer == _NO_DOCUMENTS
    assert synthesis.calls == []


def test_adapter_carrega_o_contrato_e_envia_titulos_sem_ids() -> None:

    llm = _CapturingLlm()
    adapter = LangChainDocumentalSynthesisAdapter(llm)
    excerpts = LocalKnowledgeAdapter().retrieve(_QUESTION, locale=_LOCALE)

    text = asyncio.run(
        adapter.synthesize(question=_QUESTION, excerpts=excerpts, locale=_LOCALE)
    )

    system, payload = llm.messages

    assert text == "resposta sintetizada"
    assert llm.steps == ["documental"]
    assert "somente" in system.content
    assert "título" in system.content
    assert payload.content.startswith(f"PERGUNTA\n{_QUESTION}")

    for excerpt in excerpts:
        assert excerpt.title in payload.content
        assert excerpt.document_id not in payload.content


def test_adapter_aceita_diretorio_de_prompt_explicito(tmp_path: Path) -> None:

    (tmp_path / "base.md").write_text("CONTRATO", encoding="utf-8")
    llm = _CapturingLlm()
    adapter = LangChainDocumentalSynthesisAdapter(llm, prompts_dir=tmp_path)

    asyncio.run(adapter.synthesize(question="q?", excerpts=(), locale=_LOCALE))

    assert llm.messages[0].content == "CONTRATO"


def test_adapter_sem_contrato_falha_alto() -> None:

    adapter = LangChainDocumentalSynthesisAdapter(
        _CapturingLlm(), prompts_dir=Path("/nao/existe")
    )

    try:
        asyncio.run(adapter.synthesize(question="q?", excerpts=(), locale=_LOCALE))
    except DocumentalPromptError:
        return

    raise AssertionError("deveria falhar sem o contrato de prompt")


def test_contrato_v1_exige_trechos_titulos_e_abstencao() -> None:

    text = (_PROMPTS / "v1" / "base.md").read_text(encoding="utf-8")

    assert "version: v1" in text.splitlines()[0]
    assert "somente" in text
    assert "título" in text
    assert "document_id" in text
    assert "não cobrirem a pergunta" in text
    assert "Não copie os trechos integralmente" in text


def test_documental_aponta_para_v1_por_padrao() -> None:

    resolved = DataConfig().resolved_documental_prompts_dir()

    assert _PROMPTS_SUBDIR.name == "v1"
    assert (resolved.parent.name, resolved.name) == ("documental", "v1")
    assert (resolved / "base.md").is_file()
    assert DataConfig().resolved_prompts_dirs()["documental"] == resolved

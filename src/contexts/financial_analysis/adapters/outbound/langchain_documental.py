"""Adapter outbound: a resposta documental sintetizada a partir dos trechos.

O prompt versionado (`data/prompts/documental/v1/base.md`, ou o diretório que a
composição injetar via `prompts_dir`) manda responder **somente** com os trechos
aprovados e citar os documentos pelo título. O adapter compõe outro port
outbound (`LlmPort`). O texto volta cru: o pipeline sanitiza e, se a síntese
falhar, recua para a concatenação dos trechos.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from contexts.financial_analysis.ports.outbound.documental_synthesis_port import (
    DocumentalSynthesisPort,
)
from contexts.financial_analysis.ports.outbound.knowledge_port import KnowledgeExcerpt
from contexts.financial_analysis.ports.outbound.llm_port import (
    LlmMessage,
    LlmPort,
)
from cross_cutting.resources import resolve_data_dir

_PROMPTS_SUBDIR = Path("prompts") / "documental" / "v1"
_DOCUMENTAL_STEP = "documental"


class DocumentalPromptError(RuntimeError):
    """O contrato de prompt da síntese documental está ausente."""


class LangChainDocumentalSynthesisAdapter(DocumentalSynthesisPort):
    """Sintetiza a resposta documental através do port de linguagem."""

    def __init__(self, llm: LlmPort, prompts_dir: Path | None = None):

        data_dir = resolve_data_dir()
        self._prompts_dir = prompts_dir or (data_dir / _PROMPTS_SUBDIR)
        self._llm = llm
        self._system: str | None = None

    async def synthesize(
        self,
        *,
        question: str,
        excerpts: Sequence[KnowledgeExcerpt],
        locale: str,
    ) -> str:

        messages = [
            LlmMessage(role="system", content=self._system_prompt()),
            LlmMessage(
                role="user",
                content=_render_payload(question, excerpts, locale),
            ),
        ]

        reply = await self._llm.generate(messages, step=_DOCUMENTAL_STEP)

        return reply.text

    def _system_prompt(self) -> str:

        if self._system is None:
            path = self._prompts_dir / "base.md"

            if not path.is_file():
                raise DocumentalPromptError(
                    f"prompt da síntese documental não encontrado: {path}"
                )

            self._system = path.read_text(encoding="utf-8")

        return self._system


def _render_payload(
    question: str,
    excerpts: Sequence[KnowledgeExcerpt],
    locale: str,
) -> str:

    sections = [
        f"PERGUNTA\n{question}",
        "TRECHOS\n" + _render_excerpts(excerpts),
        f"IDIOMA\n{locale}",
    ]

    return "\n\n".join(sections)


def _render_excerpts(excerpts: Sequence[KnowledgeExcerpt]) -> str:
    """Renderiza título/seção/texto: `document_id` nunca entra no prompt."""

    if not excerpts:
        return "(nenhum trecho)"

    return "\n\n".join(
        f"[{excerpt.title} — {excerpt.section}]\n{excerpt.text}" for excerpt in excerpts
    )

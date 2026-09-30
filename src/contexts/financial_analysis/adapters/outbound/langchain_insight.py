"""Adapter outbound: o insight final escrito pelo LLM sobre números verificados.

O prompt versionado (`data/prompts/insight/v3/base.md`, ou o diretório que a
composição injetar via `prompts_dir`) é o contrato; a renderização do
`AnalysisResult` para texto é determinística e contém **apenas** os números que
a execução produziu. O LLM recebe o resultado já calculado e, no máximo,
trechos aprovados.

O adapter compõe outro port outbound (`LlmPort`). O texto volta cru:
sanitização, formatação pt-BR e o portão de lastro dos números são do pipeline,
que decide se entrega, regenera ou recua.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from contexts.financial_analysis.domain.analysis_result import (
    AnalysisResult,
    MethodResult,
    OperationResult,
)
from contexts.financial_analysis.ports.outbound.insight_port import InsightPort
from contexts.financial_analysis.ports.outbound.knowledge_port import KnowledgeExcerpt
from contexts.financial_analysis.ports.outbound.llm_port import (
    LlmMessage,
    LlmPort,
)
from cross_cutting.resources import resolve_data_dir

_PROMPTS_SUBDIR = Path("prompts") / "insight" / "v3"
_MAX_INSIGHT_CACHE = 128
_INSIGHT_STEP = "insight"


class InsightPromptError(RuntimeError):
    """O contrato de prompt do insight está ausente."""


class LangChainInsightAdapter(InsightPort):
    """Explica o resultado verificado através do port de linguagem."""

    def __init__(self, llm: LlmPort, prompts_dir: Path | None = None):

        data_dir = resolve_data_dir()
        self._prompts_dir = prompts_dir or (data_dir / _PROMPTS_SUBDIR)
        self._llm = llm
        self._system: str | None = None
        self._cache: dict[str, str] = {}

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

        messages = [
            LlmMessage(role="system", content=self._system_prompt()),
            LlmMessage(
                role="user",
                content=_render_payload(
                    question, result, excerpts, caveats, rejected_numbers
                ),
            ),
        ]

        key = hashlib.sha256(messages[1].content.encode("utf-8")).hexdigest()
        cached = self._cache.get(key)

        if cached is not None:
            return cached

        reply = await self._llm.generate(
            messages, session_id=session_id, step=_INSIGHT_STEP
        )
        text = reply.text

        if len(self._cache) >= _MAX_INSIGHT_CACHE:
            self._cache.pop(next(iter(self._cache)))

        self._cache[key] = text

        return text

    def _system_prompt(self) -> str:

        if self._system is None:
            path = self._prompts_dir / "base.md"

            if not path.is_file():
                raise InsightPromptError(f"prompt do insight não encontrado: {path}")

            self._system = path.read_text(encoding="utf-8")

        return self._system


def _render_payload(
    question: str,
    result: AnalysisResult,
    excerpts: Sequence[KnowledgeExcerpt],
    caveats: Sequence[str],
    rejected_numbers: Sequence[str] = (),
) -> str:

    sections = [
        f"PERGUNTA\n{question}",
        "RESULTADO VERIFICADO\n" + _render_result(result),
        "DOCUMENTOS\n" + _render_excerpts(excerpts),
        "RESSALVAS\n" + _render_caveats(caveats),
    ]

    if rejected_numbers:
        sections.append(_render_rejected(rejected_numbers))

    return "\n\n".join(sections)


def _render_rejected(rejected_numbers: Sequence[str]) -> str:
    """Nota de regeneração: a tentativa anterior citou números sem lastro.

    A nota entra no payload do usuário (não no prompt versionado) porque é
    circunstancial; também muda a chave do cache, para que a repetição não
    devolva o texto rejeitado."""

    listed = "; ".join(rejected_numbers)

    return (
        "NÚMEROS REJEITADOS\n"
        "A versão anterior desta explicação citou números que NÃO constam do "
        f"RESULTADO VERIFICADO e foi recusada: {listed}.\n"
        "Reescreva a explicação do zero e use apenas números do RESULTADO "
        "VERIFICADO, admitido só o arredondamento de exibição. Não some, não "
        "faça média, não calcule diferença nem percentual novo."
    )


def _render_result(result: AnalysisResult) -> str:

    lines = [
        f"analysis_plan_id: {result.analysis_plan_id}",
        f"catalog_version: {result.catalog_version}",
        f"dataset_version: {result.dataset_version}",
        f"trace_id: {result.trace_id}",
        "",
        "statistical_method:",
    ]

    for method in result.statistical_method:
        lines.extend(_render_method(method))

    if result.operations:
        lines.append("")
        lines.append("operations:")
        for operation in result.operations:
            lines.extend(_render_operation(operation))

    return "\n".join(lines)


def _render_method(method: MethodResult) -> list[str]:

    lines = [f"  - {method.id} ({method.method}){_provenance(method)}:"]

    for row in method.values:
        identity = _render_subjects(row.subjects)
        period = f" @ {row.period}" if row.period else ""
        outcome = (
            _render_values(row.values)
            if row.undefined is None
            else (f"[indefinido: {row.undefined}]")
        )

        lines.append(f"      {identity}{period}: {outcome}")

    return lines


def _render_operation(operation: OperationResult) -> list[str]:

    lines = [
        f"  - {operation.id} ({operation.type})"
        f" refs={list(operation.refs)}{_provenance(operation)}:"
    ]

    for row in operation.values:
        identity = _render_subjects(row.subjects)
        rank = f" rank={row.rank}" if row.rank is not None else ""
        outcome = (
            _render_values(row.values)
            if row.undefined is None
            else (f"[indefinido: {row.undefined}]")
        )

        lines.append(f"      {identity}{rank}: {outcome}")

    return lines


def _render_subjects(subjects: dict[str, str | None]) -> str:

    if not subjects:
        return "(total)"

    return ", ".join(f"{key}={value}" for key, value in sorted(subjects.items()))


def _render_values(values: dict[str, object]) -> str:

    return ", ".join(f"{key}={value}" for key, value in sorted(values.items()))


def _render_excerpts(excerpts: Sequence[KnowledgeExcerpt]) -> str:

    if not excerpts:
        return "(nenhum documento aprovado)"

    return "\n\n".join(
        f"[{excerpt.document_id} — {excerpt.title}, {excerpt.section}]\n{excerpt.text}"
        for excerpt in excerpts
    )


def _render_caveats(caveats: Sequence[str]) -> str:

    if not caveats:
        return "(nenhuma)"

    return "\n".join(f"- {caveat}" for caveat in caveats)


def _provenance(result: MethodResult | OperationResult) -> str:

    if result.rule_id is None and result.unit is None:
        return ""

    if result.rule_id is None:
        return f" [unidade {result.unit}]"

    if result.unit is None:
        return f" [métrica {result.rule_id}]"

    return f" [métrica {result.rule_id}, unidade {result.unit}]"

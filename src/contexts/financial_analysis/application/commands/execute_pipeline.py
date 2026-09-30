"""Pipeline analítico: cálculo → análise → conhecimento → insight.

O `AnswerQuestionHandler` interpreta e valida; este colaborador executa o
pacote aprovado: pede os números ao `CalculationPort`, organiza via
`execute_analysis`, recupera documentos aprovados e pede o texto ao
`InsightPort`. A `AnalysisResult` carrega a procedência (snapshot, catálogo,
trace). A persistência do turno é reação aos eventos do agregado
`AnalysisRequest` (`policies/persist_results.py`).

Dois portões determinísticos moram aqui:
- small-cell: a população (clientes distintos) de cada célula × período vem
  do cálculo e alimenta a supressão k = 10 com complementar;
- lastro: todo número do insight tem de existir no resultado. Falhou → uma
  regeneração apontando os números recusados; falhou de novo → o usuário
  recebe a tabela verificada, nunca o texto rejeitado.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

import structlog

from contexts.financial_analysis.domain.analysis_plan import AnalysisPlan, Presentation
from contexts.financial_analysis.domain.analysis_result import (
    AnalysisResult,
    UndefinedReason,
)
from contexts.financial_analysis.domain.insight_presentation import (
    InsightNumberError,
    present_insight,
    render_verified_table,
    validate_insight_numbers,
)
from contexts.financial_analysis.domain.semantic_catalog import SemanticCatalog
from contexts.financial_analysis.domain.services.execute_analysis import (
    execute_analysis,
    populations_from_results,
    rows_without_population,
)
from contexts.financial_analysis.ports.inbound.user_request import Dataframe, Plotly
from contexts.financial_analysis.ports.outbound.artifact_builder_port import (
    ArtifactBuilderPort,
    ArtifactBundle,
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
from contexts.financial_analysis.ports.outbound.snapshot_version_port import (
    SnapshotVersionPort,
)
from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    CalculationPlan,
)

logger = structlog.get_logger(__name__)

_NO_DOCUMENTS = "Não encontrei documentação aprovada para responder a esta pergunta."
_FALLBACK_INSIGHT = "Aqui estão os números verificados:"


@dataclass(frozen=True)
class AnalysisOutcome:
    """O resultado verificado, o texto que o explica e a tabela dos números.

    `verified_table` é renderizada de forma determinística a partir de `result`
    e existe sempre — é o que o usuário recebe quando o redator falha no lastro.
    `grounded` diz se o texto passou no lastro; `insight_attempts` quantas
    vezes o redator foi chamado. `contents` são os blocos determinísticos
    (`Dataframe`/`Plotly`) da apresentação escolhida no plano, quando há.
    """

    result: AnalysisResult
    insight: str
    verified_table: str
    grounded: bool = True
    insight_attempts: int = 1
    contents: tuple[Dataframe | Plotly, ...] = ()


@dataclass(frozen=True)
class _GroundedInsight:
    text: str
    grounded: bool
    attempts: int
    retry_ms: float


class AnalysisPipeline:
    """Orquestra a execução de um pacote analítico já validado."""

    def __init__(
        self,
        *,
        calculation: CalculationPort,
        snapshot_version: SnapshotVersionPort,
        knowledge: KnowledgePort,
        insight: InsightPort,
        documental_synthesis: DocumentalSynthesisPort | None = None,
        artifacts: ArtifactBuilderPort | None = None,
        prompt_version: str = "",
    ):
        """`prompt_version` é a versão efetiva dos contratos de prompt do
        processo (a mesma que o `/health` reporta), carimbada em cada
        `AnalysisResult` para o resultado ser reproduzível."""

        self._calculation = calculation
        self._snapshot_version = snapshot_version
        self._knowledge = knowledge
        self._insight = insight
        self._documental_synthesis = documental_synthesis
        self._artifacts = artifacts
        self._prompt_version = prompt_version

    async def run(
        self,
        *,
        question: str,
        locale: str,
        session_id: str,
        analysis_plan: AnalysisPlan,
        calculations: Sequence[CalculationPlan],
        catalog: SemanticCatalog,
        assumptions: Sequence[str] = (),
        trace_id: str | None = None,
    ) -> AnalysisOutcome:
        """Executa o pacote aprovado e devolve o resultado com o insight."""

        snapshot = self._snapshot_version.current()
        started = time.perf_counter()

        calculation_results, excerpts = await asyncio.gather(
            asyncio.to_thread(
                self._calculation.execute,
                calculations,
                catalog_version=catalog.catalog_version,
                snapshot_version=snapshot,
            ),
            asyncio.to_thread(self._knowledge.retrieve, question, locale=locale),
        )

        parallel_ms = (time.perf_counter() - started) * 1000

        populations = populations_from_results(calculation_results)
        unjudged = rows_without_population(calculation_results)

        if not populations and any(result.values for result in calculation_results):
            logger.warning("Populations unavailable; small-cell suppression skipped")
        elif unjudged:
            logger.warning(
                "Some rows carry a value without population; not judged by k",
                rows_without_population=unjudged,
            )

        result = execute_analysis(
            analysis_plan,
            calculation_results,
            catalog,
            dataset_version=snapshot,
            trace_id=trace_id or uuid4().hex,
            populations=populations,
            prompt_version=self._prompt_version,
        )
        verified_table = render_verified_table(result)
        artifacts = _render_artifacts(
            self._artifacts, result, analysis_plan.presentation
        )

        analysis_ms = (time.perf_counter() - started) * 1000 - parallel_ms

        grounded = await self._grounded_insight(
            question=question,
            result=result,
            excerpts=excerpts,
            caveats=_caveats(result, assumptions),
            session_id=session_id,
            verified_table=verified_table,
        )

        total_ms = (time.perf_counter() - started) * 1000

        logger.info(
            "Pipeline executed",
            plans=len(calculations),
            parallel_ms=round(parallel_ms, 1),
            analysis_ms=round(analysis_ms, 1),
            insight_ms=round(
                total_ms - parallel_ms - analysis_ms - grounded.retry_ms, 1
            ),
            insight_retry_ms=round(grounded.retry_ms, 1),
            total_ms=round(total_ms, 1),
            artifact_blocks=len(artifacts.contents),
        )

        return AnalysisOutcome(
            result=result,
            insight=grounded.text,
            verified_table=verified_table,
            grounded=grounded.grounded,
            insight_attempts=grounded.attempts,
            contents=artifacts.contents,
        )

    async def _grounded_insight(
        self,
        *,
        question: str,
        result: AnalysisResult,
        excerpts: Sequence[KnowledgeExcerpt],
        caveats: Sequence[str],
        session_id: str,
        verified_table: str,
    ) -> _GroundedInsight:
        """Portão de lastro: só devolve texto cujos números existem no resultado.

        Uma regeneração apontando os números recusados; na segunda falha, o
        texto vira a ressalva fixa mais a tabela verificada. Devolve o texto,
        se passou no lastro, as tentativas e a latência da regeneração (0
        quando não houve)."""

        document_ids = [excerpt.document_id for excerpt in excerpts]
        insight = await self._insight.explain(
            question=question,
            result=result,
            excerpts=excerpts,
            caveats=caveats,
            session_id=session_id,
        )
        presented = present_insight(insight, result, document_ids=document_ids)
        rejected = _unverified_numbers(presented, result)

        if not rejected:
            return _GroundedInsight(presented, grounded=True, attempts=1, retry_ms=0.0)

        logger.warning(
            "Insight cites numbers outside the result; regenerating once",
            rejected=list(rejected),
        )

        retry_started = time.perf_counter()
        insight = await self._insight.explain(
            question=question,
            result=result,
            excerpts=excerpts,
            caveats=caveats,
            session_id=session_id,
            rejected_numbers=rejected,
        )
        presented = present_insight(insight, result, document_ids=document_ids)
        rejected = _unverified_numbers(presented, result)
        retry_ms = (time.perf_counter() - retry_started) * 1000

        if not rejected:
            return _GroundedInsight(
                presented, grounded=True, attempts=2, retry_ms=retry_ms
            )

        logger.warning(
            "Insight rejected twice; delivering verified table only",
            rejected=list(rejected),
        )

        return _GroundedInsight(
            f"{_FALLBACK_INSIGHT}\n\n{verified_table}",
            grounded=False,
            attempts=2,
            retry_ms=retry_ms,
        )

    async def documental(self, *, question: str, locale: str) -> str:
        """Responde a uma pergunta documental com os trechos aprovados.

        Com o port de síntese, o texto é redigido a partir dos trechos citando
        os documentos pelo título; sem ele — ou se a síntese falhar — devolve a
        concatenação crua dos trechos. Sem trechos, abstém-se."""

        excerpts = self._knowledge.retrieve(question, locale=locale)

        if not excerpts:
            return _NO_DOCUMENTS

        if self._documental_synthesis is not None:
            try:
                synthesized = await self._documental_synthesis.synthesize(
                    question=question,
                    excerpts=excerpts,
                    locale=locale,
                )
            except Exception as error:
                logger.warning(
                    "Documental synthesis failed; using raw excerpts",
                    error=type(error).__name__,
                )
            else:
                if synthesized.strip():
                    return synthesized

        return _raw_documental(excerpts)


def _raw_documental(excerpts: Sequence[KnowledgeExcerpt]) -> str:
    """Concatenação crua dos trechos: contingência e caminho sem síntese."""

    return "\n\n".join(
        f"{excerpt.title} — {excerpt.section}\n{excerpt.text}" for excerpt in excerpts
    )


def _render_artifacts(
    builder: ArtifactBuilderPort | None,
    result: AnalysisResult,
    presentation: Presentation | None,
) -> ArtifactBundle:
    """Blocos determinísticos do turno; sem apresentação ou builder, nenhum."""

    if builder is None or presentation is None:
        return ArtifactBundle()

    return builder.build(result.trace_id, result, presentation)


def _unverified_numbers(text: str, result: AnalysisResult) -> tuple[str, ...]:
    """Números citados no texto que não existem no resultado; vazio = lastro ok."""

    try:
        validate_insight_numbers(text, result)
    except InsightNumberError as error:
        return error.numbers

    return ()


def _caveats(
    result: AnalysisResult,
    assumptions: Sequence[str],
) -> list[str]:
    """Monta as ressalvas a partir do resultado e dos defaults aplicados."""

    caveats = list(assumptions)
    undefined = {
        row.undefined
        for method in result.statistical_method
        for row in method.values
        if row.undefined is not None
    }

    # Sem dígitos: o redator ecoa as ressalvas e o gate de lastro rejeitaria
    # "10" como número fora do resultado.
    if UndefinedReason.SMALL_CELL in undefined:
        caveats.append(
            "Células com menos de dez clientes foram suprimidas (small-cell)."
        )

    if UndefinedReason.NO_OBSERVATIONS in undefined:
        caveats.append("Há grupos sem observações elegíveis na janela.")

    if UndefinedReason.NOT_COMPUTABLE in undefined:
        caveats.append("Há medidas não calculáveis com os dados disponíveis.")

    return caveats

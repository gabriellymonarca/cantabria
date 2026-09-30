"""Pipeline ponta a ponta: pergunta → planos → cálculo → análise → insight.

Os ports outbound são fakes determinísticos: o cálculo devolve resultados
prontos, o conhecimento e o insight devolvem saídas fixas.
O que se garante é a ORQUESTRAÇÃO: o pacote validado é executado, o resultado
carrega procedência, o turno é entregue e a resposta ao usuário é o texto do
insight.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from contexts.auth.adapters.outbound.yaml_capabilities import (
    YamlCapabilitiesAdapter,
)
from contexts.auth.application.queries.authorize import AuthorizeQuery
from contexts.auth.domain.user import Role, User
from contexts.financial_analysis.adapters.outbound.auth_capacity_acl import (
    AuthCapacityAcl,
)
from contexts.financial_analysis.adapters.outbound.in_memory_analysis_request_repository import (
    InMemoryAnalysisRequestRepository,
)
from contexts.financial_analysis.adapters.outbound.in_memory_plan_store import (
    InMemoryPlanStore,
)
from contexts.financial_analysis.adapters.outbound.in_memory_result_store import (
    InMemoryResultStore,
)
from contexts.financial_analysis.adapters.outbound.plotly_artifact_builder import (
    PlotlyArtifactBuilder,
)
from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.application.commands.answer_question import (
    AnswerQuestionHandler,
)
from contexts.financial_analysis.application.commands.execute_pipeline import (
    AnalysisPipeline,
    _caveats,
)
from contexts.financial_analysis.application.policies.build_artifacts import (
    BuildArtifactsPolicy,
)
from contexts.financial_analysis.application.policies.persist_results import (
    PersistResultsPolicy,
)
from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    StatisticalMethod,
    StatisticalMethodType,
)
from contexts.financial_analysis.domain.analysis_request import AnalysisStatus
from contexts.financial_analysis.domain.analysis_result import (
    AnalysisResult,
    MethodResult,
    MethodValue,
    UndefinedReason,
)
from contexts.financial_analysis.domain.artifacts import ArtifactKind, ArtifactRef
from contexts.financial_analysis.ports.inbound.user_request import (
    ConversationContext,
    Dataframe,
    MethodNote,
    Plotly,
    Text,
)
from contexts.financial_analysis.ports.outbound.artifact_builder_port import (
    ArtifactBuilderPort,
)
from contexts.financial_analysis.ports.outbound.artifact_store_port import (
    ArtifactStorePort,
)
from contexts.financial_analysis.ports.outbound.calculation_port import (
    CalculationPort,
)
from contexts.financial_analysis.ports.outbound.insight_port import InsightPort
from contexts.financial_analysis.ports.outbound.knowledge_port import KnowledgePort
from contexts.financial_analysis.ports.outbound.llm_port import (
    LlmPort,
    LlmReply,
)
from contexts.financial_analysis.ports.outbound.snapshot_version_port import (
    SnapshotVersionPort,
)
from contexts.financial_calculation.domain.calculation_plan import CalculationPlan
from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
    CalculationResultRow,
)
from shared.domain_events import EventDispatcher

CATALOG = YamlSemanticCatalogAdapter().load_active()
SEGMENT = "customer_segmentation.segment"
USER = User(
    id="u1",
    name="Analista",
    email="a@b.com",
    roles=[Role(id="default", name="Analista")],
)


class _Prompt:
    def build_system_prompt(
        self, locale: str, reference_date: date | None = None
    ) -> str:
        return "system"


class _ReferenceDate:
    def latest_reference_date(self) -> date:
        return date(2026, 8, 31)


class _SequenceLlm(LlmPort):
    def __init__(self, payloads: list[dict[str, Any]]):

        self._payloads = payloads
        self.calls = 0

    async def generate(self, messages, session_id: str | None = None) -> LlmReply:

        raise NotImplementedError

    async def generate_structured(
        self, messages, schema, session_id: str | None = None, step: str = "llm"
    ):

        payload = self._payloads[self.calls]
        self.calls += 1

        return schema.model_validate(payload)


class _Calculation(CalculationPort):
    def __init__(self, results: list[CalculationResult]):

        self._results = results
        self.calls: list[tuple] = []

    def execute(self, plans, *, catalog_version, snapshot_version):

        self.calls.append((list(plans), catalog_version, snapshot_version))

        return self._results


class _Snapshot(SnapshotVersionPort):
    def current(self) -> str:

        return "2026-08-31"


class _Knowledge(KnowledgePort):
    def retrieve(self, question, *, locale, limit=5):

        return []


class _Insight(InsightPort):
    """Redator sequenciado: devolve um texto por chamada e grava o que recebeu."""

    def __init__(self, *texts: str):

        self._texts = list(texts) or ["Explicação do LLM."]
        self.caveats: list[str] = []
        self.calls: list[dict] = []

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

        self.caveats = list(caveats)
        self.calls.append({"rejected_numbers": tuple(rejected_numbers)})

        return self._texts[min(len(self.calls) - 1, len(self._texts) - 1)]


class _ArtifactStore(ArtifactStorePort):
    """Artifact Store em memória para o teste da policy."""

    def __init__(self) -> None:

        self.saved: dict[str, tuple[ArtifactRef, ...]] = {}

    def save_artifacts(self, trace_id: str, artifacts: Sequence[ArtifactRef]) -> None:

        self.saved[trace_id] = tuple(artifacts)


def _profitability_result() -> CalculationResult:

    return CalculationResult(
        calculation_plan_id="calc_prof_seg",
        rule_id="profitability",
        unit="decimal_rate",
        values=[
            CalculationResultRow(
                subjects={SEGMENT: "Varejo PF"},
                period="2026-08-31",
                value=Decimal("0.12"),
            ),
            CalculationResultRow(
                subjects={SEGMENT: "Atacado PJ"},
                period="2026-08-31",
                value=Decimal("0.08"),
            ),
        ],
    )


def _analysis_plan() -> AnalysisPlan:

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


def _calculation_payload() -> dict[str, Any]:

    return {
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


def _analytical_payload(presentation: dict[str, Any] | None = None) -> dict[str, Any]:

    analysis: dict[str, Any] = {
        "id": "plan",
        "statistical_method": [
            {
                "id": "s1",
                "method": "null",
                "calculation_plan_ids": ["calc_prof_seg"],
            }
        ],
        "operations": [],
    }

    if presentation is not None:
        analysis["presentation"] = presentation

    return {
        "route": "analytical",
        "analysis": analysis,
        "calculations": [_calculation_payload()],
        "assumptions": ["Período ausente: usei a janela padrão de série."],
    }


def _query(llm: LlmPort, pipeline: AnalysisPipeline) -> AnswerQuestionHandler:

    return AnswerQuestionHandler(
        llm=llm,
        prompt=_Prompt(),
        reference_date=_ReferenceDate(),
        catalog=YamlSemanticCatalogAdapter(),
        auth_capacity=AuthCapacityAcl(AuthorizeQuery(YamlCapabilitiesAdapter())),
        pipeline=pipeline,
    )


def _pipeline(
    insight: _Insight | None = None,
    artifacts: ArtifactBuilderPort | None = None,
) -> tuple[AnalysisPipeline, _Insight]:

    selected = insight or _Insight()
    pipeline = AnalysisPipeline(
        calculation=_Calculation([_profitability_result()]),
        snapshot_version=_Snapshot(),
        knowledge=_Knowledge(),
        insight=selected,
        artifacts=artifacts,
    )

    return pipeline, selected


def test_pipeline_executa_e_entrega_o_resultado() -> None:

    pipeline = AnalysisPipeline(
        calculation=_Calculation([_profitability_result()]),
        snapshot_version=_Snapshot(),
        knowledge=_Knowledge(),
        insight=_Insight(),
    )

    outcome = asyncio.run(
        pipeline.run(
            question="Qual a rentabilidade por segmento?",
            locale="pt-BR",
            session_id="s1",
            analysis_plan=_analysis_plan(),
            calculations=[_calculation_payload_as_plan()],
            catalog=CATALOG,
        )
    )

    assert outcome.insight == "Explicação do LLM."
    assert outcome.result.catalog_version == "v3"
    assert outcome.result.dataset_version == "2026-08-31"
    assert outcome.result.trace_id
    assert "12,00%" in outcome.verified_table
    assert "8,00%" in outcome.verified_table


def test_pipeline_propaga_o_trace_id_do_turno() -> None:

    pipeline, _ = _pipeline()

    outcome = asyncio.run(_run(pipeline, trace_id="trace-do-turno"))

    assert outcome.result.trace_id == "trace-do-turno"
    assert outcome.result.prompt_version == ""


def test_pipeline_carimba_a_versao_dos_prompts_no_resultado() -> None:

    pipeline = AnalysisPipeline(
        calculation=_Calculation([_profitability_result()]),
        snapshot_version=_Snapshot(),
        knowledge=_Knowledge(),
        insight=_Insight(),
        prompt_version="interpretation=v1,insight=v3,documental=v1",
    )

    outcome = asyncio.run(_run(pipeline))

    assert outcome.result.prompt_version == "interpretation=v1,insight=v3,documental=v1"


def _run(pipeline: AnalysisPipeline, **overrides):

    return pipeline.run(
        question="Qual a rentabilidade por segmento?",
        locale="pt-BR",
        session_id="s1",
        analysis_plan=_analysis_plan(),
        calculations=[_calculation_payload_as_plan()],
        catalog=CATALOG,
        **overrides,
    )


def _populated_result() -> CalculationResult:
    """Três células: uma abaixo de k (3 clientes), duas suficientes."""

    return CalculationResult(
        calculation_plan_id="calc_prof_seg",
        rule_id="profitability",
        unit="decimal_rate",
        values=[
            CalculationResultRow(
                subjects={SEGMENT: "Varejo PF"},
                period="2026-08-31",
                value=Decimal("0.12"),
                population=3,
            ),
            CalculationResultRow(
                subjects={SEGMENT: "Atacado PJ"},
                period="2026-08-31",
                value=Decimal("0.08"),
                population=40,
            ),
            CalculationResultRow(
                subjects={SEGMENT: "Private"},
                period="2026-08-31",
                value=Decimal("0.30"),
                population=50,
            ),
        ],
    )


def test_small_cell_e_suprimida_no_pipeline_com_complementar() -> None:
    """k = 10 ativo no pipeline: a
    célula com 3 clientes sai; a menor célula restante também (complementar);
    a ressalva chega ao redator."""

    insight = _Insight()
    pipeline = AnalysisPipeline(
        calculation=_Calculation([_populated_result()]),
        snapshot_version=_Snapshot(),
        knowledge=_Knowledge(),
        insight=insight,
    )

    outcome = asyncio.run(_run(pipeline))

    by_segment = {
        row.subjects[SEGMENT]: row
        for row in outcome.result.statistical_method[0].values
    }

    assert by_segment["Varejo PF"].undefined is UndefinedReason.SMALL_CELL
    assert by_segment["Varejo PF"].values == {}
    assert by_segment["Atacado PJ"].undefined is UndefinedReason.SMALL_CELL
    assert by_segment["Private"].undefined is None
    assert by_segment["Private"].values == {"value": Decimal("0.30")}
    assert any("small-cell" in caveat for caveat in insight.caveats)
    assert "12,00%" not in outcome.verified_table
    assert "30,00%" in outcome.verified_table


def test_insight_sem_lastro_e_regenerado_uma_vez() -> None:

    insight = _Insight("A taxa foi 99,99.", "A taxa do Varejo PF foi 0,12.")
    pipeline, _ = _pipeline(insight)

    outcome = asyncio.run(_run(pipeline))

    assert outcome.insight == "A taxa do Varejo PF foi 0,12."
    assert len(insight.calls) == 2
    assert insight.calls[0]["rejected_numbers"] == ()
    assert insight.calls[1]["rejected_numbers"] == ("99,99",)


def test_insight_rejeitado_duas_vezes_entrega_a_tabela_verificada() -> None:
    """Invariante #1: texto que falhou no lastro NUNCA é entregue; o usuário
    recebe o texto neutro fixo mais a tabela determinística."""

    insight = _Insight("A taxa foi 99,99.", "Agora foi 77,77.")
    pipeline, _ = _pipeline(insight)

    outcome = asyncio.run(_run(pipeline))

    assert len(insight.calls) == 2
    assert outcome.insight.startswith("Aqui estão os números verificados:")
    assert outcome.verified_table in outcome.insight
    assert "| Varejo PF | 2026-08-31 | valor | 12,00% | taxa |" in outcome.insight
    assert "99,99" not in outcome.insight
    assert "77,77" not in outcome.insight


def test_insight_com_lastro_e_chamado_uma_vez() -> None:

    insight = _Insight("Varejo PF rende 0,12 e Atacado PJ 0,08.")
    pipeline, _ = _pipeline(insight)

    outcome = asyncio.run(_run(pipeline))

    assert len(insight.calls) == 1
    assert outcome.insight == "Varejo PF rende 0,12 e Atacado PJ 0,08."


def test_resposta_ao_usuario_e_o_texto_do_insight() -> None:

    pipeline, _ = _pipeline()
    llm = _SequenceLlm([_analytical_payload()])

    contents = asyncio.run(
        _query(llm, pipeline).execute(
            USER,
            ConversationContext(session_id="s1", messages=[]),
            "Qual a rentabilidade por segmento?",
        )
    )

    # O insight é o primeiro bloco; o rodapé de procedência vem separado, fora da
    # sanitização e da validação de números; a nota "Como calculei" é o terceiro
    # bloco, determinístico.
    assert contents[0] == Text(text="Explicação do LLM.")
    assert len(contents) == 3
    assert isinstance(contents[1], Text)
    assert contents[1].text.startswith("_Fonte: rentabilidade (Σ margem ÷ Σ saldo)")
    assert "v3" not in contents[1].text
    assert isinstance(contents[2], MethodNote)
    assert contents[2].title == "Como calculei"
    assert "- Método: valores verificados do período" in contents[2].text


def test_rota_analitica_devolve_dataframe_e_plotly_com_apresentacao() -> None:
    """Com apresentação no plano, a resposta ganha os blocos determinísticos:
    o texto do redator, o rodapé e os DTOs montados do `AnalysisResult`."""

    pipeline, _ = _pipeline(artifacts=PlotlyArtifactBuilder())
    llm = _SequenceLlm(
        [
            _analytical_payload(
                {
                    "type": "bar",
                    "axis": "entity",
                    "title": "Rentabilidade por segmento",
                }
            )
        ]
    )

    contents = asyncio.run(
        _query(llm, pipeline).execute(
            USER,
            ConversationContext(session_id="s1", messages=[]),
            "Qual a rentabilidade por segmento?",
        )
    )

    text, footer, note, dataframe, plotly = contents

    assert text == Text(text="Explicação do LLM.")
    assert isinstance(footer, Text) and footer.text.startswith("_Fonte:")
    assert isinstance(note, MethodNote)
    assert isinstance(dataframe, Dataframe)
    assert [row[3] for row in dataframe.rows] == [Decimal("0.12"), Decimal("0.08")]
    assert isinstance(plotly, Plotly)
    assert plotly.figure["data"][0]["y"] == [Decimal("0.12"), Decimal("0.08")]


def test_rota_analitica_sem_presentation_devolve_texto_rodape_e_nota() -> None:

    pipeline, _ = _pipeline(artifacts=PlotlyArtifactBuilder())
    llm = _SequenceLlm([_analytical_payload()])

    contents = asyncio.run(
        _query(llm, pipeline).execute(
            USER,
            ConversationContext(session_id="s1", messages=[]),
            "Qual a rentabilidade por segmento?",
        )
    )

    assert len(contents) == 3
    assert isinstance(contents[0], Text) and isinstance(contents[1], Text)
    assert contents[1].text.startswith("_Fonte:")
    assert isinstance(contents[2], MethodNote)


def test_undefined_suprimido_fica_fora_do_grafico_da_rota() -> None:
    """A célula suprimida pelo k = 10 não vira ponto no gráfico nem linha na
    tabela: o artefato nunca desfaz a supressão da small-cell."""

    pipeline = AnalysisPipeline(
        calculation=_Calculation([_populated_result()]),
        snapshot_version=_Snapshot(),
        knowledge=_Knowledge(),
        insight=_Insight(),
        artifacts=PlotlyArtifactBuilder(),
    )
    llm = _SequenceLlm([_analytical_payload({"type": "bar", "axis": "entity"})])

    contents = asyncio.run(
        _query(llm, pipeline).execute(
            USER,
            ConversationContext(session_id="s1", messages=[]),
            "Qual a rentabilidade por segmento?",
        )
    )

    dataframe, plotly = contents[3], contents[4]

    assert isinstance(dataframe, Dataframe) and isinstance(plotly, Plotly)

    plotted = plotly.figure["data"][0]

    assert "Private" in plotted["x"]
    assert "Varejo PF" not in plotted["x"]
    assert "Atacado PJ" not in plotted["x"]
    assert all("Varejo PF" not in row[0] for row in dataframe.rows)
    assert all("Atacado PJ" not in row[0] for row in dataframe.rows)


def test_apresentacao_invalida_degrada_para_table_na_rota() -> None:
    """O catálogo é fechado, mas a forma é cosmética: um tipo inválido não
    derruba o plano — a rota entrega os números com a tabela (default)."""

    pipeline, _ = _pipeline(artifacts=PlotlyArtifactBuilder())
    llm = _SequenceLlm([_analytical_payload({"type": "pie", "axis": "entity"})])

    contents = asyncio.run(
        _query(llm, pipeline).execute(
            USER,
            ConversationContext(session_id="s1", messages=[]),
            "Qual a rentabilidade por segmento?",
        )
    )

    text, footer, note, dataframe = contents

    assert text == Text(text="Explicação do LLM.")
    assert isinstance(footer, Text)
    assert isinstance(note, MethodNote)
    assert isinstance(dataframe, Dataframe)
    assert len(contents) == 4


def test_turno_analitico_e_persistido_pela_policy() -> None:
    """O handler salva o `AnalysisRequest` e publica os eventos; a policy
    `PersistResults` reage a `AnalysisCompleted`/`InsightGenerated` gravando
    planos, resultado e insight — o pipeline não entrega nada sozinho."""

    pipeline, _ = _pipeline()
    llm = _SequenceLlm([_analytical_payload()])

    dispatcher = EventDispatcher()
    repository = InMemoryAnalysisRequestRepository()
    plan_store = InMemoryPlanStore()
    result_store = InMemoryResultStore()
    PersistResultsPolicy(
        repository=repository, plan_store=plan_store, result_store=result_store
    ).subscribe(dispatcher)

    handler = AnswerQuestionHandler(
        llm=llm,
        prompt=_Prompt(),
        reference_date=_ReferenceDate(),
        catalog=YamlSemanticCatalogAdapter(),
        auth_capacity=AuthCapacityAcl(AuthorizeQuery(YamlCapabilitiesAdapter())),
        pipeline=pipeline,
        repository=repository,
        publisher=dispatcher,
    )

    asyncio.run(
        handler.execute(
            USER,
            ConversationContext(session_id="s1", messages=[], trace_id="turno-7"),
            "Qual a rentabilidade por segmento?",
        )
    )

    request = repository.get("turno-7")

    assert request is not None
    assert request.status is AnalysisStatus.EXPLAINED
    assert plan_store.plans["turno-7"].catalog_version == "v3"
    assert result_store.results["turno-7"] is request.result
    assert result_store.insights["turno-7"].insight == "Explicação do LLM."


def test_policy_de_artefatos_persiste_as_refs_do_turno() -> None:
    """A policy segue o fluxo do evento `InsightGenerated`: pede ao builder os
    refs do resultado (na apresentação selada) e grava no Artifact Store."""

    pipeline, _ = _pipeline(artifacts=PlotlyArtifactBuilder())
    llm = _SequenceLlm(
        [
            _analytical_payload(
                {"type": "bar", "axis": "entity", "title": "Rentabilidade"}
            )
        ]
    )

    dispatcher = EventDispatcher()
    repository = InMemoryAnalysisRequestRepository()
    artifact_store = _ArtifactStore()
    BuildArtifactsPolicy(
        repository=repository,
        builder=PlotlyArtifactBuilder(),
        artifact_store=artifact_store,
    ).subscribe(dispatcher)

    handler = AnswerQuestionHandler(
        llm=llm,
        prompt=_Prompt(),
        reference_date=_ReferenceDate(),
        catalog=YamlSemanticCatalogAdapter(),
        auth_capacity=AuthCapacityAcl(AuthorizeQuery(YamlCapabilitiesAdapter())),
        pipeline=pipeline,
        repository=repository,
        publisher=dispatcher,
    )

    asyncio.run(
        handler.execute(
            USER,
            ConversationContext(session_id="s1", messages=[], trace_id="turno-9"),
            "Qual a rentabilidade por segmento?",
        )
    )

    refs = artifact_store.saved["turno-9"]

    assert [ref.kind for ref in refs] == [ArtifactKind.TABLE, ArtifactKind.CHART]
    assert all(ref.location.startswith("derived://analysis-result/") for ref in refs)


def test_defaults_viram_ressalvas_do_insight() -> None:

    pipeline, insight = _pipeline()
    llm = _SequenceLlm([_analytical_payload()])

    asyncio.run(
        _query(llm, pipeline).execute(
            USER,
            ConversationContext(session_id="s1", messages=[]),
            "Qual a rentabilidade por segmento?",
        )
    )

    assert "Período ausente: usei a janela padrão de série." in insight.caveats


def test_rota_clarify_devolve_a_pergunta_ao_usuario() -> None:

    pipeline, _ = _pipeline()
    llm = _SequenceLlm([{"route": "clarify", "clarification_question": "De quando?"}])

    contents = asyncio.run(
        _query(llm, pipeline).execute(
            USER,
            ConversationContext(session_id="s1", messages=[]),
            "Como estamos indo?",
        )
    )

    assert contents == [Text(text="De quando?")]


def test_rota_refuse_devolve_o_motivo() -> None:

    pipeline, _ = _pipeline()
    llm = _SequenceLlm(
        [
            {
                "route": "refuse",
                "refusal_reason": "out_of_scope",
                "refusal_message": "Produção de crédito é fluxo, fora do escopo.",
            }
        ]
    )

    contents = asyncio.run(
        _query(llm, pipeline).execute(
            USER,
            ConversationContext(session_id="s1", messages=[]),
            "Qual foi a produção de crédito em agosto?",
        )
    )

    assert contents == [Text(text="Produção de crédito é fluxo, fora do escopo.")]


def test_rota_documental_sem_acervo_avisa_o_usuario() -> None:

    pipeline, _ = _pipeline()
    llm = _SequenceLlm([{"route": "documental"}])

    contents = asyncio.run(
        _query(llm, pipeline).execute(
            USER,
            ConversationContext(session_id="s1", messages=[]),
            "O que é Vinculação?",
        )
    )

    assert contents[0].text.startswith("Não encontrei documentação aprovada")


def test_small_cell_vira_ressalva() -> None:

    result = AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v2",
        dataset_version="2026-08-31",
        trace_id="t1",
        statistical_method=[
            MethodResult(
                id="s1",
                method="null",
                values=[
                    MethodValue({SEGMENT: "Varejo PF"}, {}, UndefinedReason.SMALL_CELL)
                ],
            )
        ],
    )

    caveats = _caveats(result, ["default aplicado"])

    assert "default aplicado" in caveats
    assert any("small-cell" in caveat for caveat in caveats)
    assert not any(char.isdigit() for caveat in caveats[1:] for char in caveat)


def test_pipeline_avisa_quando_so_parte_das_linhas_tem_populacao() -> None:
    """Linha com valor e sem população passa pelo k sem ser julgada; o
    pipeline tem de dizer QUANTAS ficaram nessa situação."""

    from structlog.testing import capture_logs

    mixed = CalculationResult(
        calculation_plan_id="calc_prof_seg",
        rule_id="profitability",
        unit="decimal_rate",
        values=[
            CalculationResultRow(
                subjects={SEGMENT: "Varejo PF"},
                period="2026-08-31",
                value=Decimal("0.12"),
                population=40,
            ),
            CalculationResultRow(
                subjects={SEGMENT: "Atacado PJ"},
                period="2026-08-31",
                value=Decimal("0.08"),
                population=None,
            ),
        ],
    )
    pipeline = AnalysisPipeline(
        calculation=_Calculation([mixed]),
        snapshot_version=_Snapshot(),
        knowledge=_Knowledge(),
        insight=_Insight(),
    )

    with capture_logs() as logs:
        asyncio.run(_run(pipeline))

    warnings = [log for log in logs if log.get("log_level") == "warning"]

    assert any(log.get("rows_without_population") == 1 for log in warnings)


def test_ressalva_de_small_cell_ecoada_pelo_redator_passa_no_lastro() -> None:
    """O prompt pede ao redator para mencionar as ressalvas; se ele ecoar a de
    small-cell (ou escrever "10 clientes"), o gate de lastro não pode tratar
    isso como número inventado — senão regenera à toa."""

    insight = _Insight(
        "Private rende 0,30. Células com menos de dez clientes foram suprimidas "
        "(small-cell); cada célula precisa de 10 clientes."
    )
    pipeline = AnalysisPipeline(
        calculation=_Calculation([_populated_result()]),
        snapshot_version=_Snapshot(),
        knowledge=_Knowledge(),
        insight=insight,
    )

    outcome = asyncio.run(_run(pipeline))

    assert len(insight.calls) == 1
    assert outcome.insight.startswith("Private rende 0,30.")
    assert "10 clientes" in outcome.insight


def _calculation_payload_as_plan() -> CalculationPlan:
    """Constrói o CalculationPlan a partir do payload do LLM."""

    from contexts.financial_analysis.application.commands.answer_question import (
        InterpretationProposal,
    )

    proposal = InterpretationProposal.model_validate(_analytical_payload())

    return proposal.calculations[0]

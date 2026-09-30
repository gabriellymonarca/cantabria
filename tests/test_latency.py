from __future__ import annotations

import asyncio
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

from contexts.financial_analysis.adapters.outbound.langchain_insight import (
    LangChainInsightAdapter,
)
from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.application.commands.answer_question import (
    _context_messages,
)
from contexts.financial_analysis.application.commands.execute_pipeline import (
    AnalysisPipeline,
)
from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    StatisticalMethod,
    StatisticalMethodType,
)
from contexts.financial_analysis.ports.inbound.user_request import (
    ConversationContext,
    MessageRole,
    Text,
)
from contexts.financial_analysis.ports.outbound.calculation_port import (
    CalculationPort,
)
from contexts.financial_analysis.ports.outbound.insight_port import InsightPort
from contexts.financial_analysis.ports.outbound.knowledge_port import KnowledgePort
from contexts.financial_analysis.ports.outbound.llm_port import LlmReply
from contexts.financial_analysis.ports.outbound.snapshot_version_port import (
    SnapshotVersionPort,
)
from contexts.financial_calculation.adapters.outbound.in_memory_calculation_store import (
    InMemoryCalculationStore,
)
from contexts.financial_calculation.application.commands.execute_calculations import (
    ExecuteCalculationsHandler,
)
from contexts.financial_calculation.domain.calculation_plan import (
    AxisLevel,
    AxisType,
    CalculationPlan,
    Grain,
    Metric,
    Period,
    PeriodType,
    RuleId,
    Subject,
)
from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
    CalculationResultRow,
)
from contexts.financial_calculation.ports.outbound.official_data_repository import (
    AggregatedRow,
)

CATALOG = YamlSemanticCatalogAdapter().load_active()
SEGMENT = "customer_segmentation.segment"


class _SlowRepository:
    def __init__(self, delay: float = 0.05):

        self._delay = delay

    def fetch_aggregated(self, metric, period) -> list[AggregatedRow]:

        time.sleep(self._delay)

        return [
            AggregatedRow(
                subjects={SEGMENT: "Varejo PF"},
                period="2026-08-31",
                components={"value": Decimal("400.00")},
            )
        ]


def _plan(plan_id: str, rule_id: RuleId, month: int) -> CalculationPlan:

    return CalculationPlan(
        calculation_plan_id=plan_id,
        metric=Metric(
            id=None,
            rule_id=rule_id,
            subjects=[
                Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SEGMENT)
            ],
            sample=[],
        ),
        period=Period(
            start=date(2026, min(month, 8), 1),
            end=date(2026, 8, 31),
            type=PeriodType.SERIES,
            grain=Grain.MONTH,
        ),
    )


def test_planos_executam_em_paralelo_preservando_a_ordem() -> None:

    service = ExecuteCalculationsHandler(
        repository=_SlowRepository(),
        store=InMemoryCalculationStore(),
    )
    plans = [
        _plan("calc_a", RuleId.OUTSTANDING_BALANCE, 6),
        _plan("calc_b", RuleId.OUTSTANDING_BALANCE, 7),
        _plan("calc_c", RuleId.OUTSTANDING_BALANCE, 5),
    ]

    started = time.perf_counter()
    results = service.execute(plans, catalog_version="v1", snapshot_version="s1")
    elapsed = time.perf_counter() - started

    assert [result.calculation_plan_id for result in results] == [
        "calc_a",
        "calc_b",
        "calc_c",
    ]
    assert elapsed < 0.15


def test_um_plano_sozinho_nao_usa_thread_pool() -> None:

    service = ExecuteCalculationsHandler(
        repository=_SlowRepository(),
        store=InMemoryCalculationStore(),
    )

    results = service.execute(
        [_plan("calc_a", RuleId.OUTSTANDING_BALANCE, 6)],
        catalog_version="v1",
        snapshot_version="s1",
    )

    assert [result.calculation_plan_id for result in results] == ["calc_a"]


class _SlowCalculation(CalculationPort):
    def __init__(self, results: list[CalculationResult], delay: float = 0.3):

        self._results = results
        self._delay = delay

    def execute(self, plans, *, catalog_version, snapshot_version):

        time.sleep(self._delay)

        return self._results


class _SlowKnowledge(KnowledgePort):
    def __init__(self, delay: float = 0.3):

        self._delay = delay

    def retrieve(self, question, *, locale, limit=5):

        time.sleep(self._delay)

        return []


class _Insight(InsightPort):
    async def explain(
        self, *, question, result, excerpts=(), caveats=(), session_id=None
    ) -> str:

        return "Explicação do LLM."


class _Snapshot(SnapshotVersionPort):
    def current(self) -> str:

        return "2026-08-31"


def _profitability_result(plan_id: str = "calc_prof_seg") -> CalculationResult:

    return CalculationResult(
        calculation_plan_id=plan_id,
        rule_id="profitability",
        unit="decimal_rate",
        values=[
            CalculationResultRow(
                subjects={SEGMENT: "Varejo PF"},
                period="2026-08-31",
                value=Decimal("0.12"),
            ),
        ],
    )


def test_knowledge_roda_em_paralelo_com_o_calculo() -> None:

    pipeline = AnalysisPipeline(
        calculation=_SlowCalculation([_profitability_result()]),
        snapshot_version=_Snapshot(),
        knowledge=_SlowKnowledge(),
        insight=_Insight(),
    )
    analysis = AnalysisPlan(
        id="plan",
        statistical_method=[
            StatisticalMethod(
                id="s1",
                method=StatisticalMethodType.NULL,
                calculation_plan_ids=["calc_prof_seg"],
            )
        ],
    )

    started = time.perf_counter()

    outcome = asyncio.run(
        pipeline.run(
            question="Qual a rentabilidade por segmento?",
            locale="pt-BR",
            session_id="s1",
            analysis_plan=analysis,
            calculations=[
                _plan("calc_prof_seg", RuleId.PROFITABILITY, 9),
            ],
            catalog=CATALOG,
        )
    )

    elapsed = time.perf_counter() - started

    assert outcome.insight == "Explicação do LLM."
    assert elapsed < 0.55


def test_historico_limitado_as_ultimas_mensagens() -> None:

    history = [
        (
            MessageRole.USER if index % 2 == 0 else MessageRole.ASSISTANT,
            [Text(text=f"msg {index}")],
        )
        for index in range(30)
    ]

    messages = _context_messages(history)

    assert len(messages) <= 10
    assert messages[-1].content == "msg 29"
    assert messages[0].content == "msg 20"


def test_mensagem_longa_do_historico_e_truncada() -> None:

    history = [(MessageRole.USER, [Text(text="x" * 5000)])]

    messages = _context_messages(history)

    assert len(messages[0].content) == 2000


class _CountingLlm:
    def __init__(self):

        self.calls = 0
        self.steps: list[str] = []

    async def generate(self, messages, session_id=None, step="llm") -> LlmReply:

        self.calls += 1
        self.steps.append(step)

        return LlmReply(text="Explicação.", model="test", usage=None)


def test_insight_reaproveita_resposta_para_mesma_pergunta(tmp_path: Path) -> None:

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "base.md").write_text("system", encoding="utf-8")

    llm = _CountingLlm()
    adapter = LangChainInsightAdapter(llm=llm, prompts_dir=prompts_dir)  # type: ignore[arg-type]

    from contexts.financial_analysis.domain.analysis_result import (
        AnalysisResult,
        MethodResult,
        MethodValue,
    )

    result = AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v2",
        dataset_version="2026-08-31",
        trace_id="t1",
        statistical_method=[
            MethodResult(
                id="s1",
                method="null",
                values=[MethodValue(subjects={}, values={"value": Decimal("1")})],
            )
        ],
    )

    async def _run_twice() -> None:

        first = await adapter.explain(question="Q?", result=result)
        second = await adapter.explain(question="Q?", result=result)

        assert first == second == "Explicação."

    asyncio.run(_run_twice())

    assert llm.calls == 1
    assert llm.steps == ["insight"]


def test_rodape_de_procedencia_nao_volta_ao_contexto_do_planner() -> None:
    """O rodapé `_Fonte: ...` é um bloco `Text` do assistente com metadados (regra,
    catálogo, dados, trace). Só o insight volta ao contexto do planner; um turno
    só com rodapé não vira mensagem."""

    footer = (
        "_Fonte: rentabilidade (Σ margem ÷ Σ saldo), dados oficiais fechados em "
        "31/08/2026 · protocolo CAN-T1_"
    )
    history = [
        (MessageRole.USER, [Text(text="Qual a rentabilidade por segmento?")]),
        (MessageRole.ASSISTANT, [Text(text="Explicação do LLM."), Text(text=footer)]),
        (MessageRole.ASSISTANT, [Text(text=footer)]),
    ]

    messages = _context_messages(history)

    assert [message.content for message in messages] == [
        "Qual a rentabilidade por segmento?",
        "Explicação do LLM.",
    ]


def test_turno_recusado_pelo_guardrail_nao_volta_ao_planner() -> None:
    """O texto barrado antes do LLM (SQL, injeção, mensagem longa) não pode
    reaparecer como histórico no turno seguinte: o par pergunta/recusa sai."""

    from contexts.financial_analysis.application.commands.answer_question import (
        _INPUT_REFUSALS,
    )
    from contexts.financial_analysis.domain.insight_presentation import (
        sanitize_user_text,
    )
    from contexts.financial_analysis.domain.services.input_guard import SQL_FRAGMENT

    refusal = sanitize_user_text(_INPUT_REFUSALS[SQL_FRAGMENT])
    history = [
        (MessageRole.USER, [Text(text="Qual a rentabilidade por segmento?")]),
        (MessageRole.ASSISTANT, [Text(text="Explicação do LLM.")]),
        (MessageRole.USER, [Text(text="select vl_margem from tabela; drop table x")]),
        (MessageRole.ASSISTANT, [Text(text=refusal)]),
        (MessageRole.USER, [Text(text="E por produto?")]),
    ]

    messages = _context_messages(history)

    assert [message.content for message in messages] == [
        "Qual a rentabilidade por segmento?",
        "Explicação do LLM.",
        "E por produto?",
    ]


def test_contexto_sem_historico_nao_estoura_o_limite() -> None:

    context = ConversationContext(session_id="s1", messages=[])

    assert _context_messages(context.messages) == []


def test_exemplos_do_prompt_cabem_no_orcamento() -> None:

    # Os exemplos mostram a seção `presentation`, parte do contrato do
    # AnalysisPlan; o orçamento guarda a ordem de grandeza do prompt do planner.

    path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "prompts"
        / "interpretation"
        / "v1"
        / "examples.pt-BR.md"
    )

    assert len(path.read_text(encoding="utf-8")) < 12000

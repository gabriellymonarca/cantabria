"""Apresentação do insight: número em pt-BR, sem id interno, com lastro.

Cobre o formatador por unidade, o sanitizador de identificadores internos, o
validador de lastro dos números, a propagação de `unit`/`rule_id` até o
`AnalysisResult` e o cenário ponta a ponta com id vazando e `0.154632`.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from contexts.auth.adapters.outbound.yaml_capabilities import (
    YamlCapabilitiesAdapter,
)
from contexts.auth.application.queries.authorize import AuthorizeQuery
from contexts.auth.domain.user import Role, User
from contexts.financial_analysis.adapters.outbound.auth_capacity_acl import (
    AuthCapacityAcl,
)
from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.application.commands.answer_question import (
    AnswerQuestionHandler,
)
from contexts.financial_analysis.application.commands.execute_pipeline import (
    AnalysisPipeline,
)
from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    Operation,
    OperationType,
    StatisticalMethod,
    StatisticalMethodType,
)
from contexts.financial_analysis.domain.analysis_result import (
    AnalysisResult,
    MethodResult,
    MethodValue,
    UndefinedReason,
)
from contexts.financial_analysis.domain.insight_presentation import (
    InsightNumberError,
    format_insight_numbers,
    format_number,
    present_insight,
    render_verified_table,
    sanitize_user_text,
    validate_insight_numbers,
)
from contexts.financial_analysis.domain.services.execute_analysis import (
    execute_analysis,
)
from contexts.financial_analysis.ports.inbound.user_request import (
    ConversationContext,
    Text,
)
from contexts.financial_analysis.ports.outbound.calculation_port import (
    CalculationPort,
)
from contexts.financial_analysis.ports.outbound.insight_port import InsightPort
from contexts.financial_analysis.ports.outbound.knowledge_port import KnowledgePort
from contexts.financial_analysis.ports.outbound.llm_port import LlmPort
from contexts.financial_analysis.ports.outbound.snapshot_version_port import (
    SnapshotVersionPort,
)
from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
    CalculationResultRow,
)

CATALOG = YamlSemanticCatalogAdapter().load_active()
SEGMENT = "customer_segmentation.segment"
USER = User(
    id="u1",
    name="Analista",
    email="a@b.com",
    roles=[Role(id="default", name="Analista")],
)


def _rate_result(value: Decimal = Decimal("0.154632")) -> AnalysisResult:

    return AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v2",
        dataset_version="2026-08-31",
        trace_id="trace-1",
        statistical_method=[
            MethodResult(
                id="s1",
                method="null",
                values=[MethodValue({SEGMENT: "Varejo PF"}, {"value": value})],
                unit="decimal_rate",
                rule_id="profitability",
            )
        ],
        unit="decimal_rate",
        rule_id="profitability",
    )


def test_taxa_formata_com_duas_casas() -> None:

    assert format_number(Decimal("0.154632"), "decimal_rate") == "0,15"


def test_moeda_formata_com_duas_casas_e_milhar() -> None:

    assert format_number(Decimal("1234.5"), "currency") == "1.234,50"
    assert (
        format_number(Decimal("1234.5"), "currency", with_currency_symbol=True)
        == "R$ 1.234,50"
    )


def test_contagem_permanece_inteira() -> None:

    assert format_number(42, "count") == "42"
    assert format_number(Decimal("42.00"), "count") == "42"


def test_chave_percent_lê_como_taxa() -> None:

    assert format_number(Decimal("0.05"), None, key="percent") == "0,05"


def test_chave_outliers_lê_como_contagem() -> None:

    assert format_number(Decimal("3"), "currency", key="outliers") == "3"


def test_sanitizador_remove_ids_internos() -> None:

    text = (
        "O método s1 mostra customer_segmentation.segment=Varejo PF "
        "na janela reference_snapshot com trace_id: trace-1."
    )

    cleaned = sanitize_user_text(text, extra_ids=["s1", "plan", "trace-1"])

    assert "s1" not in cleaned
    assert "customer_segmentation.segment" not in cleaned
    assert "reference_snapshot" not in cleaned
    assert "trace_id" not in cleaned
    assert "trace-1" not in cleaned
    assert "Varejo PF" in cleaned
    assert "posição atual" in cleaned


def test_sanitizador_preserva_prosa_sem_ids() -> None:

    assert sanitize_user_text("Explicação do LLM.") == "Explicação do LLM."
    assert (
        sanitize_user_text("A rentabilidade do Varejo PF subiu.")
        == "A rentabilidade do Varejo PF subiu."
    )


def test_sanitizador_troca_apresentacoes_e_metodos_crus_por_rotulos() -> None:
    """Vazamento observado na UI: o planner repetiu os ids de apresentação do
    prompt ("o catálogo fechado tem apenas ranking_bar, bar..."). Tokens com
    underscore trocam sempre; palavras comuns só entre crases."""

    text = (
        "O catálogo fechado tem apenas ranking_bar (barras de ranking), `bar`, "
        "`line` e `table`; `share` e `mean` também; e cumulative_share."
    )

    cleaned = sanitize_user_text(text)

    assert cleaned == (
        "O catálogo tem apenas gráfico de ranking (barras de ranking), gráfico de "
        "barras, gráfico de linhas e tabela; participação e média também; e "
        "participação acumulada."
    )


def test_sanitizador_nao_toca_palavras_comuns_fora_de_crases() -> None:

    text = "A line de crédito, o bar da esquina, a table do relatório e o share."

    assert sanitize_user_text(text) == text


def test_ponta_a_ponta_com_id_vazando_e_numero_cru() -> None:

    leaked = (
        "O método s1 apurou 0.154632 em "
        "customer_segmentation.segment=Varejo PF no reference_snapshot."
    )

    presented = present_insight(leaked, _rate_result())

    assert "0,15" in presented
    assert "0.154632" not in presented
    assert "0,154632" not in presented
    assert "s1" not in presented
    assert "customer_segmentation.segment" not in presented
    assert "reference_snapshot" not in presented
    assert "Varejo PF" in presented


def _two_segments_result() -> AnalysisResult:

    return AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v2",
        dataset_version="2026-08-31",
        trace_id="trace-1",
        statistical_method=[
            MethodResult(
                id="s1",
                method="null",
                values=[
                    MethodValue({SEGMENT: "Varejo PF"}, {"value": Decimal("0.154632")}),
                    MethodValue({SEGMENT: "Atacado PJ"}, {"value": Decimal("0.08")}),
                ],
                unit="decimal_rate",
                rule_id="profitability",
            )
        ],
        unit="decimal_rate",
        rule_id="profitability",
    )


def test_apresentacao_preserva_markdown_com_tabela_e_negrito() -> None:
    """O insight em Markdown (negrito, lista, tabela, ressalvas) chega à UI
    intacto: só os números mudam, reescritos em pt-BR com a precisão da unidade."""

    markdown = (
        "**Varejo PF tem rentabilidade de 0.154632 nos últimos 12 meses.**\n"
        "\n"
        "- Varejo PF: 0.154632\n"
        "- Atacado PJ: 0.08\n"
        "\n"
        "| Entidade | Valor | Unidade |\n"
        "|---|---|---|\n"
        "| Varejo PF | 0.154632 | taxa |\n"
        "| Atacado PJ | 0.08 | taxa |\n"
        "\n"
        "Ressalvas: célula suprimida em 1 segmento."
    )
    expected = markdown.replace("0.154632", "0,15").replace("0.08", "0,08")

    assert present_insight(markdown, _two_segments_result()) == expected


def test_sanitizador_preserva_quebras_de_linha_e_titulos() -> None:
    """Quebras de linha são estrutura Markdown: ficam; só o excesso é reduzido."""

    text = "# Resumo\n\nLinha um.   \n\n\n\nLinha dois com s1."

    assert sanitize_user_text(text) == "# Resumo\n\nLinha um.\n\nLinha dois com."


def test_validador_aceita_arredondamento_de_exibicao() -> None:

    validate_insight_numbers("A taxa é 0,15.", _rate_result())


def test_validador_aceita_percentual_equivalente() -> None:

    validate_insight_numbers("A taxa é 12,00%.", _rate_result(Decimal("0.12")))


def test_validador_rejeita_numero_sem_lastro() -> None:

    with pytest.raises(InsightNumberError) as raised:
        validate_insight_numbers("A taxa é 99,99 e a outra 42.", _rate_result())

    assert raised.value.numbers == ("99,99", "42")
    assert "99,99" in str(raised.value)


def test_tabela_verificada_lista_entidade_periodo_metodo_valor_unidade() -> None:

    result = AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v2",
        dataset_version="2026-08-31",
        trace_id="trace-1",
        statistical_method=[
            MethodResult(
                id="s1",
                method="null",
                values=[
                    MethodValue(
                        {SEGMENT: "Varejo PF"},
                        {"value": Decimal("0.154632")},
                        None,
                        "2026-08-31",
                    ),
                    MethodValue(
                        {SEGMENT: "Atacado PJ"},
                        {},
                        UndefinedReason.SMALL_CELL,
                        "2026-08-31",
                    ),
                ],
                unit="decimal_rate",
                rule_id="profitability",
            )
        ],
    )

    table = render_verified_table(result)

    assert table.splitlines() == [
        "| Entidade | Período | Método | Valor | Unidade |",
        "| --- | --- | --- | --- | --- |",
        "| Atacado PJ | 2026-08-31 | valor | [indefinido: célula suprimida] | — |",
        "| Varejo PF | 2026-08-31 | valor | 15,46% | taxa |",
    ]


def test_tabela_verificada_escreve_taxa_pequena_como_percentual() -> None:
    """Uma taxa de 0,0034 com duas casas viraria `0,00`, um número que não
    existe no resultado; em percentual (`0,34%`) preserva a informação e o
    validador aceita a forma com `%`."""

    table = render_verified_table(_rate_result(Decimal("0.0034")))

    assert "| Varejo PF | valor | 0,34% | taxa |" in table
    assert "0,00" not in table

    validate_insight_numbers(table, _rate_result(Decimal("0.0034")))


def test_tabela_verificada_sem_periodo_omite_a_coluna_e_junta_subjects() -> None:

    result = AnalysisResult(
        analysis_plan_id="plan",
        catalog_version="v2",
        dataset_version="2026-08-31",
        trace_id="trace-1",
        statistical_method=[
            MethodResult(
                id="s1",
                method="variation",
                values=[
                    MethodValue(
                        {SEGMENT: "Varejo PF", "product.product": "Cartão"},
                        {"absolute": Decimal("1234.5"), "percent": Decimal("0.05")},
                    ),
                    MethodValue({}, {"absolute": Decimal("10"), "percent": None}),
                ],
                unit="currency",
            )
        ],
    )

    table = render_verified_table(result)

    assert table.splitlines() == [
        "| Entidade | Método | Valor | Unidade |",
        "| --- | --- | --- | --- |",
        "| Total | variação | 10,00 | moeda |",
        "| Varejo PF · Cartão | variação | absoluta 1.234,50; percentual 5,00% | moeda |",
    ]


def test_tabela_verificada_e_deterministica() -> None:

    result = _two_segments_result()

    assert render_verified_table(result) == render_verified_table(result)
    assert "15,46%" in render_verified_table(result)
    assert "8,00%" in render_verified_table(result)
    assert "0.154632" not in render_verified_table(result)


def test_validador_passaa_sem_numeros() -> None:

    validate_insight_numbers("Sem números aqui.", _rate_result())
    validate_insight_numbers("", _rate_result())


def test_validador_ignora_ano_data_e_janela() -> None:

    validate_insight_numbers(
        "Em 2026, na posição de 2026-08-31: taxa de 0,15 nos últimos 12 meses.",
        _rate_result(),
    )


def test_validador_tolera_o_limiar_de_clientes_da_ressalva() -> None:
    """ "10 clientes" é o k da regra small-cell, não um número do resultado —
    tratado como tamanho de janela, tal como "12 meses"."""

    validate_insight_numbers(
        "Células com menos de 10 clientes foram suprimidas; a taxa é 0,15.",
        _rate_result(),
    )


def test_formatador_nao_quebra_janela_em_meses() -> None:

    formatted = format_insight_numbers(
        "Nos últimos 12 meses, a taxa é 0.154632.", _rate_result()
    )

    assert "12 meses" in formatted
    assert "0,15" in formatted


def test_execute_analysis_propaga_unit_e_rule() -> None:

    plan = AnalysisPlan(
        id="plan",
        statistical_method=[
            StatisticalMethod(
                id="s1",
                method=StatisticalMethodType.NULL,
                calculation_plan_ids=["calc_prof_seg"],
            )
        ],
        operations=[
            Operation(id="o1", type=OperationType.RANKING, refs=["s1"], params={})
        ],
    )
    calculation = CalculationResult(
        calculation_plan_id="calc_prof_seg",
        rule_id="profitability",
        unit="decimal_rate",
        values=[
            CalculationResultRow(
                subjects={SEGMENT: "Varejo PF"},
                period="2026-08-31",
                value=Decimal("0.12"),
            )
        ],
    )

    result = execute_analysis(
        plan, [calculation], CATALOG, dataset_version="2026-08-31", trace_id="t1"
    )

    assert result.unit == "decimal_rate"
    assert result.rule_id == "profitability"
    assert result.statistical_method[0].unit == "decimal_rate"
    assert result.statistical_method[0].rule_id == "profitability"
    assert result.operations[0].unit == "decimal_rate"
    assert result.operations[0].rule_id == "profitability"


def test_share_produz_taxa_mesmo_de_estoque() -> None:

    plan = AnalysisPlan(
        id="plan",
        statistical_method=[
            StatisticalMethod(
                id="s1",
                method=StatisticalMethodType.SHARE,
                calculation_plan_ids=["calc_saldo"],
            )
        ],
    )
    calculation = CalculationResult(
        calculation_plan_id="calc_saldo",
        rule_id="outstanding_balance",
        unit="currency",
        values=[
            CalculationResultRow(
                subjects={SEGMENT: "Varejo PF"},
                period="2026-08-31",
                value=Decimal("100"),
            ),
            CalculationResultRow(
                subjects={SEGMENT: "Atacado PJ"},
                period="2026-08-31",
                value=Decimal("300"),
            ),
        ],
    )

    result = execute_analysis(
        plan, [calculation], CATALOG, dataset_version="2026-08-31", trace_id="t1"
    )

    assert result.statistical_method[0].unit == "decimal_rate"
    assert result.statistical_method[0].rule_id == "outstanding_balance"


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

    async def generate(self, messages, session_id: str | None = None):

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

    def execute(self, plans, *, catalog_version, snapshot_version):

        return self._results


class _Snapshot(SnapshotVersionPort):
    def current(self) -> str:

        return "2026-08-31"


class _Knowledge(KnowledgePort):
    def retrieve(self, question, *, locale, limit=5):

        return []


class _LeakingInsight(InsightPort):
    async def explain(
        self, *, question, result, excerpts=(), caveats=(), session_id=None
    ) -> str:

        return (
            "O método s1 apurou 0.154632 em "
            "customer_segmentation.segment=Varejo PF no reference_snapshot."
        )


def test_pipeline_apresenta_insight_vazado() -> None:

    pipeline = AnalysisPipeline(
        calculation=_Calculation(
            [
                CalculationResult(
                    calculation_plan_id="calc_prof_seg",
                    rule_id="profitability",
                    unit="decimal_rate",
                    values=[
                        CalculationResultRow(
                            subjects={SEGMENT: "Varejo PF"},
                            period="2026-08-31",
                            value=Decimal("0.154632"),
                        )
                    ],
                )
            ]
        ),
        snapshot_version=_Snapshot(),
        knowledge=_Knowledge(),
        insight=_LeakingInsight(),
    )
    plan = AnalysisPlan(
        id="plan",
        statistical_method=[
            StatisticalMethod(
                id="s1",
                method=StatisticalMethodType.NULL,
                calculation_plan_ids=["calc_prof_seg"],
            )
        ],
    )

    outcome = asyncio.run(
        pipeline.run(
            question="Qual a rentabilidade do Varejo PF?",
            locale="pt-BR",
            session_id="sessao-1",
            analysis_plan=plan,
            calculations=[],
            catalog=CATALOG,
        )
    )

    assert "0,15" in outcome.insight
    assert "0.154632" not in outcome.insight
    assert "s1" not in outcome.insight
    assert "customer_segmentation.segment" not in outcome.insight
    assert "reference_snapshot" not in outcome.insight
    assert "Varejo PF" in outcome.insight


def test_rota_clarify_nao_expoe_id() -> None:

    llm = _SequenceLlm(
        [
            {
                "route": "clarify",
                "clarification_question": "De qual s1 no reference_snapshot?",
            }
        ]
    )
    query = AnswerQuestionHandler(
        llm=llm,
        prompt=_Prompt(),
        reference_date=_ReferenceDate(),
        catalog=YamlSemanticCatalogAdapter(),
        auth_capacity=AuthCapacityAcl(AuthorizeQuery(YamlCapabilitiesAdapter())),
        pipeline=object(),  # type: ignore[arg-type]
    )

    contents = asyncio.run(
        query.execute(
            USER,
            ConversationContext(session_id="sessao-1", messages=[]),
            "Como estamos indo?",
        )
    )

    assert contents == [Text(text="De qual no posição atual?")]

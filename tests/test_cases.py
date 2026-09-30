"""Cobertura dos 74 cases de `data/eval/cases.md` na camada de cálculo.

Cada case recebe uma classe segundo o que o `financial_calculation` garante:

- `ACCEPTED` — o plano de cálculo do case é expressável e aceito pelo motor;
- `REJECTED` — o limite é do contrato de cálculo e o erro é tipado;
- `STRUCTURAL` — a capacidade pedida está fora do contrato de cálculo (amostra
  multivalor, negação, having, percentil);
- `ANALYSIS` — a decisão pertence à camada de análise (RAG, janela, governança,
  clarificação, valor externo) e fica fora deste teste.

A paridade numérica dos planos aceitos é validada contra o dado real no harness
`utils/validate_oracle.py` (oracle pré-computado em `data/oracle/oracle_v1.yaml`),
fora da suíte padrão.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from typing import cast

import pytest

from contexts.financial_calculation.application.commands.execute_calculation import (
    execute_calculation,
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
    SampleCondition,
    Subject,
)
from contexts.financial_calculation.domain.errors import (
    CalculationError,
    UnknownAxisError,
    UnknownRuleError,
)
from contexts.financial_calculation.domain.metric_binding import METRIC_BINDINGS
from contexts.financial_calculation.ports.outbound.official_data_repository import (
    AggregatedRow,
    MetricRequest,
    PeriodRequest,
)


class _FakeRepository:
    def fetch_aggregated(
        self,
        metric: MetricRequest,
        period: PeriodRequest,
    ) -> list[AggregatedRow]:

        return []


@dataclass(frozen=True)
class _Accepted:
    plans: tuple[CalculationPlan, ...]


# --- eixos do catálogo

SEGMENT = Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SEGMENT)
SUBSEGMENT = Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SUBSEGMENT)
PERSON_TYPE = Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.PERSON_TYPE)
PRODUCT_GROUP = Subject(type=AxisType.PRODUCT, level=AxisLevel.PRODUCT_GROUP)
PRODUCT = Subject(type=AxisType.PRODUCT, level=AxisLevel.PRODUCT)
SUBPRODUCT = Subject(type=AxisType.PRODUCT, level=AxisLevel.SUBPRODUCT)
RELATIONSHIP = Subject(
    type=AxisType.CUSTOMER_RELATIONSHIP,
    level=AxisLevel.RELATIONSHIP_DEPTH,
)
PRINCIPALITY = Subject(
    type=AxisType.CUSTOMER_PRINCIPALITY,
    level=AxisLevel.PRINCIPALITY_DEPTH,
)
TOTAL = Subject(type=AxisType.TOTAL, level=AxisLevel.TOTAL)

INDIVIDUAL = Subject(
    type=cast(AxisType, "customer"),
    level=cast(AxisLevel, "customer_id"),
)
REGION = Subject(
    type=cast(AxisType, "region"),
    level=cast(AxisLevel, "municipality"),
)

# --- recortes governados

HIGH_PRINCIPALITY = SampleCondition(
    type=AxisType.CUSTOMER_PRINCIPALITY,
    level=AxisLevel.PRINCIPALITY_DEPTH,
    value_id="high",
)
LOW_PRINCIPALITY = SampleCondition(
    type=AxisType.CUSTOMER_PRINCIPALITY,
    level=AxisLevel.PRINCIPALITY_DEPTH,
    value_id="low",
)
HIGH_RELATIONSHIP = SampleCondition(
    type=AxisType.CUSTOMER_RELATIONSHIP,
    level=AxisLevel.RELATIONSHIP_DEPTH,
    value_id="high",
)
PRIVATE = SampleCondition(
    type=AxisType.CUSTOMER_SEGMENTATION,
    level=AxisLevel.SEGMENT,
    value_id="private",
)
VAREJO_PF = SampleCondition(
    type=AxisType.CUSTOMER_SEGMENTATION,
    level=AxisLevel.SEGMENT,
    value_id="varejo_pf",
)
VAREJO_PJ = SampleCondition(
    type=AxisType.CUSTOMER_SEGMENTATION,
    level=AxisLevel.SEGMENT,
    value_id="varejo_pj",
)
CORPORATE_LARGE = SampleCondition(
    type=AxisType.CUSTOMER_SEGMENTATION,
    level=AxisLevel.SEGMENT,
    value_id="corporate_large",
)

# --- janelas (data de referência 2026-08-31)

P_3M = Period(
    start=date(2026, 6, 1),
    end=date(2026, 8, 31),
    type=PeriodType.SERIES,
    grain=Grain.MONTH,
)
P_6M = Period(
    start=date(2026, 3, 1),
    end=date(2026, 8, 31),
    type=PeriodType.SERIES,
    grain=Grain.MONTH,
)
P_6M_PREV = Period(
    start=date(2025, 9, 1),
    end=date(2026, 2, 28),
    type=PeriodType.SERIES,
    grain=Grain.MONTH,
)
P_12M = Period(
    start=date(2025, 9, 1),
    end=date(2026, 8, 31),
    type=PeriodType.SERIES,
    grain=Grain.MONTH,
)
P_12M_PREV = Period(
    start=date(2024, 9, 1),
    end=date(2025, 8, 31),
    type=PeriodType.SERIES,
    grain=Grain.MONTH,
)
P_Q_26 = Period(
    start=date(2026, 1, 1),
    end=date(2026, 8, 31),
    type=PeriodType.SERIES,
    grain=Grain.QUARTER,
)
P_YEAR_25_8M = Period(
    start=date(2025, 1, 1),
    end=date(2025, 8, 31),
    type=PeriodType.SERIES,
    grain=Grain.YEAR,
)
P_YEAR_26_8M = Period(
    start=date(2026, 1, 1),
    end=date(2026, 8, 31),
    type=PeriodType.SERIES,
    grain=Grain.YEAR,
)
S_AUG25 = Period(
    start=date(2025, 8, 31),
    end=date(2025, 8, 31),
    type=PeriodType.SNAPSHOT,
    grain=Grain.MONTH,
)
S_MAY26 = Period(
    start=date(2026, 5, 31),
    end=date(2026, 5, 31),
    type=PeriodType.SNAPSHOT,
    grain=Grain.MONTH,
)
S_AUG26 = Period(
    start=date(2026, 8, 31),
    end=date(2026, 8, 31),
    type=PeriodType.SNAPSHOT,
    grain=Grain.MONTH,
)


def _plan(
    plan_id: str,
    rule_id: RuleId,
    subjects: list[Subject],
    sample: list[SampleCondition] | None = None,
    period: Period = P_12M,
) -> CalculationPlan:

    return CalculationPlan(
        calculation_plan_id=plan_id,
        metric=Metric(rule_id=rule_id, subjects=subjects, sample=sample or []),
        period=period,
    )


def _accepted(*plans: CalculationPlan) -> _Accepted:

    return _Accepted(plans=tuple(plans))


ACCEPTED: dict[str, _Accepted] = {
    "A1": _accepted(_plan("A1", RuleId.PROFITABILITY, [SEGMENT], period=S_AUG26)),
    "A2": _accepted(_plan("A2", RuleId.PROFITABILITY, [SEGMENT], period=P_3M)),
    "A3": _accepted(_plan("A3", RuleId.PROFITABILITY, [SEGMENT])),
    "A4": _accepted(_plan("A4", RuleId.PROFITABILITY, [PRODUCT])),
    "A5": _accepted(_plan("A5", RuleId.CONTRACT_COUNT, [TOTAL], period=S_AUG26)),
    "A6": _accepted(
        _plan("A6", RuleId.CONTRACT_COUNT, [PRODUCT_GROUP], period=S_AUG26)
    ),
    "A7": _accepted(_plan("A7", RuleId.PROFITABILITY, [PERSON_TYPE])),
    "A8": _accepted(_plan("A8", RuleId.PROFITABILITY, [RELATIONSHIP])),
    "A9": _accepted(_plan("A9", RuleId.PROFITABILITY, [PRINCIPALITY])),
    "A10": _accepted(_plan("A10", RuleId.PROFITABILITY, [SEGMENT])),
    "B11": _accepted(
        _plan("B11", RuleId.PROFITABILITY, [PRODUCT], [HIGH_PRINCIPALITY])
    ),
    "B12": _accepted(_plan("B12", RuleId.PROFITABILITY, [PRODUCT], [LOW_PRINCIPALITY])),
    "B13": _accepted(
        _plan("B13", RuleId.PROFITABILITY, [SEGMENT], [HIGH_RELATIONSHIP])
    ),
    "B14": _accepted(
        _plan("B14", RuleId.CONTRACT_COUNT, [SEGMENT, PRODUCT], period=S_AUG26)
    ),
    "B15": _accepted(
        _plan(
            "B15",
            RuleId.CONTRACT_COUNT,
            [SEGMENT, PRODUCT],
            [HIGH_RELATIONSHIP],
            period=S_AUG26,
        )
    ),
    "B16": _accepted(_plan("B16", RuleId.PROFITABILITY, [SEGMENT, SUBSEGMENT])),
    "B17": _accepted(_plan("B17", RuleId.PROFITABILITY, [PRODUCT_GROUP, SUBPRODUCT])),
    "B18": _accepted(_plan("B18", RuleId.PROFITABILITY, [SEGMENT, PRODUCT])),
    "B19": _accepted(
        _plan("B19", RuleId.CONTRACT_COUNT, [PRODUCT], [PRIVATE], period=S_AUG26)
    ),
    "B20": _accepted(
        _plan("B20_varejo", RuleId.PROFITABILITY, [PRODUCT], [VAREJO_PF]),
        _plan("B20_corporate", RuleId.PROFITABILITY, [PRODUCT], [CORPORATE_LARGE]),
    ),
    "C21": _accepted(_plan("C21", RuleId.PROFITABILITY, [TOTAL], [VAREJO_PF], P_6M)),
    "C22": _accepted(_plan("C22", RuleId.PROFITABILITY, [SEGMENT], period=P_3M)),
    "C23": _accepted(_plan("C23", RuleId.PROFITABILITY, [SEGMENT], period=P_Q_26)),
    "C24": _accepted(
        _plan("C24_2025", RuleId.PROFITABILITY, [TOTAL], period=P_YEAR_25_8M),
        _plan("C24_2026", RuleId.PROFITABILITY, [TOTAL], period=P_YEAR_26_8M),
    ),
    "C25": _accepted(_plan("C25", RuleId.PROFITABILITY, [TOTAL])),
    "C26": _accepted(
        _plan("C26_2025", RuleId.PROFITABILITY, [TOTAL], period=S_AUG25),
        _plan("C26_2026", RuleId.PROFITABILITY, [TOTAL], period=S_AUG26),
    ),
    "C27": _accepted(
        _plan("C27_maio", RuleId.PROFITABILITY, [SEGMENT], period=S_MAY26),
        _plan("C27_agosto", RuleId.PROFITABILITY, [SEGMENT], period=S_AUG26),
    ),
    "C28": _accepted(
        _plan("C28_2025", RuleId.CONTRACT_COUNT, [SEGMENT], period=S_AUG25),
        _plan("C28_2026", RuleId.CONTRACT_COUNT, [SEGMENT], period=S_AUG26),
    ),
    "C29": _accepted(
        _plan("C29_antes", RuleId.PROFITABILITY, [SEGMENT], period=P_6M_PREV),
        _plan("C29_depois", RuleId.PROFITABILITY, [SEGMENT], period=P_6M),
    ),
    "C30": _accepted(_plan("C30", RuleId.PROFITABILITY, [TOTAL], [VAREJO_PJ])),
    "D31": _accepted(
        _plan("D31_contratos", RuleId.CONTRACT_COUNT, [SEGMENT], period=S_AUG26),
        _plan("D31_rentabilidade", RuleId.PROFITABILITY, [SEGMENT], period=S_AUG26),
    ),
    "D32": _accepted(
        _plan("D32_contratos", RuleId.CONTRACT_COUNT, [SEGMENT], period=S_AUG26),
        _plan("D32_rentabilidade", RuleId.PROFITABILITY, [SEGMENT], period=S_AUG26),
    ),
    "D33": _accepted(_plan("D33", RuleId.PROFITABILITY, [RELATIONSHIP])),
    "D34": _accepted(
        _plan("D34_vinculacao", RuleId.PROFITABILITY, [RELATIONSHIP]),
        _plan("D34_principalidade", RuleId.PROFITABILITY, [PRINCIPALITY]),
    ),
    "D36": _accepted(
        _plan("D36", RuleId.OUTSTANDING_BALANCE, [SEGMENT], period=S_AUG26)
    ),
    "D37": _accepted(
        _plan("D37", RuleId.OUTSTANDING_BALANCE, [SEGMENT], period=S_AUG26)
    ),
    "D39": _accepted(_plan("D39", RuleId.CONTRACT_COUNT, [PRODUCT], period=S_AUG26)),
    "D40": _accepted(
        _plan("D40_base", RuleId.PROFITABILITY, [SEGMENT], period=P_12M_PREV),
        _plan("D40_atual", RuleId.PROFITABILITY, [SEGMENT], period=P_12M),
        _plan(
            "D40_carteira",
            RuleId.OUTSTANDING_BALANCE,
            [SEGMENT],
            period=P_12M_PREV,
        ),
    ),
    "E41": _accepted(
        _plan(
            "E41",
            RuleId.PROFITABILITY,
            [SEGMENT],
            [HIGH_PRINCIPALITY, HIGH_RELATIONSHIP],
        )
    ),
    "E46": _accepted(_plan("E46", RuleId.PROFITABILITY, [PRODUCT])),
    "G63": _accepted(
        _plan("G63_antes", RuleId.PROFITABILITY, [TOTAL], [VAREJO_PF], P_12M_PREV),
        _plan("G63_depois", RuleId.PROFITABILITY, [TOTAL], [VAREJO_PF], P_12M),
    ),
}

REJECTED: dict[str, tuple[type[CalculationError], CalculationPlan, str]] = {
    "D35": (
        UnknownRuleError,
        _plan(
            "D35",
            cast(RuleId, "profitability_per_contract"),
            [PRODUCT],
        ),
        "métrica derivada (razão entre métricas) não existe no registry",
    ),
    "D38": (
        UnknownRuleError,
        _plan("D38", cast(RuleId, "profitability_unweighted"), [SEGMENT]),
        "média simples de taxas não é oferecida; a ponderação é da family",
    ),
    "E47": (
        UnknownAxisError,
        _plan("E47", RuleId.CUSTOMER_COUNT, [INDIVIDUAL], period=S_AUG26),
        "grão de cliente individual bloqueado por construção",
    ),
    "G55": (
        UnknownAxisError,
        _plan("G55", RuleId.PROFITABILITY, [INDIVIDUAL], period=S_AUG26),
        "grão individual + PII",
    ),
    "G56": (
        UnknownAxisError,
        _plan("G56", RuleId.CUSTOMER_COUNT, [INDIVIDUAL], period=S_AUG26),
        "PII",
    ),
    "G58": (
        UnknownRuleError,
        _plan("G58", cast(RuleId, "captacao"), [SEGMENT]),
        "métrica fora do catálogo",
    ),
    "G60": (
        UnknownRuleError,
        _plan("G60", cast(RuleId, "credit_origination"), [TOTAL], period=P_3M),
        "fluxo: o MVP modela estoque",
    ),
    "G61": (
        UnknownRuleError,
        _plan(
            "G61",
            cast(RuleId, "contract_termination_count"),
            [SEGMENT],
            period=P_3M,
        ),
        "encerramento é fluxo",
    ),
    "G62": (
        UnknownRuleError,
        _plan(
            "G62",
            cast(RuleId, "contract_margin_recalculation"),
            [TOTAL],
            period=S_AUG26,
        ),
        "recálculo de valor oficial (source-owned)",
    ),
    "G64": (
        UnknownAxisError,
        _plan("G64", RuleId.PROFITABILITY, [REGION]),
        "dimensão inexistente no modelo",
    ),
}

STRUCTURAL: dict[str, str] = {
    "E42": "multivalor / IN não representável: uma igualdade por condição",
    "E43": "negação não representável",
    "E44": "amostra por valor de métrica (having) não representável",
    "E45": "having não representável",
    "E48": "percentil como população exige grão individual, que não existe",
}

ANALYSIS: dict[str, str] = {
    "F49": "RAG puro (documental)",
    "F50": "RAG puro (documental)",
    "F51": "RAG puro (documental)",
    "F52": "matriz_seg_prod é dado estruturado de governança",
    "F53": "RAG puro (documental)",
    "F54": "metadado do catálogo, não do fato",
    "G57": "projeção: futuro fora de escopo (rota refuse)",
    "G59": "fora da janela de 24 meses (rota refuse)",
    "H65": "ambíguo: clarificar",
    "H66": "ambíguo: clarificar",
    "H67": "ambíguo: clarificar",
    "H68": "ambíguo: clarificar",
    "H69": "ambíguo: clarificar",
    "I70": "valor de referência externo (meta)",
    "I71": "valor de referência externo (orçamento)",
    "I72": "benchmark externo",
    "I73": "período nomeado vindo de documento",
    "I74": "previsão: rota refuse",
}

ALL_BLOCKS = sorted(list(ACCEPTED) + list(REJECTED) + list(STRUCTURAL) + list(ANALYSIS))

EXPECTED_CASES = (
    [f"A{i}" for i in range(1, 11)]
    + [f"B{i}" for i in range(11, 21)]
    + [f"C{i}" for i in range(21, 31)]
    + [f"D{i}" for i in range(31, 41)]
    + [f"E{i}" for i in range(41, 49)]
    + [f"F{i}" for i in range(49, 55)]
    + [f"G{i}" for i in range(55, 65)]
    + [f"H{i}" for i in range(65, 70)]
    + [f"I{i}" for i in range(70, 75)]
)


def test_matriz_cobre_os_74_cases() -> None:

    assert set(ALL_BLOCKS) == set(EXPECTED_CASES)
    assert len(ALL_BLOCKS) == 74


def test_classificacao_por_camada() -> None:

    assert len(ACCEPTED) == 41
    assert len(REJECTED) == 10
    assert len(STRUCTURAL) == 5
    assert len(ANALYSIS) == 18


@pytest.mark.parametrize("case_id", sorted(ACCEPTED))
def test_case_de_calculo_e_aceito(case_id: str) -> None:

    accepted = ACCEPTED[case_id]

    results = [execute_calculation(plan, _FakeRepository()) for plan in accepted.plans]

    assert [result.calculation_plan_id for result in results] == [
        plan.calculation_plan_id for plan in accepted.plans
    ]


@pytest.mark.parametrize("case_id", sorted(REJECTED))
def test_case_de_calculo_e_recusado_com_erro_tipado(case_id: str) -> None:

    error, plan, _reason = REJECTED[case_id]

    with pytest.raises(error):
        execute_calculation(plan, _FakeRepository())


def test_amostra_nao_expressa_multivalor_negacao_having_ou_percentil() -> None:

    assert {field.name for field in fields(SampleCondition)} == {
        "type",
        "level",
        "value_id",
    }
    assert sorted(STRUCTURAL) == ["E42", "E43", "E44", "E45", "E48"]


def test_nao_existe_grao_de_cliente_individual() -> None:

    assert {axis.value for axis in AxisType} == {
        "customer_segmentation",
        "customer_relationship",
        "customer_principality",
        "product",
        "total",
    }


def test_rentabilidade_so_existe_ponderada() -> None:

    binding = METRIC_BINDINGS[RuleId.PROFITABILITY]

    assert binding.aggregation.kind == "ratio"
    assert binding.aggregation.numerator == "vl_margem"
    assert binding.aggregation.denominator == "vl_saldo"


def test_cases_de_analise_estao_explicitos() -> None:

    assert sorted(ANALYSIS) == sorted(
        [
            "F49",
            "F50",
            "F51",
            "F52",
            "F53",
            "F54",
            "G57",
            "G59",
            "H65",
            "H66",
            "H67",
            "H68",
            "H69",
            "I70",
            "I71",
            "I72",
            "I73",
            "I74",
        ]
    )
    assert all(reason for reason in ANALYSIS.values())

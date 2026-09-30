"""`validate_plan`: o pacote vira garantia — ou recusa tipificada.

Mesma entrada, mesma saída. O teste cobre as oito verificações e os motivos da
taxonomia.
"""

from __future__ import annotations

from datetime import date
from typing import cast

import pytest

from contexts.auth.domain.capabilities import UserCapabilities
from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    Operation,
    OperationType,
    Presentation,
    PresentationAxis,
    PresentationType,
    StatisticalMethod,
    StatisticalMethodType,
)
from contexts.financial_analysis.domain.errors import PlanValidationError
from contexts.financial_analysis.domain.interpretation import RefusalReason
from contexts.financial_analysis.domain.services.validate_plan import (
    validate_plan,
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
    InvalidPeriodError,
    InvalidPlanError,
    UnknownAxisError,
)

CATALOG = YamlSemanticCatalogAdapter().load_active()

ALL = UserCapabilities(
    can_use_financial_analysis=True,
    metrics=frozenset(
        {
            "profitability",
            "outstanding_balance",
            "contract_count",
            "customer_count",
            "cdi_rate",
            "selic_rate",
            "inflation_ipca",
        }
    ),
    axes=frozenset(entry.key for entry in CATALOG.axes),
)

SEGMENT = Subject(type=AxisType.CUSTOMER_SEGMENTATION, level=AxisLevel.SEGMENT)
RELATIONSHIP = Subject(
    type=AxisType.CUSTOMER_RELATIONSHIP, level=AxisLevel.RELATIONSHIP_DEPTH
)
TOTAL = Subject(type=AxisType.TOTAL, level=AxisLevel.TOTAL)

SERIES_12M = Period(
    start=date(2025, 9, 1),
    end=date(2026, 8, 31),
    type=PeriodType.SERIES,
    grain=Grain.MONTH,
)
TOTAL_12M = Period(
    start=date(2025, 9, 1),
    end=date(2026, 8, 31),
    type=PeriodType.SERIES,
    grain=Grain.TOTAL,
)
SNAPSHOT_AUG25 = Period(
    start=date(2025, 8, 31),
    end=date(2025, 8, 31),
    type=PeriodType.SNAPSHOT,
    grain=Grain.MONTH,
)
SNAPSHOT_AUG26 = Period(
    start=date(2026, 8, 31),
    end=date(2026, 8, 31),
    type=PeriodType.SNAPSHOT,
    grain=Grain.MONTH,
)


def _plan(
    plan_id: str,
    *,
    rule: RuleId = RuleId.PROFITABILITY,
    subjects: list[Subject] | None = None,
    sample: list[SampleCondition] | None = None,
    period: Period = SERIES_12M,
) -> CalculationPlan:

    return CalculationPlan(
        calculation_plan_id=plan_id,
        metric=Metric(
            rule_id=rule,
            subjects=subjects or [SEGMENT],
            sample=list(sample or []),
        ),
        period=period,
    )


def _method(
    method_id: str,
    method: StatisticalMethodType,
    *,
    calculation_plan_ids: list[str] | None = None,
    statistic_refs: list[str] | None = None,
) -> StatisticalMethod:

    return StatisticalMethod(
        id=method_id,
        method=method,
        calculation_plan_ids=list(calculation_plan_ids or []),
        statistic_refs=list(statistic_refs or []),
    )


def _analysis(
    methods: list[StatisticalMethod],
    operations: list[Operation] | None = None,
) -> AnalysisPlan:

    return AnalysisPlan(
        id="plan",
        statistical_method=methods,
        operations=list(operations or []),
    )


def _assert_refused(
    reason: RefusalReason,
    analysis: AnalysisPlan,
    calculations: list[CalculationPlan],
    capabilities: UserCapabilities = ALL,
) -> None:

    with pytest.raises(PlanValidationError) as error:
        validate_plan(analysis, calculations, CATALOG, capabilities)

    assert error.value.reason is reason


def test_pacote_valido_e_selado() -> None:

    calculations = [_plan("calc_prof_seg")]
    analysis = _analysis(
        [
            _method(
                "s1", StatisticalMethodType.STD, calculation_plan_ids=["calc_prof_seg"]
            )
        ],
        [
            Operation(
                id="o1",
                type=OperationType.RANKING,
                refs=["s1"],
                params={"order": "desc", "axis": "entity"},
            )
        ],
    )

    validated = validate_plan(analysis, calculations, CATALOG, ALL)

    assert validated.catalog_version == "v3"
    assert validated.calculations[0].calculation_plan_id == "calc_prof_seg"


def test_media_de_taxas_e_recusada() -> None:

    calculations = [_plan("calc_prof_seg")]
    analysis = _analysis(
        [
            _method(
                "s1", StatisticalMethodType.MEAN, calculation_plan_ids=["calc_prof_seg"]
            )
        ]
    )

    _assert_refused(RefusalReason.NOT_EXPRESSIBLE, analysis, calculations)


def test_dispersion_de_taxas_e_recusada() -> None:
    calculations = [_plan("calc_prof_seg")]
    analysis = _analysis(
        [
            _method(
                "s1",
                StatisticalMethodType.DISPERSION,
                calculation_plan_ids=["calc_prof_seg"],
            )
        ]
    )

    _assert_refused(RefusalReason.NOT_EXPRESSIBLE, analysis, calculations)


def test_share_de_razao_e_recusado() -> None:
    calculations = [_plan("calc_prof_seg")]
    analysis = _analysis(
        [
            _method(
                "s1",
                StatisticalMethodType.SHARE,
                calculation_plan_ids=["calc_prof_seg"],
            )
        ]
    )

    _assert_refused(RefusalReason.NOT_EXPRESSIBLE, analysis, calculations)


def test_share_de_estoque_colapsado_e_aprovado() -> None:
    calculations = [
        _plan(
            "calc_bal_seg",
            rule=RuleId.OUTSTANDING_BALANCE,
            period=TOTAL_12M,
        )
    ]
    analysis = _analysis(
        [
            _method(
                "s1",
                StatisticalMethodType.SHARE,
                calculation_plan_ids=["calc_bal_seg"],
            )
        ]
    )

    validate_plan(analysis, calculations, CATALOG, ALL)


def test_variation_com_janelas_sobrepostas_e_invalid_window() -> None:
    calculations = [
        _plan(
            "calc_a",
            period=Period(
                start=date(2026, 1, 1),
                end=date(2026, 8, 31),
                type=PeriodType.SERIES,
                grain=Grain.TOTAL,
            ),
        ),
        _plan(
            "calc_b",
            period=Period(
                start=date(2026, 5, 1),
                end=date(2026, 12, 31),
                type=PeriodType.SERIES,
                grain=Grain.TOTAL,
            ),
        ),
    ]
    analysis = _analysis(
        [
            _method(
                "s1",
                StatisticalMethodType.VARIATION,
                calculation_plan_ids=["calc_a", "calc_b"],
            )
        ]
    )

    _assert_refused(RefusalReason.INVALID_WINDOW, analysis, calculations)


def test_variation_com_duracoes_diferentes_e_invalid_window() -> None:
    calculations = [
        _plan(
            "calc_a",
            period=Period(
                start=date(2025, 9, 1),
                end=date(2025, 11, 30),
                type=PeriodType.SERIES,
                grain=Grain.TOTAL,
            ),
        ),
        _plan(
            "calc_b",
            period=Period(
                start=date(2025, 12, 1),
                end=date(2026, 8, 31),
                type=PeriodType.SERIES,
                grain=Grain.TOTAL,
            ),
        ),
    ]
    analysis = _analysis(
        [
            _method(
                "s1",
                StatisticalMethodType.VARIATION,
                calculation_plan_ids=["calc_a", "calc_b"],
            )
        ]
    )

    _assert_refused(RefusalReason.INVALID_WINDOW, analysis, calculations)


def test_variation_serie_nao_colapsada_e_recusada() -> None:
    calculations = [
        _plan(
            "calc_a",
            period=Period(
                start=date(2024, 9, 1),
                end=date(2025, 8, 31),
                type=PeriodType.SERIES,
                grain=Grain.MONTH,
            ),
        ),
        _plan("calc_b", period=SERIES_12M),
    ]
    analysis = _analysis(
        [
            _method(
                "s1",
                StatisticalMethodType.VARIATION,
                calculation_plan_ids=["calc_a", "calc_b"],
            )
        ]
    )

    _assert_refused(RefusalReason.NOT_EXPRESSIBLE, analysis, calculations)


def test_variation_yoy_aceita_intervalo_entre_janelas() -> None:
    calculations = [
        _plan("calc_2025", subjects=[TOTAL], period=SNAPSHOT_AUG25),
        _plan("calc_2026", subjects=[TOTAL], period=SNAPSHOT_AUG26),
    ]
    analysis = _analysis(
        [
            _method(
                "s1",
                StatisticalMethodType.VARIATION,
                calculation_plan_ids=["calc_2025", "calc_2026"],
            )
        ]
    )

    validate_plan(analysis, calculations, CATALOG, ALL)


def test_metrica_fora_do_catalogo_e_catalog_miss() -> None:
    calculations = [_plan("calc_x", rule=cast(RuleId, "captacao"))]
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_x"])]
    )

    _assert_refused(RefusalReason.CATALOG_MISS, analysis, calculations)


def test_eixo_fora_do_catalogo_e_catalog_miss() -> None:
    calculations = [
        _plan(
            "calc_x",
            subjects=[
                Subject(
                    type=AxisType.CUSTOMER_SEGMENTATION,
                    level=cast(AxisLevel, "municipality"),
                )
            ],
        )
    ]
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_x"])]
    )

    _assert_refused(RefusalReason.CATALOG_MISS, analysis, calculations)


def test_valor_fora_do_eixo_e_catalog_miss() -> None:
    calculations = [
        _plan(
            "calc_x",
            subjects=[Subject(type=AxisType.PRODUCT, level=AxisLevel.PRODUCT)],
            sample=[
                SampleCondition(
                    type=AxisType.CUSTOMER_SEGMENTATION,
                    level=AxisLevel.SEGMENT,
                    value_id="agencia",
                )
            ],
        )
    ]
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_x"])]
    )

    _assert_refused(RefusalReason.CATALOG_MISS, analysis, calculations)


def test_data_fora_da_janela_e_out_of_window() -> None:
    calculations = [
        _plan(
            "calc_x",
            period=Period(
                start=date(2023, 9, 1),
                end=date(2024, 8, 31),
                type=PeriodType.SERIES,
                grain=Grain.MONTH,
            ),
        )
    ]
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_x"])]
    )

    _assert_refused(RefusalReason.OUT_OF_WINDOW, analysis, calculations)


def test_metrica_sem_capacidade_e_unauthorized() -> None:

    capabilities = UserCapabilities(
        can_use_financial_analysis=True,
        metrics=frozenset({"outstanding_balance"}),
        axes=ALL.axes,
    )
    calculations = [_plan("calc_prof_seg")]
    analysis = _analysis(
        [
            _method(
                "s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_prof_seg"]
            )
        ]
    )

    _assert_refused(RefusalReason.UNAUTHORIZED, analysis, calculations, capabilities)


def test_eixo_sem_capacidade_e_unauthorized() -> None:

    capabilities = UserCapabilities(
        can_use_financial_analysis=True,
        metrics=ALL.metrics,
        axes=frozenset({"product.product"}),
    )
    calculations = [_plan("calc_prof_seg")]
    analysis = _analysis(
        [
            _method(
                "s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_prof_seg"]
            )
        ]
    )

    _assert_refused(RefusalReason.UNAUTHORIZED, analysis, calculations, capabilities)


def test_metrica_orfa_e_recusada() -> None:
    calculations = [_plan("calc_a"), _plan("calc_b")]
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_a"])]
    )

    _assert_refused(RefusalReason.NOT_EXPRESSIBLE, analysis, calculations)


def test_ranking_sem_axis_e_recusado() -> None:
    calculations = [_plan("calc_a")]
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_a"])],
        [
            Operation(
                id="o1",
                type=OperationType.RANKING,
                refs=["s1"],
                params={"order": "desc"},
            )
        ],
    )

    _assert_refused(RefusalReason.NOT_EXPRESSIBLE, analysis, calculations)


def test_decomposition_exige_variation_e_share() -> None:
    calculations = [_plan("calc_a")]
    analysis = _analysis(
        [
            _method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_a"]),
            _method(
                "s2",
                StatisticalMethodType.NULL,
                calculation_plan_ids=["calc_a"],
            ),
        ],
        [
            Operation(
                id="o1",
                type=OperationType.DECOMPOSITION,
                refs=["s1", "s2"],
            )
        ],
    )

    _assert_refused(RefusalReason.NOT_EXPRESSIBLE, analysis, calculations)


def test_correlation_exige_dois_metodos() -> None:
    calculations = [_plan("calc_a")]
    analysis = _analysis(
        [
            _method("s1", StatisticalMethodType.STD, calculation_plan_ids=["calc_a"]),
            _method("s2", StatisticalMethodType.CORRELATION, statistic_refs=["s1"]),
        ]
    )

    _assert_refused(RefusalReason.NOT_EXPRESSIBLE, analysis, calculations)


def test_trend_ordinal_com_tres_niveis_e_aprovado() -> None:
    calculations = [_plan("calc_rel", subjects=[RELATIONSHIP], period=TOTAL_12M)]
    analysis = _analysis(
        [
            _method(
                "s1",
                StatisticalMethodType.TREND,
                calculation_plan_ids=["calc_rel"],
            )
        ]
    )

    validate_plan(analysis, calculations, CATALOG, ALL)


def test_trend_em_eixo_nominal_e_recusado() -> None:
    calculations = [_plan("calc_prof_seg", period=TOTAL_12M)]
    analysis = _analysis(
        [
            _method(
                "s1",
                StatisticalMethodType.TREND,
                calculation_plan_ids=["calc_prof_seg"],
            )
        ]
    )

    _assert_refused(RefusalReason.NOT_EXPRESSIBLE, analysis, calculations)


def test_snapshot_com_datas_diferentes_e_recusado() -> None:
    """A forma do período é invariante do value object: um snapshot com datas
    diferentes nem chega a virar CalculationPlan para o validate_plan ver."""

    with pytest.raises(InvalidPeriodError):
        Period(
            start=date(2026, 1, 1),
            end=date(2026, 8, 31),
            type=PeriodType.SNAPSHOT,
            grain=Grain.MONTH,
        )


def test_periodo_invertido_e_recusado_pelo_value_object() -> None:

    with pytest.raises(InvalidPeriodError):
        Period(
            start=date(2026, 8, 31),
            end=date(2026, 1, 1),
            type=PeriodType.SERIES,
            grain=Grain.MONTH,
        )


def test_total_com_outra_quebra_e_recusado_pelo_value_object() -> None:

    with pytest.raises(InvalidPlanError):
        Metric(rule_id=RuleId.PROFITABILITY, subjects=[TOTAL, SEGMENT])


def test_recorte_que_repete_quebra_e_recusado_pelo_value_object() -> None:

    with pytest.raises(UnknownAxisError):
        Metric(
            rule_id=RuleId.PROFITABILITY,
            subjects=[SEGMENT],
            sample=[
                SampleCondition(
                    type=AxisType.CUSTOMER_SEGMENTATION,
                    level=AxisLevel.SEGMENT,
                    value_id="varejo_pf",
                )
            ],
        )


def test_metrica_macro_aceita_total_colapsado() -> None:

    calculations = [
        _plan("calc_cdi", rule=RuleId.CDI_RATE, subjects=[TOTAL], period=TOTAL_12M)
    ]
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_cdi"])]
    )

    validated = validate_plan(analysis, calculations, CATALOG, ALL)

    assert validated.calculations[0].metric.rule_id is RuleId.CDI_RATE


def test_metrica_macro_com_eixo_de_negocio_e_not_expressible() -> None:

    calculations = [_plan("calc_cdi", rule=RuleId.CDI_RATE, subjects=[SEGMENT])]
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_cdi"])]
    )

    _assert_refused(RefusalReason.NOT_EXPRESSIBLE, analysis, calculations)


def test_metrica_macro_com_eixo_ordinal_e_not_expressible() -> None:

    calculations = [_plan("calc_cdi", rule=RuleId.CDI_RATE, subjects=[RELATIONSHIP])]
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_cdi"])]
    )

    _assert_refused(RefusalReason.NOT_EXPRESSIBLE, analysis, calculations)


def test_metrica_macro_com_sample_e_not_expressible() -> None:

    calculations = [
        _plan(
            "calc_cdi",
            rule=RuleId.CDI_RATE,
            subjects=[TOTAL],
            sample=[
                SampleCondition(
                    type=AxisType.CUSTOMER_PRINCIPALITY,
                    level=AxisLevel.PRINCIPALITY_DEPTH,
                    value_id="high",
                )
            ],
        )
    ]
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_cdi"])]
    )

    _assert_refused(RefusalReason.NOT_EXPRESSIBLE, analysis, calculations)


def test_metrica_macro_sem_capacidade_e_unauthorized() -> None:

    capabilities = UserCapabilities(
        can_use_financial_analysis=True,
        metrics=frozenset({"profitability"}),
        axes=ALL.axes,
    )
    calculations = [
        _plan("calc_cdi", rule=RuleId.CDI_RATE, subjects=[TOTAL], period=TOTAL_12M)
    ]
    analysis = _analysis(
        [_method("s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_cdi"])]
    )

    _assert_refused(RefusalReason.UNAUTHORIZED, analysis, calculations, capabilities)


def test_presentation_compativel_e_preservada_no_plano_selado() -> None:

    calculations = [_plan("calc_prof_seg")]
    presentation = Presentation(
        type=PresentationType.BAR,
        axis=PresentationAxis.ENTITY,
        title="Rentabilidade por segmento",
    )
    analysis = AnalysisPlan(
        id="plan",
        statistical_method=[
            _method(
                "s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_prof_seg"]
            )
        ],
        presentation=presentation,
    )

    validated = validate_plan(analysis, calculations, CATALOG, ALL)

    assert validated.analysis_plan.presentation == presentation


def test_line_sem_serie_degrada_para_table() -> None:

    calculations = [_plan("calc_prof_seg", period=SNAPSHOT_AUG26)]
    analysis = AnalysisPlan(
        id="plan",
        statistical_method=[
            _method(
                "s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_prof_seg"]
            )
        ],
        presentation=Presentation(
            type=PresentationType.LINE,
            axis=PresentationAxis.PERIOD,
            title="Evolução",
        ),
    )

    validated = validate_plan(analysis, calculations, CATALOG, ALL)

    assert validated.analysis_plan.presentation == Presentation()
    assert validated.analysis_plan.presentation is not None
    assert validated.analysis_plan.presentation.type is PresentationType.TABLE


def test_ranking_bar_sem_ranking_degrada_para_table() -> None:

    calculations = [_plan("calc_prof_seg")]
    analysis = AnalysisPlan(
        id="plan",
        statistical_method=[
            _method(
                "s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_prof_seg"]
            )
        ],
        presentation=Presentation(
            type=PresentationType.RANKING_BAR,
            axis=PresentationAxis.ENTITY,
        ),
    )

    validated = validate_plan(analysis, calculations, CATALOG, ALL)

    assert validated.analysis_plan.presentation == Presentation()


def test_ranking_bar_com_ranking_e_preservada() -> None:

    calculations = [_plan("calc_prof_seg")]
    presentation = Presentation(
        type=PresentationType.RANKING_BAR,
        axis=PresentationAxis.ENTITY,
        title="Ranking de rentabilidade",
    )
    analysis = AnalysisPlan(
        id="plan",
        statistical_method=[
            _method(
                "s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_prof_seg"]
            )
        ],
        operations=[
            Operation(
                id="o1",
                type=OperationType.RANKING,
                refs=["s1"],
                params={"order": "desc", "axis": "entity"},
            )
        ],
        presentation=presentation,
    )

    validated = validate_plan(analysis, calculations, CATALOG, ALL)

    assert validated.analysis_plan.presentation == presentation


def test_bar_de_total_sem_entidade_degrada_para_table() -> None:

    calculations = [_plan("calc_prof_total", subjects=[TOTAL])]
    analysis = AnalysisPlan(
        id="plan",
        statistical_method=[
            _method(
                "s1",
                StatisticalMethodType.NULL,
                calculation_plan_ids=["calc_prof_total"],
            )
        ],
        presentation=Presentation(
            type=PresentationType.BAR, axis=PresentationAxis.ENTITY
        ),
    )

    validated = validate_plan(analysis, calculations, CATALOG, ALL)

    assert validated.analysis_plan.presentation == Presentation()


def test_bar_de_periodo_com_serie_e_preservada() -> None:

    calculations = [_plan("calc_prof_seg")]
    presentation = Presentation(
        type=PresentationType.BAR,
        axis=PresentationAxis.PERIOD,
        title="Rentabilidade mês a mês",
    )
    analysis = AnalysisPlan(
        id="plan",
        statistical_method=[
            _method(
                "s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_prof_seg"]
            )
        ],
        presentation=presentation,
    )

    validated = validate_plan(analysis, calculations, CATALOG, ALL)

    assert validated.analysis_plan.presentation == presentation


def test_sem_presentation_o_plano_selado_nao_ganha_uma() -> None:

    calculations = [_plan("calc_prof_seg")]
    analysis = _analysis(
        [
            _method(
                "s1", StatisticalMethodType.NULL, calculation_plan_ids=["calc_prof_seg"]
            )
        ]
    )

    validated = validate_plan(analysis, calculations, CATALOG, ALL)

    assert validated.analysis_plan.presentation is None

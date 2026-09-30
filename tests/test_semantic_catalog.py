"""O catálogo tipado: pertencimento, forma e compatibilidade.

O prompt e a validação consomem o MESMO objeto. Este teste fixa o que a v3
declara, para que `validate_plan` não precise ler regra de nenhum outro lugar,
e que a v2 continua compilável e imutável (sem as métricas macro).
"""

from __future__ import annotations

import pytest

from contexts.financial_analysis.adapters.outbound.localized_interpretation_prompt import (
    LocalizedInterpretationPromptAdapter,
)
from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.domain.errors import InvalidCatalogError
from contexts.financial_analysis.domain.semantic_catalog import (
    CompatibilitySource,
    MetricShape,
    Requirement,
    SameField,
    WindowRequirement,
)


def _catalog():
    return YamlSemanticCatalogAdapter().load_active()


def test_versao_ativa_e_a_v3() -> None:

    assert _catalog().catalog_version == "v3"


def test_versao_fixada_satisfaz_replay() -> None:

    adapter = YamlSemanticCatalogAdapter()

    assert adapter.load("v3") == adapter.load_active()


def test_v2_continua_imutavel_e_sem_metricas_macro() -> None:

    v2 = YamlSemanticCatalogAdapter().load("v2")

    assert v2.catalog_version == "v2"
    assert v2.metric("cdi_rate") is None
    assert v2.method_rule("trend").synonyms == ()


def test_versao_legada_nao_e_compilada() -> None:

    with pytest.raises(InvalidCatalogError, match="legado"):
        YamlSemanticCatalogAdapter().load("v1")


def test_versao_inexistente_recusa() -> None:

    with pytest.raises(InvalidCatalogError, match="não encontrado"):
        YamlSemanticCatalogAdapter().load("v9")


def test_metricas_tem_forma_e_unidade() -> None:

    catalog = _catalog()

    assert catalog.metric("profitability").shape is MetricShape.RATIO
    assert catalog.metric("outstanding_balance").shape is MetricShape.STOCK
    assert catalog.metric("contract_count").shape is MetricShape.COUNT
    assert catalog.metric("captacao") is None


def test_eixos_cobrem_os_niveis_dos_casos() -> None:

    catalog = _catalog()

    assert catalog.axis("customer_segmentation", "person_type") is not None
    assert catalog.axis("customer_segmentation", "subsegment") is not None
    assert catalog.axis("product", "subproduct") is not None
    assert catalog.axis("total", "total") is not None
    assert catalog.is_ordinal("customer_relationship", "relationship_depth") is True
    assert catalog.is_ordinal("customer_segmentation", "segment") is False


def test_valor_pertence_ao_eixo_da_versao() -> None:

    catalog = _catalog()

    assert catalog.value("customer_segmentation", "segment", "varejo_pj") is not None
    assert (
        catalog.value("customer_principality", "principality_depth", "high") is not None
    )
    assert catalog.value("customer_segmentation", "segment", "agencia") is None
    assert catalog.value("product", "product_group", "cartao") is None


def test_ratio_proibe_media_e_dispersion() -> None:

    catalog = _catalog()

    mean = catalog.method_rule("mean")

    assert MetricShape.RATIO in mean.forbids_metric_shape
    assert Requirement.SERIES in mean.requires
    assert MetricShape.RATIO in catalog.method_rule("dispersion").forbids_metric_shape
    assert catalog.method_rule("distribution") is None


def test_variation_exige_dois_planos_colapsados() -> None:

    variation = _catalog().method_rule("variation")

    assert variation.reads is CompatibilitySource.CALCULATION_PLAN_IDS
    assert variation.count == 2
    assert Requirement.COLLAPSED_RESULT in variation.requires
    assert SameField.SUBJECTS in variation.same
    assert variation.windows is WindowRequirement.DISJOINT_EQUAL_DURATION


def test_correlation_e_pearson_com_entidades() -> None:

    correlation = _catalog().method_rule("correlation")

    assert correlation.reads is CompatibilitySource.STATISTIC_REFS
    assert correlation.min_points == 3
    assert SameField.SUBJECTS in correlation.same


def test_trend_aceita_serie_ou_ordinal_com_tres_niveis() -> None:

    trend = _catalog().method_rule("trend")

    assert Requirement.SERIES in trend.requires_any
    assert Requirement.ORDINAL_AXIS in trend.requires_any
    assert trend.min_levels == 3


def test_decomposition_e_operacao_que_le_variation_e_share() -> None:

    catalog = _catalog()

    assert catalog.method_rule("decomposition") is None

    decomposition = catalog.operation_rule("decomposition")

    assert decomposition.count == 2
    assert decomposition.requires_source == ("variation", "share")


def test_ranking_exige_axis() -> None:

    assert "axis" in _catalog().operation_rule("ranking").requires_params


def test_selection_proibe_media_em_ratio() -> None:

    selection = _catalog().operation_rule("selection")

    assert selection.forbidden_rules_metric_shape["above_mean"] is MetricShape.RATIO
    assert selection.forbidden_rules_metric_shape["below_mean"] is MetricShape.RATIO


def test_metricas_macro_do_mercado_tem_forma_unidade_e_sinonimos() -> None:

    catalog = _catalog()

    assert catalog.metric("profitability").macro is False

    cdi = catalog.metric("cdi_rate")
    selic = catalog.metric("selic_rate")
    ipca = catalog.metric("inflation_ipca")

    for entry in (cdi, selic, ipca):
        assert entry.shape is MetricShape.RATIO
        assert entry.unit == "decimal_rate"
        assert entry.macro is True

    assert cdi.synonyms == ("cdi", "taxa cdi")
    assert "selic" in selic.synonyms
    assert "juros básicos" in selic.synonyms
    assert ipca.synonyms == ("ipca", "inflação")


def test_todos_os_metodos_tem_sinonimos_no_catalogo_ativo() -> None:

    catalog = _catalog()

    for rule in catalog.methods:
        assert rule.synonyms, f"método '{rule.method}' sem sinônimos na v3"

    assert catalog.method_rule("trend").synonyms[:3] == (
        "tendência",
        "regressão",
        "reta de tendência",
    )
    assert "volatilidade" in catalog.method_rule("std").synonyms
    assert {"participação", "peso", "concentração"} <= set(
        catalog.method_rule("share").synonyms
    )


def test_prompt_do_planner_renderiza_sinonimos_e_macro() -> None:

    prompt = LocalizedInterpretationPromptAdapter().build_system_prompt("pt-BR")

    assert "sinônimos" in prompt
    assert "regressão" in prompt
    assert "volatilidade" in prompt
    assert "apenas `total.total`, sem recorte de negócio" in prompt

"""Invariantes arquiteturais que cruzam módulos.

Cada asserção aqui falha se um contrato de governança for quebrado: catálogo
fechado, ratio sem média, plano sem campo físico e resultado com procedência.
"""

from __future__ import annotations

from dataclasses import fields

from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.domain.analysis_plan import (
    OperationType,
    StatisticalMethodType,
)
from contexts.financial_analysis.domain.analysis_result import AnalysisResult
from contexts.financial_analysis.domain.semantic_catalog import MetricShape
from contexts.financial_calculation.domain.calculation_plan import (
    CalculationPlan,
    Metric,
    Period,
    SampleCondition,
    Subject,
)

CATALOG = YamlSemanticCatalogAdapter().load_active()

_PHYSICAL_FIELDS = {
    "ds_segm",
    "ds_segm_agrup",
    "ds_subsegm",
    "ds_subsegm_agrup",
    "ds_produto",
    "ds_subproduto",
    "ds_grupo_prod",
    "tp_pess",
    "principalidade_score",
    "vinculacao_score",
    "id_cliente",
    "id_contrato",
    "cpf_cnpj",
}


def test_catalogo_de_metodos_e_operacoes_e_fechado() -> None:

    assert {entry.value for entry in StatisticalMethodType} == {
        entry.method for entry in CATALOG.methods
    }
    assert {entry.value for entry in OperationType} == {
        entry.operation for entry in CATALOG.operations
    }


def test_distribution_saiu_e_decomposition_e_operacao() -> None:

    methods = {entry.value for entry in StatisticalMethodType}
    operations = {entry.value for entry in OperationType}

    assert "distribution" not in methods
    assert "decomposition" not in methods
    assert "decomposition" in operations


def test_ratio_proibe_media_dispersion_e_selection_por_media() -> None:

    mean = CATALOG.method_rule("mean")
    dispersion = CATALOG.method_rule("dispersion")
    selection = CATALOG.operation_rule("selection")

    assert MetricShape.RATIO in mean.forbids_metric_shape
    assert MetricShape.RATIO in dispersion.forbids_metric_shape
    assert selection.forbidden_rules_metric_shape["above_mean"] is MetricShape.RATIO
    assert selection.forbidden_rules_metric_shape["below_mean"] is MetricShape.RATIO


def test_plano_nao_carrega_campo_fisico() -> None:

    names = {
        field.name
        for dataclass in (CalculationPlan, Metric, Subject, SampleCondition, Period)
        for field in fields(dataclass)
    }

    assert not names & _PHYSICAL_FIELDS


def test_resultado_carrega_procedencia() -> None:

    names = {field.name for field in fields(AnalysisResult)}

    assert {"catalog_version", "dataset_version", "trace_id"} <= names

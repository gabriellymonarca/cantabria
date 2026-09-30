"""Compilação do adapter: pushdown, eixos, recorte e ausência.

Testar a compilação sem banco prova que a agregação é empurrada para o banco
(pushdown) e que a regra de negócio fica fora da infraestrutura. A paridade com
um ClickHouse real é validada em `test_clickhouse_parity.py`.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from contexts.financial_calculation.adapters.outbound.clickhouse_official_data import (
    DIMENSION_EXPRESSIONS,
    _map_rows,
    _to_number,
    compile_query,
)
from contexts.financial_calculation.domain.calculation_plan import (
    AxisLevel,
    AxisType,
    RuleId,
)
from contexts.financial_calculation.domain.errors import (
    UnknownAxisError,
    UnknownValueError,
)
from contexts.financial_calculation.domain.metric_binding import METRIC_BINDINGS
from contexts.financial_calculation.ports.outbound.official_data_repository import (
    MetricRequest,
    PeriodRequest,
    SampleConditionRequest,
    SubjectRequest,
)


def _request(rule_id: RuleId, subjects=(), sample=()) -> MetricRequest:

    binding = METRIC_BINDINGS[rule_id]

    return MetricRequest(
        rule_id=rule_id,
        unit=binding.unit,
        aggregation=binding.aggregation,
        temporal_behavior=binding.temporal_behavior,
        subjects=tuple(subjects),
        sample=tuple(sample),
    )


def _segment() -> SubjectRequest:
    return SubjectRequest("customer_segmentation", "segment")


PRODUCT_AXES = sorted(axis for axis in DIMENSION_EXPRESSIONS if axis[0] == "product")


def test_rentabilidade_de_cliente_empurra_agregacao() -> None:

    metric = _request(RuleId.PROFITABILITY, [_segment()])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-05-31", "2026-08-31", "series", "month"),
        "cantabria",
    )

    assert "fato_rentabilidade_cliente" in compiled.sql
    assert "fato_rentabilidade_contrato_produto" not in compiled.sql
    assert "SUM(r.vl_margem)" in compiled.sql
    assert "SUM(r.vl_saldo)" in compiled.sql
    assert "LEFT JOIN agg" in compiled.sql
    assert "arrayJoin({buckets:Array(Date)})" in compiled.sql
    assert compiled.component_names == ("numerator", "denominator", "population")


def test_eixo_de_produto_le_o_grao_item() -> None:

    metric = _request(RuleId.PROFITABILITY, [SubjectRequest("product", "product")])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-01", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert "fato_rentabilidade_contrato_produto" in compiled.sql
    assert "dim_produto" in compiled.sql
    assert "fato_rentabilidade_cliente" not in compiled.sql


def test_estoque_no_grao_usa_leitura_do_fim_e_nao_soma() -> None:

    metric = _request(RuleId.OUTSTANDING_BALANCE, [SubjectRequest("total", "total")])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-05-31", "2026-08-31", "series", "quarter"),
        "cantabria",
    )

    assert "argMax(sum_saldo, month) AS last_saldo" in compiled.sql
    assert "SELECT 1 AS _g" in compiled.sql
    assert compiled.component_names == ("value", "population")


def test_estoque_no_grao_total_conta_clientes_do_ultimo_mes() -> None:
    """O valor de estoque é a leitura do último mês do bucket; a população que
    julga o k = 10 tem de ser a desse MESMO mês, não a união dos meses."""

    metric = _request(RuleId.OUTSTANDING_BALANCE, [SubjectRequest("total", "total")])
    compiled = compile_query(
        metric,
        PeriodRequest("2025-09-01", "2026-08-31", "series", "total"),
        "cantabria",
    )

    assert "uniqExact(r.id_cliente) AS month_customers" in compiled.sql
    assert "argMax(month_customers, month) AS last_population" in compiled.sql
    assert "a.last_population AS v0_population" in compiled.sql
    assert "uniqExactMerge(customers_state) AS v0_population" not in compiled.sql
    assert "a.population AS v0_population" not in compiled.sql


def test_estoque_por_produto_conta_clientes_do_ultimo_mes() -> None:

    metric = _request(
        RuleId.OUTSTANDING_BALANCE, [SubjectRequest("product", "product_group")]
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-01-01", "2026-12-31", "series", "quarter"),
        "cantabria",
    )

    assert "uniqExact(c.id_cliente) AS month_customers" in compiled.sql
    assert "a.last_population AS v0_population" in compiled.sql


def test_ratio_no_grao_total_funde_clientes_do_bucket() -> None:
    """Para razão (Σnum/Σden sobre o bucket) a população correta é a união dos
    clientes distintos de todos os meses — o `-Merge` fica."""

    metric = _request(RuleId.PROFITABILITY, [SubjectRequest("total", "total")])
    compiled = compile_query(
        metric,
        PeriodRequest("2025-09-01", "2026-08-31", "series", "total"),
        "cantabria",
    )

    assert "uniqExactMerge(customers_state) AS population" in compiled.sql
    assert "a.population AS v0_population" in compiled.sql
    assert "last_population AS v0_population" not in compiled.sql


def test_grao_total_colapsa_a_janela_num_bucket() -> None:

    metric = _request(RuleId.PROFITABILITY, [_segment()])
    compiled = compile_query(
        metric,
        PeriodRequest("2025-09-01", "2026-08-31", "series", "total"),
        "cantabria",
    )

    assert compiled.params["buckets"] == [dt.date(2026, 8, 31)]
    assert "{end:Date} AS bucket" in compiled.sql
    assert "toStartOfMonth(r.mes_ref) AS month" in compiled.sql
    assert "SUM(sum_margem) AS total_margem" in compiled.sql


def test_grao_total_sem_eixo_mantem_chave_de_join() -> None:
    """No grão total o rótulo do bucket é a constante {end:Date}; o lado do
    LEFT JOIN tem de ser a coluna b.ref, senão o ClickHouse não acha chave
    de junção (INVALID_JOIN_ON_EXPRESSION)."""

    metric = _request(RuleId.PROFITABILITY, [SubjectRequest("total", "total")])
    compiled = compile_query(
        metric,
        PeriodRequest("2025-01-01", "2025-12-31", "series", "total"),
        "cantabria",
    )

    assert "LEFT JOIN agg AS a ON a.bucket = b.ref" in compiled.sql
    assert "a.bucket = {end:Date}" not in compiled.sql


def test_contagem_snapshot_usa_contratos_ativos() -> None:

    metric = _request(RuleId.CONTRACT_COUNT, [_segment()])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert compiled.params["buckets"] == [dt.date(2026, 8, 31)]
    assert "uniqExact(c.id_contrato)" in compiled.sql
    assert "c.dt_ini_contrato <= b.ref" in compiled.sql
    assert "c.dt_encerramento >= b.ref" in compiled.sql


def test_contagem_por_produto_entra_pelo_item() -> None:

    metric = _request(RuleId.CONTRACT_COUNT, [SubjectRequest("product", "product")])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert "fato_contrato_produtos AS cp" in compiled.sql
    assert "dim_produto AS dp" in compiled.sql
    assert "fato_rentabilidade" not in compiled.sql


def test_contagem_de_clientes_usa_chave_de_cliente() -> None:

    metric = _request(RuleId.CUSTOMER_COUNT, [_segment()])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert "uniqExact(c.id_cliente)" in compiled.sql
    assert "fato_cliente AS dc" in compiled.sql


def test_recorte_de_principalidade_vira_faixa_de_score() -> None:

    metric = _request(
        RuleId.PROFITABILITY,
        [SubjectRequest("product", "product")],
        [SampleConditionRequest("customer_principality", "principality_depth", "high")],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-01", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert "principalidade_score >= 70" in compiled.sql
    assert "filter_0" not in compiled.params


def test_recorte_de_vinculacao_media_vira_faixa_de_score() -> None:

    metric = _request(
        RuleId.PROFITABILITY,
        [_segment()],
        [
            SampleConditionRequest(
                "customer_relationship", "relationship_depth", "medium"
            )
        ],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-01", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert "vinculacao_score >= 40" in compiled.sql
    assert "vinculacao_score < 70" in compiled.sql


def test_recorte_de_segmento_traduz_valor_fisico() -> None:

    metric = _request(
        RuleId.PROFITABILITY,
        [_segment()],
        [SampleConditionRequest("customer_segmentation", "segment", "varejo_pf")],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-01", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert compiled.params["filter_0"] == "Varejo PF"
    assert "dc.ds_segm = {filter_0:String}" in compiled.sql


def test_grupos_governados_nao_somem_com_o_recorte() -> None:

    metric = _request(
        RuleId.PROFITABILITY,
        [_segment()],
        [SampleConditionRequest("customer_segmentation", "segment", "varejo_pf")],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-01", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    groups_cte = compiled.sql.split("groups AS (")[1].split("),\nmonthly")[0]

    assert "filter_0" not in groups_cte
    assert "filter_0" in compiled.sql


def test_produto_com_recorte_de_cliente_faz_join_de_cliente() -> None:

    metric = _request(
        RuleId.PROFITABILITY,
        [SubjectRequest("product", "product")],
        [SampleConditionRequest("customer_segmentation", "segment", "private")],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-01", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert "fato_rentabilidade_contrato_produto" in compiled.sql
    assert "JOIN cantabria.fato_cliente AS dc" in compiled.sql


def test_serie_mensal_gera_um_bucket_por_mes() -> None:

    metric = _request(RuleId.PROFITABILITY, [_segment()])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-05-31", "2026-08-31", "series", "month"),
        "cantabria",
    )

    assert compiled.params["buckets"] == [
        dt.date(2026, 5, 31),
        dt.date(2026, 6, 30),
        dt.date(2026, 7, 31),
        dt.date(2026, 8, 31),
    ]


def test_total_nao_produz_dimensao_nula() -> None:

    metric = _request(RuleId.PROFITABILITY, [SubjectRequest("total", "total")])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-01", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    rows = _map_rows(
        compiled,
        [(dt.date(2026, 8, 31), Decimal("130.00"), Decimal("1000.00"), 42)],
    )

    assert len(rows) == 1
    assert rows[0].subjects == {}
    assert rows[0].components == {
        "numerator": Decimal("130.00"),
        "denominator": Decimal("1000.00"),
        "population": 42,
    }


def test_ausencia_vira_componente_nulo() -> None:

    metric = _request(RuleId.PROFITABILITY, [_segment()])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-01", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    rows = _map_rows(compiled, [("Varejo PF", dt.date(2026, 8, 31), None, None, None)])

    assert rows[0].subjects == {"customer_segmentation.segment": "Varejo PF"}
    assert rows[0].period == "2026-08-31"
    assert rows[0].components == {
        "numerator": None,
        "denominator": None,
        "population": None,
    }


def test_profundidade_e_agrupada_por_faixa() -> None:

    metric = _request(
        RuleId.PROFITABILITY,
        [SubjectRequest("customer_principality", "principality_depth")],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-01", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert "multiIf(dc.principalidade_score >= 70, 'alta'" in compiled.sql
    assert compiled.axes[0].key == "customer_principality.principality_depth"


@pytest.mark.parametrize(("axis_type", "level"), sorted(DIMENSION_EXPRESSIONS))
def test_todo_eixo_do_catalogo_compila(axis_type: str, level: str) -> None:

    metric = _request(RuleId.PROFITABILITY, [SubjectRequest(axis_type, level)])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-01", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert compiled.axes[0].key == f"{axis_type}.{level}"
    assert compiled.axes[0].alias == "d0"
    assert "fato_rentabilidade" in compiled.sql


@pytest.mark.parametrize(("axis_type", "level"), sorted(PRODUCT_AXES))
def test_todo_eixo_de_produto_le_a_tabela_item(axis_type: str, level: str) -> None:

    metric = _request(RuleId.OUTSTANDING_BALANCE, [SubjectRequest(axis_type, level)])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert "fato_rentabilidade_contrato_produto" in compiled.sql


def test_grao_anual_gera_bucket_do_fim_do_ano() -> None:

    metric = _request(RuleId.PROFITABILITY, [_segment()])
    compiled = compile_query(
        metric, PeriodRequest("2024-09-30", "2026-08-31", "series", "year"), "cantabria"
    )

    assert compiled.params["buckets"] == [
        dt.date(2024, 12, 31),
        dt.date(2025, 12, 31),
        dt.date(2026, 12, 31),
    ]


def test_grao_trimestral_alinha_buckets_ao_trimestre() -> None:

    metric = _request(RuleId.PROFITABILITY, [_segment()])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-01-01", "2026-08-31", "series", "quarter"),
        "cantabria",
    )

    assert compiled.params["buckets"] == [
        dt.date(2026, 3, 31),
        dt.date(2026, 6, 30),
        dt.date(2026, 9, 30),
    ]


def test_serie_de_uma_data_gera_um_bucket() -> None:

    metric = _request(RuleId.PROFITABILITY, [_segment()])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "series", "month"),
        "cantabria",
    )

    assert compiled.params["buckets"] == [dt.date(2026, 8, 31)]


def test_multiplas_condicoes_de_recorte_somam_em_and() -> None:

    metric = _request(
        RuleId.PROFITABILITY,
        [_segment()],
        [
            SampleConditionRequest(
                "customer_principality", "principality_depth", "high"
            ),
            SampleConditionRequest(
                "customer_relationship", "relationship_depth", "high"
            ),
        ],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert "principalidade_score >= 70" in compiled.sql
    assert "vinculacao_score >= 70" in compiled.sql


def test_recorte_de_pessoa_fisica_usa_valor_fisico() -> None:

    metric = _request(
        RuleId.PROFITABILITY,
        [_segment()],
        [SampleConditionRequest("customer_segmentation", "person_type", "F")],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert compiled.params["filter_0"] == "F"
    assert "dc.tp_pess = {filter_0:String}" in compiled.sql


def test_recorte_de_produto_em_contagem_de_clientes() -> None:

    metric = _request(
        RuleId.CUSTOMER_COUNT,
        [_segment()],
        [SampleConditionRequest("product", "product_group", "rotativo")],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert "fato_contrato_produtos AS cp" in compiled.sql
    assert "uniqExact(c.id_cliente)" in compiled.sql
    assert compiled.params["filter_0"] == "Crédito Rotativo"


def test_contagem_com_recorte_de_cliente_e_produto() -> None:

    metric = _request(
        RuleId.CONTRACT_COUNT,
        [_segment()],
        [
            SampleConditionRequest("customer_segmentation", "segment", "private"),
            SampleConditionRequest("product", "product_group", "consignado"),
        ],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert "fato_contrato_produtos AS cp" in compiled.sql
    assert "dim_produto AS dp" in compiled.sql
    assert "fato_cliente AS dc" in compiled.sql
    assert compiled.params["filter_0"] == "Private"
    assert compiled.params["filter_1"] == "Crédito Consignado"


@pytest.mark.parametrize(
    ("value_id", "physical"),
    [
        ("varejo_pf", "Varejo PF"),
        ("varejo_pj", "Varejo PJ"),
        ("varejo_rural", "Varejo Rural"),
        ("private", "Private"),
        ("corporate_middle", "Corporate Middle"),
        ("corporate_large", "Corporate Large"),
        ("cib", "CIB"),
    ],
)
def test_segmentos_do_dado_tem_traducao_fisica(value_id: str, physical: str) -> None:

    metric = _request(
        RuleId.PROFITABILITY,
        [_segment()],
        [SampleConditionRequest("customer_segmentation", "segment", value_id)],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert compiled.params["filter_0"] == physical


def test_valor_de_recorte_vai_como_parametro_nunca_inline() -> None:

    injection = "X'; DROP TABLE fato_cliente; --"

    metric = _request(
        RuleId.PROFITABILITY,
        [_segment()],
        [SampleConditionRequest("customer_segmentation", "segment", injection)],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert "DROP TABLE" not in compiled.sql
    assert compiled.params["filter_0"] == injection


def test_recorte_de_profundidade_com_valor_invalido_e_recusado_pelo_adapter() -> None:

    metric = _request(
        RuleId.PROFITABILITY,
        [_segment()],
        [
            SampleConditionRequest(
                "customer_principality", "principality_depth", "hacker"
            )
        ],
    )

    with pytest.raises(UnknownValueError):
        compile_query(
            metric,
            PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
            "cantabria",
        )


def test_map_rows_converte_contagem_ausente() -> None:

    metric = _request(RuleId.CONTRACT_COUNT, [_segment()])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    rows = _map_rows(compiled, [("Varejo PF", dt.date(2026, 8, 31), None, None)])

    assert rows[0].components == {"value": None, "population": None}


def test_map_rows_le_population_como_inteiro() -> None:

    metric = _request(RuleId.CONTRACT_COUNT, [_segment()])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    rows = _map_rows(compiled, [("Varejo PF", dt.date(2026, 8, 31), 120, 37)])

    assert rows[0].components == {"value": 120, "population": 37}


@pytest.mark.parametrize(
    ("rule_id", "subject"),
    [
        (RuleId.PROFITABILITY, SubjectRequest("customer_segmentation", "segment")),
        (RuleId.PROFITABILITY, SubjectRequest("product", "product")),
        (RuleId.OUTSTANDING_BALANCE, SubjectRequest("total", "total")),
        (RuleId.OUTSTANDING_BALANCE, SubjectRequest("product", "product_group")),
        (RuleId.CONTRACT_COUNT, SubjectRequest("customer_segmentation", "segment")),
        (RuleId.CUSTOMER_COUNT, SubjectRequest("product", "product")),
    ],
)
def test_toda_familia_devolve_population_por_uniqexact(rule_id, subject) -> None:
    """Small-cell (k = 10) só é possível se TODO caminho físico contar clientes
    distintos por grupo/período; a chave física fica no adapter."""

    metric = _request(rule_id, [subject])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-05-31", "2026-08-31", "series", "month"),
        "cantabria",
    )

    assert "uniqExact" in compiled.sql
    assert "id_cliente" in compiled.sql
    assert "AS population" in compiled.sql
    assert compiled.component_names[-1] == "population"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (Decimal("1.50"), Decimal("1.50")),
        (7, 7),
        (1.25, Decimal("1.25")),
        ("4.75", Decimal("4.75")),
    ],
)
def test_to_number_normaliza_tipos(value, expected) -> None:

    assert _to_number(value) == expected


def test_dois_subjects_viram_duas_colunas_de_group_by() -> None:

    metric = _request(
        RuleId.PROFITABILITY,
        [
            SubjectRequest("customer_segmentation", "segment"),
            SubjectRequest("product", "product"),
        ],
    )
    compiled = compile_query(
        metric,
        PeriodRequest("2026-08-31", "2026-08-31", "snapshot", "month"),
        "cantabria",
    )

    assert [axis.alias for axis in compiled.axes] == ["d0", "d1"]
    assert [axis.key for axis in compiled.axes] == [
        "customer_segmentation.segment",
        "product.product",
    ]
    assert "GROUP BY bucket, month, d0, d1" in compiled.sql


def test_plano_nao_carrega_campo_fisico() -> None:

    vocabulary = {axis.value for axis in AxisType} | {
        level.value for level in AxisLevel
    }
    physical = {
        "ds_segm",
        "ds_segm_agrup",
        "ds_subsegm",
        "ds_grupo_prod",
        "ds_produto",
        "ds_subproduto",
        "principalidade_score",
        "vinculacao_score",
        "vl_saldo",
        "vl_margem",
        "id_cliente",
        "id_contrato",
    }

    assert vocabulary.isdisjoint(physical)


def test_ratio_nao_usa_media_de_taxas_no_sql() -> None:

    metric = _request(RuleId.PROFITABILITY, [_segment()])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-06-01", "2026-08-31", "series", "quarter"),
        "cantabria",
    )

    assert "avg(" not in compiled.sql.lower()
    assert "SUM(sum_margem)" in compiled.sql
    assert "SUM(sum_saldo)" in compiled.sql


def test_mercado_agrega_taxas_mensais_do_bucket_no_banco() -> None:
    """O banco devolve as taxas do bucket (`groupArray`); a composição e a
    anualização ficam no kernel puro, nunca no SQL (sem avg/exp/log)."""

    metric = _request(RuleId.CDI_RATE, [SubjectRequest("total", "total")])
    compiled = compile_query(
        metric,
        PeriodRequest("2025-09-01", "2026-08-31", "series", "total"),
        "cantabria",
    )

    assert "mercado_indicadores" in compiled.sql
    assert "groupArray(m.taxa) AS rates" in compiled.sql
    assert compiled.params["indicador"] == "cdi"
    assert compiled.component_names == ("rates",)
    assert "{end:Date} AS bucket" in compiled.sql
    assert "LEFT JOIN monthly AS a ON a.bucket = b.ref" in compiled.sql
    assert compiled.params["buckets"] == [dt.date(2026, 8, 31)]
    assert "avg(" not in compiled.sql.lower()
    assert "exp(" not in compiled.sql.lower()
    assert "log(" not in compiled.sql.lower()


def test_mercado_serie_mensal_alinha_bucket_ao_mes() -> None:
    metric = _request(RuleId.INFLATION_IPCA, [SubjectRequest("total", "total")])
    compiled = compile_query(
        metric,
        PeriodRequest("2026-06-01", "2026-08-31", "series", "month"),
        "cantabria",
    )

    assert compiled.params["indicador"] == "ipca"
    assert "toStartOfMonth(m.mes_ref) AS bucket" in compiled.sql
    assert "LEFT JOIN monthly AS a ON a.bucket = toStartOfMonth(b.ref)" in compiled.sql
    assert "AND m.mes_ref >= toStartOfMonth({start:Date})" in compiled.sql
    assert compiled.params["buckets"] == [
        dt.date(2026, 6, 30),
        dt.date(2026, 7, 31),
        dt.date(2026, 8, 31),
    ]


def test_mercado_rejeita_eixo_de_negocio_no_adapter() -> None:
    """`validate_plan` e o motor já recusam; o adapter não compila o recorte."""

    metric = _request(RuleId.CDI_RATE, [_segment()])

    with pytest.raises(UnknownAxisError):
        compile_query(
            metric,
            PeriodRequest("2025-09-01", "2026-08-31", "series", "total"),
            "cantabria",
        )


def test_mercado_mapeia_array_de_taxas_para_decimal() -> None:
    metric = _request(RuleId.SELIC_RATE, [SubjectRequest("total", "total")])
    compiled = compile_query(
        metric,
        PeriodRequest("2025-09-01", "2026-08-31", "series", "total"),
        "cantabria",
    )

    rows = _map_rows(
        compiled,
        [(dt.date(2026, 8, 31), [Decimal("0.01"), Decimal("0.02")])],
    )

    assert rows[0].subjects == {}
    assert rows[0].components == {"rates": (Decimal("0.01"), Decimal("0.02"))}


def test_mercado_ausente_vira_componente_nulo() -> None:
    metric = _request(RuleId.CDI_RATE, [SubjectRequest("total", "total")])
    compiled = compile_query(
        metric,
        PeriodRequest("2025-09-01", "2026-08-31", "series", "total"),
        "cantabria",
    )

    rows = _map_rows(compiled, [(dt.date(2026, 8, 31), None)])

    assert rows[0].components == {"rates": None}

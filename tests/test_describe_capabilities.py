"""O gerador de capacidades lê o catálogo.

A descrição é determinística e sem números de dados: métricas pelos sinônimos,
recortes pelos eixos, métodos/operações com rótulo de negócio, formatos de
saída e a faixa de janelas do próprio catálogo. Os starters da tela inicial
derivam da mesma fonte.
"""

from __future__ import annotations

from datetime import date

from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_analysis.domain.semantic_catalog import (
    AxisEntry,
    AxisKind,
    MethodCompatibility,
    MetricEntry,
    MetricShape,
    OperationCompatibility,
    SemanticCatalog,
    WindowEntry,
)
from contexts.financial_analysis.domain.services.describe_capabilities import (
    describe_capabilities,
    starter_questions,
)


def _active_catalog() -> SemanticCatalog:

    return YamlSemanticCatalogAdapter().load_active()


def test_descricao_cita_metricas_eixos_metodos_e_operacoes_do_catalogo_ativo() -> None:

    text = describe_capabilities(_active_catalog()).lower()

    for term in ("rentabilidade", "carteira", "contratos", "clientes"):
        assert term in text

    for term in ("segmento", "vinculação", "principalidade", "produto", "subproduto"):
        assert term in text

    for term in ("tendência", "participação", "correlação", "outliers", "ranking"):
        assert term in text


def test_descricao_traz_a_faixa_de_janelas_do_catalogo() -> None:

    text = describe_capabilities(_active_catalog())

    assert "set/2024" in text
    assert "ago/2026" in text
    assert "últimos 12 meses" in text


def test_metodo_identidade_nao_aparece_como_analise() -> None:

    text = describe_capabilities(_active_catalog())

    assert "null" not in text


def test_rotulos_desconhecidos_caem_no_id_legivel_e_eixo_sem_nome_fica_fora() -> None:

    catalog = SemanticCatalog(
        catalog_version="v9",
        locale="pt-BR",
        reference_date=date(2026, 8, 31),
        window_start=date(2024, 9, 1),
        window_end=date(2026, 8, 31),
        metrics=(
            MetricEntry(
                rule_id="market_rate",
                shape=MetricShape.RATIO,
                unit="decimal_rate",
            ),
        ),
        axes=(AxisEntry(type="total", level="total", kind=AxisKind.NOMINAL),),
        windows=(
            WindowEntry(
                id="last_month",
                kind="trailing_months",
                type="series",
                grain="month",
                labels=("último mês",),
            ),
        ),
        methods=(MethodCompatibility(method="spread"),),
        operations=(OperationCompatibility(operation="custom_op"),),
    )

    text = describe_capabilities(catalog).lower()

    assert "market rate" in text
    assert "spread" in text
    assert "custom op" in text
    assert "recortes por" not in text


def test_descricao_lista_os_formatos_de_saida_sem_id_de_apresentacao() -> None:

    text = describe_capabilities(_active_catalog())

    assert (
        "- Formatos: texto, tabela, gráfico de barras, gráfico de linhas e ranking"
        in text
    )
    assert "ranking_bar" not in text
    assert "_" not in text


def test_starters_vem_do_catalogo_ativo_com_rotulo_e_pergunta_completa() -> None:

    starters = starter_questions(_active_catalog())

    assert starters == (
        (
            "Segmento mais rentável",
            "Qual o segmento mais rentável nos últimos 12 meses?",
        ),
        ("Evolução da carteira", "Como evoluiu a carteira nos últimos 6 meses?"),
        ("Rentabilidade × CDI", "Compare a rentabilidade com o CDI em 2026"),
        ("O que você faz?", "O que você sabe fazer?"),
    )


def test_starter_do_cdi_so_existe_quando_a_metrica_esta_no_catalogo() -> None:

    catalog = SemanticCatalog(
        catalog_version="v9",
        locale="pt-BR",
        reference_date=date(2026, 8, 31),
        window_start=date(2024, 9, 1),
        window_end=date(2026, 8, 31),
        metrics=(
            MetricEntry(
                rule_id="profitability",
                shape=MetricShape.RATIO,
                unit="decimal_rate",
                synonyms=("rentabilidade",),
            ),
        ),
        axes=(
            AxisEntry(
                type="customer_segmentation",
                level="segment",
                kind=AxisKind.NOMINAL,
                synonyms=("segmento",),
            ),
        ),
    )

    labels = [label for label, _ in starter_questions(catalog)]

    assert labels == ["Segmento mais rentável", "O que você faz?"]

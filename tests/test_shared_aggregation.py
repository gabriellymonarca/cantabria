"""Invariantes dos operadores puros (shared.aggregation).

Aqui vive a semântica que o adapter compila para SQL. Testar o operador puro é
mais forte que testar um exemplo: define o que precisa valer para QUALQUER
entrada. A paridade com o ClickHouse é verificada em test_clickhouse_parity.py.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import assume, given
from hypothesis import strategies as st

from shared.aggregation import (
    annualize_rate,
    compound_annualized_rate,
    compound_rate,
    count_distinct,
    latest,
    ratio,
    sum_values,
)

MONEY = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1000000000000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
RATE = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)


@given(num=MONEY, den=MONEY)
def test_ratio_com_denominador_zero_e_ausencia(num: Decimal, den: Decimal) -> None:
    """Denominador zero devolve None — nunca 0.0 (número plausível e falso)."""

    if den == 0:
        assert ratio(num, den) is None
    else:
        assert ratio(num, den) == num / den


@given(values=st.lists(MONEY, max_size=60))
def test_soma_e_exata_e_independente_de_ordem(values: list[Decimal]) -> None:
    assert sum_values(values) == sum(values, Decimal(0))
    assert sum_values(values) == sum_values(list(reversed(values)))


@given(saldo_a=MONEY, saldo_b=MONEY, taxa_a=RATE, taxa_b=RATE)
def test_ratio_nao_e_media_de_taxas(
    saldo_a: Decimal, saldo_b: Decimal, taxa_a: Decimal, taxa_b: Decimal
) -> None:
    """Re-derivar Σmargem/Σsaldo NÃO é a média das taxas quando o saldo varia."""

    assume(saldo_a != saldo_b)
    assume(taxa_a != taxa_b)
    assume(saldo_a + saldo_b != 0)

    margem_a = saldo_a * taxa_a
    margem_b = saldo_b * taxa_b

    ponderado = ratio(margem_a + margem_b, saldo_a + saldo_b)
    media_taxas = (taxa_a + taxa_b) / 2

    assert ponderado is not None
    assert ponderado != media_taxas


@given(meses=st.lists(MONEY, min_size=2, max_size=12))
def test_estoque_nao_soma_entre_periodos(meses: list[Decimal]) -> None:
    """Estoque é a leitura do período mais recente, nunca a soma dos meses."""

    by_period = {f"2026-{index + 1:02d}-28": value for index, value in enumerate(meses)}
    assume(sum(1 for value in meses if value != 0) >= 2)

    assert latest(by_period) == meses[-1]
    assert latest(by_period) != sum_values(meses)


@given(chaves=st.lists(st.text(min_size=1, max_size=4), max_size=40))
def test_count_distinct(chaves: list[str]) -> None:
    assert count_distinct(chaves) == len(set(chaves))


POSITIVE_RATE = st.decimals(
    min_value=Decimal("0.000001"),
    max_value=Decimal("0.1"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)


def test_composto_conhecido_e_produto_dos_fatores() -> None:
    """1% e 2% compõem 3,02%: fatores multiplicados, nunca somados."""

    assert compound_rate([Decimal("0.01"), Decimal("0.02")]) == Decimal("0.0302")
    assert compound_rate([Decimal("0.01"), Decimal("0.02")]) == (
        Decimal("1.01") * Decimal("1.02") - 1
    )


def test_composto_vazio_e_ausencia_nunca_zero() -> None:
    assert compound_rate([]) is None
    assert compound_annualized_rate([]) is None


def test_composto_nunca_e_soma_nem_media() -> None:
    rates = [Decimal("0.10"), Decimal("0.10")]

    assert compound_rate(rates) == Decimal("0.21")
    assert compound_rate(rates) != sum_values(rates)
    assert compound_rate(rates) != sum(rates, Decimal(0)) / 2


def test_composto_com_ipca_negativo() -> None:
    rates = [Decimal("0.0044"), Decimal("-0.0032")]

    assert compound_rate(rates) == Decimal("1.0044") * Decimal("0.9968") - 1


def test_anualizacao_de_doze_meses_e_o_ponto_fixo() -> None:
    effective = Decimal("0.126825030131969720661201")

    assert annualize_rate(effective, 12) == effective


def test_anualizacao_de_um_mes_usa_doze_periodos() -> None:
    assert annualize_rate(Decimal("0.01"), 1) == Decimal("1.01") ** 12 - 1
    assert compound_annualized_rate([Decimal("0.01")]) == Decimal("1.01") ** 12 - 1


def test_anualizacao_de_tres_meses_usa_quatro_periodos() -> None:
    effective = compound_rate([Decimal("0.01")] * 3)

    assert compound_annualized_rate([Decimal("0.01")] * 3) == (
        (Decimal(1) + effective) ** 4 - 1
    )


def test_anualizacao_de_janela_de_doze_meses_iguala_o_composto() -> None:
    rates = [Decimal("0.01"), Decimal("0.02"), Decimal("-0.005")] * 4

    assert compound_annualized_rate(rates) == compound_rate(rates)


def test_anualizacao_de_base_nao_positiva_ou_janela_vazia_e_ausencia() -> None:
    assert annualize_rate(Decimal("-1"), 1) is None
    assert annualize_rate(Decimal("-1.5"), 1) is None
    assert annualize_rate(None, 12) is None
    assert annualize_rate(Decimal("0.01"), 0) is None


@given(rates=st.lists(RATE, min_size=1, max_size=24))
def test_composto_e_o_produto_dos_fatores(rates: list[Decimal]) -> None:
    product = Decimal(1)

    for factor in sorted(Decimal(1) + rate for rate in rates):
        product *= factor

    assert compound_rate(rates) == product - 1


@given(rates=st.lists(RATE, min_size=1, max_size=24))
def test_composto_independe_da_ordem_da_fonte(rates: list[Decimal]) -> None:
    """A ordem que o armazém devolve não pode mudar o último dígito."""

    assert compound_rate(rates) == compound_rate(list(reversed(rates)))
    assert compound_rate(rates) == compound_rate(sorted(rates))


@given(rates=st.lists(RATE, min_size=12, max_size=12))
def test_composto_de_doze_meses_e_idempotente_na_anualizacao(
    rates: list[Decimal],
) -> None:
    assert compound_annualized_rate(rates) == compound_rate(rates)


@given(rates=st.lists(POSITIVE_RATE, min_size=2, max_size=12))
def test_composto_supera_a_soma_para_taxas_positivas(rates: list[Decimal]) -> None:
    assert compound_rate(rates) > sum_values(rates)

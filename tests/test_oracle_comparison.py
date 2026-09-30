"""Igualdade numérica com tolerância (1e-9).

Ausência nunca equivale a número; entre números, a diferença precisa caber na
tolerância. O oracle congela os esperados com 12 casas e o motor divide em
Decimal com 28 dígitos: a distância entre os dois fica ordens de grandeza
abaixo de 1e-9, e este teste fixa exatamente essa fronteira.
"""

from __future__ import annotations

from decimal import Decimal

from shared.comparison import numbers_equal, parse_expected, parse_tolerance

TOLERANCE = Decimal("1e-9")


def test_ausencia_so_e_igual_a_ausencia() -> None:

    assert numbers_equal(None, None, TOLERANCE)
    assert not numbers_equal(None, Decimal("0"), TOLERANCE)
    assert not numbers_equal(Decimal("0"), None, TOLERANCE)
    assert not numbers_equal(None, 0, TOLERANCE)


def test_zero_nao_e_ausencia_nem_medicao_vazia() -> None:

    assert numbers_equal(Decimal("0.00"), Decimal("0"), TOLERANCE)
    assert not numbers_equal(Decimal("0.00"), None, TOLERANCE)


def test_iguais_em_tipos_distintos() -> None:

    assert numbers_equal(2, 2, TOLERANCE)
    assert numbers_equal(Decimal("400.00"), 1000 - 600, TOLERANCE)
    assert numbers_equal(
        Decimal("0.3"), Decimal("60.00") / Decimal("200.00"), TOLERANCE
    )


def test_precisao_do_motor_cabe_na_tolerancia() -> None:

    motor = Decimal(50) / Decimal(300)
    oracle = Decimal("0.166666666667")

    assert abs(motor - oracle) < TOLERANCE
    assert numbers_equal(motor, oracle, TOLERANCE)


def test_fronteira_da_tolerancia() -> None:

    base = Decimal("0.22")

    assert numbers_equal(base, base + TOLERANCE, TOLERANCE)
    assert not numbers_equal(base, base + Decimal("1.1e-9"), TOLERANCE)


def test_taxa_media_nao_passa_por_rederivada() -> None:

    rederivada = Decimal(110) / Decimal(500)
    media_das_taxas = (Decimal(50) / Decimal(300) + Decimal(60) / Decimal(200)) / 2

    assert not numbers_equal(rederivada, media_das_taxas, TOLERANCE)


def test_parse_do_artefato() -> None:

    assert parse_expected(None) is None
    assert parse_expected(2) == 2
    assert parse_expected("0.1") == Decimal("0.1")
    assert parse_expected(0.1) == Decimal("0.1")
    assert parse_tolerance("1e-9") == Decimal("1e-9")

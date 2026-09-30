"""Comparação numérica com tolerância para validação contra o oracle.

Ausência (`None`) nunca equivale a número: um grupo sem observações não é
zero. Entre números, a igualdade admite a tolerância declarada pelo oracle
(1e-9), em Decimal — dinheiro nunca passa por float.
"""

from __future__ import annotations

from decimal import Decimal

Number = Decimal | int


def numbers_equal(
    actual: Number | None,
    expected: Number | None,
    tolerance: Decimal,
) -> bool:

    if actual is None or expected is None:
        return actual is None and expected is None

    return abs(Decimal(str(actual)) - Decimal(str(expected))) <= tolerance


def parse_expected(value: str | int | float | None) -> Number | None:

    if value is None:
        return None

    if isinstance(value, int):
        return value

    return Decimal(str(value))


def parse_tolerance(value: str) -> Decimal:

    return Decimal(str(value))

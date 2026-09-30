"""Funções estatísticas puras do motor de análise.

Aqui mora a conta; a orquestração (qual método lê qual fonte) fica no motor de
análise. Tudo é determinístico e em `Decimal`.

Convenções: variância e desvio são AMOSTRAIS (n-1); quartis por interpolação
linear; `mode` indefinido (sem repetição ou empate) devolve `None`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal

Number = Decimal | int


def mean(values: Sequence[Number]) -> Decimal:

    decimals = [Decimal(value) for value in values]

    return sum(decimals) / Decimal(len(decimals))


def median(values: Sequence[Number]) -> Decimal:

    ordered = sorted(Decimal(value) for value in values)
    middle = len(ordered) // 2

    if len(ordered) % 2:
        return ordered[middle]

    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def mode(values: Sequence[Number]) -> Decimal | None:

    counts = Counter(Decimal(value) for value in values)
    top = max(counts.values())

    if top == 1:
        return None

    winners = [value for value, count in counts.items() if count == top]

    return winners[0] if len(winners) == 1 else None


def sample_variance(values: Sequence[Number]) -> Decimal | None:

    if len(values) < 2:
        return None

    average = mean(values)

    return sum((Decimal(value) - average) ** 2 for value in values) / Decimal(
        len(values) - 1
    )


def sample_std(values: Sequence[Number]) -> Decimal | None:

    variance = sample_variance(values)

    return variance.sqrt() if variance is not None else None


def quantile(values: Sequence[Number], quantile_value: Decimal) -> Decimal:

    ordered = sorted(Decimal(value) for value in values)

    if len(ordered) == 1:
        return ordered[0]

    position = quantile_value * Decimal(len(ordered) - 1)
    lower = int(position)
    fraction = position - Decimal(lower)

    if fraction == 0:
        return ordered[lower]

    return ordered[lower] + fraction * (ordered[lower + 1] - ordered[lower])


def dispersion_pack(values: Sequence[Number]) -> dict[str, Decimal] | None:

    if len(values) < 2:
        return None

    pack = {
        "mean": mean(values),
        "median": median(values),
        "variance": sample_variance(values),
        "std": sample_std(values),
        "min": min(Decimal(value) for value in values),
        "max": max(Decimal(value) for value in values),
        "q1": quantile(values, Decimal("0.25")),
        "q3": quantile(values, Decimal("0.75")),
    }
    pack["iqr"] = pack["q3"] - pack["q1"]

    return pack


def slope(points: Sequence[tuple[Decimal, Decimal]]) -> Decimal | None:
    """Inclinação por mínimos quadrados de y sobre x (>= 2 pontos)."""

    if len(points) < 2:
        return None

    average_x = sum(point[0] for point in points) / Decimal(len(points))
    average_y = sum(point[1] for point in points) / Decimal(len(points))
    denominator = sum((point[0] - average_x) ** 2 for point in points)

    if denominator == 0:
        return None

    numerator = sum((point[0] - average_x) * (point[1] - average_y) for point in points)

    return numerator / denominator


def pearson(pairs: Sequence[tuple[Decimal, Decimal]]) -> Decimal | None:
    """Correlação linear de Pearson (>= 3 pares, variância não nula)."""

    if len(pairs) < 3:
        return None

    average_x = sum(pair[0] for pair in pairs) / Decimal(len(pairs))
    average_y = sum(pair[1] for pair in pairs) / Decimal(len(pairs))

    delta_x = [pair[0] - average_x for pair in pairs]
    delta_y = [pair[1] - average_y for pair in pairs]

    sum_squares_x = sum(delta**2 for delta in delta_x)
    sum_squares_y = sum(delta**2 for delta in delta_y)

    if sum_squares_x == 0 or sum_squares_y == 0:
        return None

    covariance = sum(dx * dy for dx, dy in zip(delta_x, delta_y, strict=True))

    return covariance / (sum_squares_x * sum_squares_y).sqrt()


def iqr_outliers(
    values: Sequence[Number],
) -> list[Decimal]:
    """Pontos fora da cerca IQR 1.5 (mínimo de 4 pontos)."""

    if len(values) < 4:
        return []

    q1 = quantile(values, Decimal("0.25"))
    q3 = quantile(values, Decimal("0.75"))
    iqr = q3 - q1
    low = q1 - Decimal("1.5") * iqr
    high = q3 + Decimal("1.5") * iqr

    return [Decimal(value) for value in values if value < low or value > high]


def iqr_fences(values: Sequence[Number]) -> tuple[Decimal, Decimal] | None:

    if len(values) < 4:
        return None

    q1 = quantile(values, Decimal("0.25"))
    q3 = quantile(values, Decimal("0.75"))
    iqr = q3 - q1

    return q1 - Decimal("1.5") * iqr, q3 + Decimal("1.5") * iqr

"""Contagem de buckets e comparação de janelas.

A duração de uma janela é medida no **grão**: quantos buckets ela toca (set–fev
e mar–ago são ambas 6 buckets mensais, com dias diferentes). `grain: total` e
`snapshot` tocam um.
"""

from __future__ import annotations

from datetime import date

from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    Grain,
    Period,
    PeriodType,
)


def grain_buckets(period: Period) -> int:
    """Quantos buckets de `grain` a janela toca (total/snapshot = 1)."""

    if period.type is PeriodType.SNAPSHOT or period.grain is Grain.TOTAL:
        return 1

    buckets: set[date] = set()
    current = period.start.replace(day=1)

    while current <= period.end:
        buckets.add(_bucket_start(current, period.grain))
        current = _next_month(current)

    return len(buckets)


def window_months(period: Period) -> int:
    """Meses-calendário tocados pela janela (snapshot = 1)."""

    if period.type is PeriodType.SNAPSHOT:
        return 1

    start_index = period.start.year * 12 + period.start.month
    end_index = period.end.year * 12 + period.end.month

    return end_index - start_index + 1


def windows_disjoint(left: Period, right: Period) -> bool:
    """Duas janelas não se sobrepõem."""

    return left.end < right.start or right.end < left.start


def same_grain_span(left: Period, right: Period) -> bool:
    """As duas janelas têm a mesma duração (meses-calendário).

    A duração é comparada em meses, não em dias: set–fev e mar–ago são ambas
    janelas de 6 meses, ainda que o número de dias difira. `grain: total`
    colapsa o resultado, mas não encurta a janela.
    """

    return window_months(left) == window_months(right)


def _bucket_start(month_start: date, grain: Grain) -> date:

    if grain is Grain.MONTH:
        return month_start

    if grain is Grain.QUARTER:
        quarter_month = ((month_start.month - 1) // 3) * 3 + 1
        return date(month_start.year, quarter_month, 1)

    if grain is Grain.YEAR:
        return date(month_start.year, 1, 1)

    return month_start


def _next_month(current: date) -> date:

    return date(current.year + (current.month // 12), current.month % 12 + 1, 1)

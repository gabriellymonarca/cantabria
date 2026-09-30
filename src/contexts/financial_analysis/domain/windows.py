"""Resolução determinística de janelas temporais nomeadas.

A data de referência é o as-of do negócio (último dia com dado oficial). As
datas concretas são derivadas dela por código: o catálogo declara a definição
da janela (offset/âncora) e aqui ela vira um intervalo concreto.

Assim, avançar a janela do sistema é atualizar `reference_date` no catálogo
versionado: as janelas se recalculam sozinhas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class WindowKind(StrEnum):
    """Como uma janela nomeada é ancorada na data de referência."""

    SNAPSHOT_AT_REFERENCE = "snapshot_at_reference"
    TRAILING_MONTHS = "trailing_months"
    YEAR_TO_DATE = "year_to_date"
    PREVIOUS_YEAR = "previous_year"


@dataclass(frozen=True)
class ResolvedWindow:
    """O intervalo concreto de uma janela nomeada."""

    start: date
    end: date


def resolve_window(
    kind: WindowKind,
    reference_date: date,
    months: int | None = None,
) -> ResolvedWindow:

    if kind is WindowKind.SNAPSHOT_AT_REFERENCE:
        return ResolvedWindow(start=reference_date, end=reference_date)

    if kind is WindowKind.TRAILING_MONTHS:
        return _trailing_months(reference_date, months)

    if kind is WindowKind.YEAR_TO_DATE:
        return ResolvedWindow(start=date(reference_date.year, 1, 1), end=reference_date)

    if kind is WindowKind.PREVIOUS_YEAR:
        year = reference_date.year - 1
        return ResolvedWindow(start=date(year, 1, 1), end=date(year, 12, 31))

    raise ValueError(f"Tipo de janela desconhecido: {kind!r}")


def _trailing_months(reference_date: date, months: int | None) -> ResolvedWindow:

    if months is None or months < 1:
        raise ValueError("trailing_months exige 'months' >= 1.")

    return ResolvedWindow(
        start=_first_day_months_before(reference_date, months - 1),
        end=reference_date,
    )


def _first_day_months_before(reference_date: date, months: int) -> date:

    index = reference_date.year * 12 + (reference_date.month - 1) - months
    year, month = divmod(index, 12)

    return date(year, month + 1, 1)

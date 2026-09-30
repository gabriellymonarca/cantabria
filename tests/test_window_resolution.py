"""Resolução determinística das janelas nomeadas.

As datas são derivadas de `reference_date`; nada é escrito à mão. Estes testes
cobrem as âncoras e os casos de virada de mês e de ano.
"""

from __future__ import annotations

from datetime import date

import pytest

from contexts.financial_analysis.domain.windows import WindowKind, resolve_window


@pytest.mark.parametrize(
    ("kind", "months", "reference_date", "expected_start", "expected_end"),
    [
        (
            WindowKind.SNAPSHOT_AT_REFERENCE,
            None,
            date(2026, 8, 31),
            date(2026, 8, 31),
            date(2026, 8, 31),
        ),
        (
            WindowKind.SNAPSHOT_AT_REFERENCE,
            None,
            date(2026, 1, 15),
            date(2026, 1, 15),
            date(2026, 1, 15),
        ),
        (
            WindowKind.TRAILING_MONTHS,
            1,
            date(2026, 8, 31),
            date(2026, 8, 1),
            date(2026, 8, 31),
        ),
        (
            WindowKind.TRAILING_MONTHS,
            3,
            date(2026, 8, 31),
            date(2026, 6, 1),
            date(2026, 8, 31),
        ),
        (
            WindowKind.TRAILING_MONTHS,
            6,
            date(2026, 8, 31),
            date(2026, 3, 1),
            date(2026, 8, 31),
        ),
        (
            WindowKind.TRAILING_MONTHS,
            12,
            date(2026, 8, 31),
            date(2025, 9, 1),
            date(2026, 8, 31),
        ),
        (
            WindowKind.TRAILING_MONTHS,
            3,
            date(2026, 1, 15),
            date(2025, 11, 1),
            date(2026, 1, 15),
        ),
        (
            WindowKind.TRAILING_MONTHS,
            3,
            date(2026, 2, 28),
            date(2025, 12, 1),
            date(2026, 2, 28),
        ),
        (
            WindowKind.YEAR_TO_DATE,
            None,
            date(2026, 8, 31),
            date(2026, 1, 1),
            date(2026, 8, 31),
        ),
        (
            WindowKind.YEAR_TO_DATE,
            None,
            date(2025, 6, 30),
            date(2025, 1, 1),
            date(2025, 6, 30),
        ),
        (
            WindowKind.PREVIOUS_YEAR,
            None,
            date(2026, 8, 31),
            date(2025, 1, 1),
            date(2025, 12, 31),
        ),
    ],
)
def test_resolve_window_deriva_datas(
    kind: WindowKind,
    months: int | None,
    reference_date: date,
    expected_start: date,
    expected_end: date,
) -> None:

    window = resolve_window(kind, reference_date, months)

    assert window.start == expected_start
    assert window.end == expected_end


def test_trailing_months_exige_um_numero_positivo() -> None:

    with pytest.raises(ValueError):
        resolve_window(WindowKind.TRAILING_MONTHS, date(2026, 8, 31))


def test_trailing_months_recusa_zero() -> None:

    with pytest.raises(ValueError):
        resolve_window(WindowKind.TRAILING_MONTHS, date(2026, 8, 31), months=0)

"""Ingestão de mercado offline: parsing do SGS, cache e carga no seed.

Sem rede: o JSON público é inline e o cache versionado (`data/market/`) é um
artefato do repositório — a demo roda do clone sem tocar o BACEN. O teste
cobre o parsing, a proveniência, a ida-e-volta do CSV e a conversão do valor
publicado (% no mês) na fração decimal que a tabela guarda.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from utils.ingest_market_data import (
    SERIES,
    MarketSeries,
    parse_sgs_payload,
    read_cache,
    write_cache,
)
from utils.seed_clickhouse import _rows_mercado

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE = REPO_ROOT / "data" / "market" / "bacen_sgs.csv"

CDI = MarketSeries(indicador="cdi", serie_codigo="4391", unidade="% no mês")
PAYLOAD = (
    '[{"data":"01/11/2024","valor":"0.79"},'
    '{"data":"01/09/2024","valor":"0.84"},'
    '{"data":"01/10/2024","valor":"0.93"}]'
)
EXTRACTED_AT = date(2026, 9, 29)


def test_parse_do_payload_do_sgs_tipifica_e_ordena() -> None:

    points = parse_sgs_payload(PAYLOAD, CDI, extracted_at=EXTRACTED_AT)

    assert [point.data_referencia for point in points] == [
        date(2024, 9, 1),
        date(2024, 10, 1),
        date(2024, 11, 1),
    ]

    first = points[0]

    assert first.indicador == "cdi"
    assert first.fonte == "BACEN/SGS"
    assert first.serie_codigo == "4391"
    assert first.valor_publicado == Decimal("0.84")
    assert first.unidade == "% no mês"
    assert first.data_extracao == EXTRACTED_AT


def test_cache_round_trip_preserva_proveniencia_e_ordem(tmp_path) -> None:

    path = tmp_path / "bacen_sgs.csv"
    points = parse_sgs_payload(PAYLOAD, CDI, extracted_at=EXTRACTED_AT)

    write_cache(path, points)

    assert read_cache(path) == points
    assert path.read_text(encoding="utf-8").splitlines()[0] == (
        "indicador,fonte,serie_codigo,data_referencia,valor_publicado,unidade,"
        "data_extracao"
    )


def test_seed_converte_percentual_publicado_em_fracao_decimal() -> None:

    points = parse_sgs_payload(PAYLOAD, CDI, extracted_at=EXTRACTED_AT)
    rows = _rows_mercado(points)

    assert rows[0] == (
        "cdi",
        date(2024, 9, 1),
        Decimal("0.0084"),
        "BACEN/SGS",
        "4391",
        EXTRACTED_AT,
    )


def test_cache_versionado_tem_as_tres_series_do_plano() -> None:

    points = read_cache(CACHE)

    assert len(points) == 72
    assert {point.indicador for point in points} == {"cdi", "selic", "ipca"}
    assert {point.serie_codigo for point in points} == {"4390", "4391", "433"}

    for series in SERIES:
        selected = [point for point in points if point.indicador == series.indicador]

        assert len(selected) == 24
        assert {point.serie_codigo for point in selected} == {series.serie_codigo}

    assert all(point.fonte == "BACEN/SGS" for point in points)
    assert all(point.data_referencia.day == 1 for point in points)
    assert min(point.data_referencia for point in points) == date(2024, 9, 1)
    assert max(point.data_referencia for point in points) == date(2026, 8, 1)

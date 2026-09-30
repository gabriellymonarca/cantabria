#!/usr/bin/env python3
"""Ingestão das séries macro do BACEN/SGS para o cache versionado.

Fora do caminho de resposta: este CLI busca as séries no SGS,
grava um CSV determinístico em `data/market/` com a proveniência completa e
para. O seed do ClickHouse lê esse CSV, sem acesso à rede.

Séries (API SGS do Banco Central, JSON público):
    4390  SELIC acumulada no mês (%)
    4391  CDI acumulado no mês (%)
    433   IPCA mensal (%)

Idempotente: sem `--force`, um cache existente é preservado (e a data de
extração não muda); com `--force`, as três séries são rebuscadas e o arquivo é
reescrito por inteiro.

Uso:
    python utils/ingest_market_data.py             # usa/valida o cache
    python utils/ingest_market_data.py --force     # refaz a busca no SGS
    python utils/ingest_market_data.py --out data/market/bacen_sgs.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FONTE = "BACEN/SGS"
SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie_codigo}/dados"
WINDOW_START = "01/09/2024"
WINDOW_END = "31/08/2026"
DEFAULT_OUT = REPO_ROOT / "data" / "market" / "bacen_sgs.csv"
TIMEOUT_SECONDS = 60.0

CSV_COLUMNS = (
    "indicador",
    "fonte",
    "serie_codigo",
    "data_referencia",
    "valor_publicado",
    "unidade",
    "data_extracao",
)


@dataclass(frozen=True)
class MarketSeries:
    """Uma série do SGS: indicador semântico, código, unidade publicada."""

    indicador: str
    serie_codigo: str
    unidade: str


@dataclass(frozen=True)
class MarketPoint:
    """Um ponto publicado: o valor COMO PUBLICADO (% no mês) e a linhagem."""

    indicador: str
    fonte: str
    serie_codigo: str
    data_referencia: date
    valor_publicado: Decimal
    unidade: str
    data_extracao: date


SERIES: tuple[MarketSeries, ...] = (
    MarketSeries(indicador="cdi", serie_codigo="4391", unidade="% no mês"),
    MarketSeries(indicador="selic", serie_codigo="4390", unidade="% no mês"),
    MarketSeries(indicador="ipca", serie_codigo="433", unidade="% no mês"),
)


def fetch_series(
    series: MarketSeries,
    *,
    start: str = WINDOW_START,
    end: str = WINDOW_END,
    timeout: float = TIMEOUT_SECONDS,
) -> str:
    """Busca a série no SGS e devolve o JSON cru (formato público)."""

    query = urllib.parse.urlencode(
        {"formato": "json", "dataInicial": start, "dataFinal": end}
    )
    url = f"{SGS_URL.format(serie_codigo=series.serie_codigo)}?{query}"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise RuntimeError(
            f"falha ao buscar a série {series.serie_codigo}: {error}"
        ) from error


def parse_sgs_payload(
    payload: str,
    series: MarketSeries,
    *,
    extracted_at: date,
) -> list[MarketPoint]:
    """Converte o JSON do SGS (data dd/mm/aaaa, valor em %) em pontos."""

    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"JSON inválido da série {series.serie_codigo}: {error}"
        ) from error

    points: list[MarketPoint] = []

    for entry in raw:
        reference = datetime.strptime(str(entry["data"]), "%d/%m/%Y").date()

        points.append(
            MarketPoint(
                indicador=series.indicador,
                fonte=FONTE,
                serie_codigo=series.serie_codigo,
                data_referencia=reference,
                valor_publicado=Decimal(str(entry["valor"])),
                unidade=series.unidade,
                data_extracao=extracted_at,
            )
        )

    return sorted(points, key=lambda point: point.data_referencia)


def write_cache(path: Path, points: list[MarketPoint]) -> None:
    """Grava o CSV versionado, ordenado e reproduzível (fim de linha `\\n`)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(points, key=lambda point: (point.indicador, point.data_referencia))

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)

        for point in ordered:
            writer.writerow(
                [
                    point.indicador,
                    point.fonte,
                    point.serie_codigo,
                    point.data_referencia.isoformat(),
                    format(point.valor_publicado, "f"),
                    point.unidade,
                    point.data_extracao.isoformat(),
                ]
            )


def read_cache(path: Path) -> list[MarketPoint]:
    """Lê o cache versionado de volta em pontos tipados."""

    if not path.is_file():
        raise FileNotFoundError(
            f"cache ausente em {path}; rode com rede: "
            "python utils/ingest_market_data.py --force"
        )

    points: list[MarketPoint] = []

    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            points.append(
                MarketPoint(
                    indicador=row["indicador"],
                    fonte=row["fonte"],
                    serie_codigo=row["serie_codigo"],
                    data_referencia=date.fromisoformat(row["data_referencia"]),
                    valor_publicado=Decimal(row["valor_publicado"]),
                    unidade=row["unidade"],
                    data_extracao=date.fromisoformat(row["data_extracao"]),
                )
            )

    return points


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="CSV versionado de saída"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebusca as três séries mesmo com cache existente",
    )
    args = parser.parse_args()

    if args.out.is_file() and not args.force:
        points = read_cache(args.out)

        print(
            f"cache preservado: {args.out} ({len(points)} pontos; "
            "use --force para rebuscar)"
        )

        return 0

    extracted_at = date.today()
    points: list[MarketPoint] = []

    for series in SERIES:
        payload = fetch_series(series)
        fetched = parse_sgs_payload(payload, series, extracted_at=extracted_at)

        if not fetched:
            raise SystemExit(
                f"erro: série {series.serie_codigo} voltou vazia; cache não gravado."
            )

        points.extend(fetched)

    write_cache(args.out, points)

    per_series = ", ".join(
        f"{series.indicador}={sum(1 for p in points if p.indicador == series.indicador)}"
        for series in SERIES
    )
    print(f"OK: {len(points)} pontos ({per_series}) em {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

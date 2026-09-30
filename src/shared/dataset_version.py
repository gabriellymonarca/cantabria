"""Impressão digital de conteúdo do dataset oficial.

A versão do dado que carimba um resultado precisa mudar quando o CONTEÚDO
muda, não quando o calendário vira. Este kernel recebe resumos canônicos por
tabela (contagens, somas, máximo) e devolve o hash sha256 estável desse
retrato. Quem coleta o retrato (Python sobre o fixture, ClickHouse sobre o
banco) formata cada campo da mesma maneira; o hash então coincide entre os
dois lados quando o conteúdo é o mesmo.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal

_MONEY_QUANTUM = Decimal("0.00")


def normalize_money(value: Decimal | int | str) -> str:

    return str(Decimal(str(value)).quantize(_MONEY_QUANTUM))


def normalize_count(value: int | str) -> str:

    return str(int(str(value)))


def fingerprint_tables(tables: Mapping[str, Mapping[str, str]]) -> str:

    payload = json.dumps(
        {table: dict(fields) for table, fields in tables.items()},
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def format_snapshot_version(reference_date: str | None, fingerprint: str) -> str:

    reference = reference_date if reference_date else "unknown"

    return f"{reference}#sha256:{fingerprint}"

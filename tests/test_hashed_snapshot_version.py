"""Snapshot versionado por hash: composição e fallback.

O `HashedSnapshotVersionAdapter` decora a versão base (data de referência)
com o fingerprint de conteúdo; se o fingerprint falhar, a versão da base
passa direto e o pipeline segue. O adapter ClickHouse coleta o
retrato canônico com o mesmo formato que o fixture Python usa no oracle.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from contexts.financial_analysis.adapters.outbound.clickhouse_dataset_fingerprint import (
    ClickHouseDatasetFingerprintAdapter,
)
from contexts.financial_analysis.adapters.outbound.hashed_snapshot_version import (
    HashedSnapshotVersionAdapter,
)
from contexts.financial_analysis.ports.outbound.dataset_fingerprint_port import (
    DatasetFingerprintPort,
)
from contexts.financial_analysis.ports.outbound.snapshot_version_port import (
    SnapshotVersionPort,
)


class _Base(SnapshotVersionPort):
    def current(self) -> str:

        return "2026-08-31"


class _Digest(DatasetFingerprintPort):
    def __init__(self, digest: str):

        self._digest = digest

    def digest(self) -> str:

        return self._digest


class _BoomDigest(DatasetFingerprintPort):
    def digest(self) -> str:

        raise RuntimeError("clickhouse indisponível")


class _StubClient:
    def __init__(self, counts: int = 3):

        self._counts = counts
        self.queries: list[str] = []

    def query(self, sql: str) -> Any:

        self.queries.append(sql)

        if "sum(" in sql:
            return _StubResult(
                (
                    self._counts,
                    Decimal("2900.00"),
                    Decimal("390.00"),
                    dt.date(2026, 8, 31),
                )
            )

        return _StubResult((self._counts,))


class _StubResult:
    def __init__(self, first_row: tuple):

        self.first_row = first_row


class _EmptyRentClient(_StubClient):
    def query(self, sql: str) -> Any:

        self.queries.append(sql)

        if "sum(" in sql:
            return _StubResult((0, None, None, None))

        return _StubResult((0,))


def test_composta_data_com_hash() -> None:

    adapter = HashedSnapshotVersionAdapter(_Base(), _Digest("abc123"))

    assert adapter.current() == "2026-08-31#sha256:abc123"


def test_falha_do_fingerprint_cai_para_a_base() -> None:

    adapter = HashedSnapshotVersionAdapter(_Base(), _BoomDigest())

    assert adapter.current() == "2026-08-31"


def test_fingerprint_consulta_todas_as_tabelas() -> None:

    adapter = ClickHouseDatasetFingerprintAdapter(_StubClient(), database="test")
    digest = adapter.digest()

    assert len(digest) == 64
    assert len(adapter._client.queries) == 7


def test_tabela_vazia_tem_retrato_canonico() -> None:

    adapter = ClickHouseDatasetFingerprintAdapter(_EmptyRentClient(), database="test")
    digest = adapter.digest()

    assert len(digest) == 64

"""Configuração do ClickHouse lida do ambiente.

O adapter recebe as credenciais injetadas pelo composition root; este módulo só
traduz o ambiente num value object. O `.env` local é carregado por quem monta a
aplicação (`entrypoints`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ClickHouseConfig:
    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> ClickHouseConfig:

        return cls(
            host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
            port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
            database=os.environ.get("CLICKHOUSE_DB", "cantabria"),
            user=os.environ.get("CLICKHOUSE_USER", "default"),
            password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        )

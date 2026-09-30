"""Conexão e serialização BSON para os stores MongoDB.

A URL vem do ambiente (`MONGO_URL`). Sem ela, a fiação usa os adapters em
memória; com ela, mas com o servidor fora do ar, a fiação também degrada para
memória e o `/ready` reporta o estado (degradação graciosa).
`to_bson_safe` converte os tipos que o BSON não aceita — o `Decimal` da
análise financeira vira `Decimal128` (exato), nunca ponto flutuante — e
resolve enums para os seus valores.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from bson.decimal128 import Decimal128
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

MONGO_URL_ENV = "MONGO_URL"

DEFAULT_DATABASE = "cantabria"
DEFAULT_TIMEOUT_MS = 1500


@dataclass(frozen=True)
class MongoConfig:
    """A URL do MongoDB e o limite de espera pela seleção de servidor."""

    url: str
    timeout_ms: int = DEFAULT_TIMEOUT_MS

    @classmethod
    def from_env(cls) -> MongoConfig | None:
        """Lê `MONGO_URL`; ausente ou vazia desliga o Mongo."""

        url = os.environ.get(MONGO_URL_ENV, "").strip()

        return cls(url=url) if url else None


def open_database(config: MongoConfig) -> Database:
    """Abre a conexão e confirma com um ping; levanta se não alcançar."""

    client = MongoClient(config.url, serverSelectionTimeoutMS=config.timeout_ms)

    try:
        client.admin.command("ping")
    except Exception:
        client.close()
        raise

    return client.get_default_database(default=DEFAULT_DATABASE)


def upsert_document(
    collection: Collection,
    selector: dict,
    update: dict,
    *,
    replace: bool = False,
    attempts: int = 2,
) -> None:
    """Upsert tolerante à corrida de criação simultânea do mesmo `_id`.

    O Chainlit cria a thread no `connect` e o store pode gravar a conversa do
    primeiro turno ao mesmo tempo: um dos dois upserts perde a corrida com
    `E11000`. Repetir resolve — na segunda tentativa o documento já existe.
    """

    for attempt in range(attempts):
        try:
            if replace:
                collection.replace_one(selector, update, upsert=True)
            else:
                collection.update_one(selector, update, upsert=True)

            return
        except DuplicateKeyError:
            if attempt + 1 == attempts:
                raise


def to_bson_safe(value: Any) -> Any:
    """Converte um valor para algo que o BSON armazene sem perder exatidão."""

    if is_dataclass(value) and not isinstance(value, type):
        return to_bson_safe(asdict(value))

    if isinstance(value, Decimal):
        return Decimal128(value)

    if isinstance(value, Enum):
        return to_bson_safe(value.value)

    # O BSON não tem tipo data: meia-noite UTC mantém o dia (o horário de um
    # `datetime` já é significativo e passa como está).
    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)

    if isinstance(value, dict):
        return {key: to_bson_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [to_bson_safe(item) for item in value]

    return value


def from_bson_safe(value: Any) -> Any:
    """Inverso de `to_bson_safe` para leitura: `Decimal128` volta a `Decimal`."""

    if isinstance(value, Decimal128):
        return value.to_decimal()

    if isinstance(value, dict):
        return {key: from_bson_safe(item) for key, item in value.items()}

    if isinstance(value, list):
        return [from_bson_safe(item) for item in value]

    return value

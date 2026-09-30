"""Readiness probe served by the Chainlit FastAPI application.

Chainlit already serves ``GET /health`` as a trivial liveness check and owns
the HTTP server, so the Cantábria probe is registered as ``GET /ready`` on
``chainlit.server:app`` by the composition root (see ``entrypoints.app``).
Every check is injected through ``HealthDeps``, which keeps the route
testable without a database.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from cross_cutting.config import AppConfig, DataConfig

_CLICKHOUSE_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class HealthDeps:
    check_clickhouse: Callable[[], str]
    check_mongo: Callable[[], str]
    check_qdrant: Callable[[], str]
    check_minio: Callable[[], str]
    catalog_version: Callable[[], str]
    prompt_version: Callable[[], str]
    tracing: str


def check_clickhouse() -> str:
    """Pings ClickHouse with the application credentials; never raises."""

    import clickhouse_connect

    from contexts.financial_calculation.adapters.outbound.clickhouse_config import (
        ClickHouseConfig,
    )

    client = None

    # `get_client` já conecta (consulta versão/timezone): fica dentro do try
    # para que ClickHouse fora do ar vire "degraded", não um 500 no /ready.
    try:
        config = ClickHouseConfig.from_env()
        client = clickhouse_connect.get_client(
            host=config.host,
            port=config.port,
            database=config.database,
            username=config.user,
            password=config.password,
            connect_timeout=_CLICKHOUSE_TIMEOUT_SECONDS,
        )

        if not client.ping():
            return "error: ping returned false"

        return "ok"
    except Exception as error:
        return f"error: {error}"
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()


def check_mongo() -> str:
    """Reports the conversation/audit store status; never raises.

    Sem `MONGO_URL` a aplicação roda com os stores em memória;
    com a URL definida, um ping decide entre ``ok`` e o erro.
    """

    from cross_cutting.mongo import MongoConfig, open_database

    config = MongoConfig.from_env()

    if config is None:
        return "disabled (in-memory)"

    database = None

    try:
        database = open_database(config)

        return "ok"
    except Exception as error:
        return f"error: {error}"
    finally:
        if database is not None:
            database.client.close()


def check_qdrant(embeddings_configured: bool = True) -> str:
    """Reports the semantic RAG store; without it the app is lexical.

    Com Qdrant de pé e sem a seção `embeddings`, a busca continua lexical e o
    estado reportado diz isso.
    """

    import os

    from qdrant_client import QdrantClient

    url = os.environ.get("QDRANT_URL", "").strip()

    if not url:
        return "disabled (lexical BM25)"

    client = QdrantClient(url=url, timeout=2.0)

    try:
        client.get_collections()
    except Exception as error:
        return f"error: {error}"
    finally:
        client.close()

    if not embeddings_configured:
        return "ok (lexical: embeddings off)"

    return "ok"


def check_minio() -> str:
    """Reports the document/artifact object store; never raises."""

    import os
    from urllib.parse import urlsplit

    from minio import Minio

    endpoint = os.environ.get("MINIO_ENDPOINT", "").strip()

    if not endpoint:
        return "disabled"

    parsed = urlsplit(endpoint)
    server = parsed.netloc or parsed.path

    try:
        Minio(
            server,
            access_key=os.environ.get("MINIO_ROOT_USER", ""),
            secret_key=os.environ.get("MINIO_ROOT_PASSWORD", ""),
            secure=parsed.scheme == "https",
        ).list_buckets()

        return "ok"
    except Exception as error:
        return f"error: {error}"


def catalog_version() -> str:
    """Resolves the active catalog version; never raises."""

    from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
        YamlSemanticCatalogAdapter,
    )

    try:
        return YamlSemanticCatalogAdapter().load_active().catalog_version
    except Exception as error:
        return f"unknown: {error}"


def prompt_version(data: DataConfig) -> str:
    """Reports the effective version of each prompt contract, e.g.
    ``interpretation=v1,insight=v3,documental=v1``; the version is the selected
    directory."""

    directories = data.resolved_prompts_dirs()
    missing = [
        name for name, directory in directories.items() if not directory.is_dir()
    ]

    if missing:
        return f"unknown: missing prompts for {', '.join(missing)}"

    return ",".join(
        f"{name}={directory.name}" for name, directory in directories.items()
    )


def default_deps(config: AppConfig) -> HealthDeps:

    return HealthDeps(
        check_clickhouse=check_clickhouse,
        check_mongo=check_mongo,
        check_qdrant=partial(
            check_qdrant,
            embeddings_configured=config.resolved_embeddings() is not None,
        ),
        check_minio=check_minio,
        catalog_version=catalog_version,
        prompt_version=partial(prompt_version, config.data),
        tracing="enabled" if config.observability.enabled else "disabled",
    )


def build_health_status(deps: HealthDeps) -> tuple[int, dict[str, str]]:

    clickhouse = deps.check_clickhouse()
    mongo = deps.check_mongo()
    qdrant = deps.check_qdrant()
    minio = deps.check_minio()
    catalog = deps.catalog_version()
    prompt = deps.prompt_version()

    body = {
        "status": "ok",
        "clickhouse": clickhouse,
        "mongo": mongo,
        "qdrant": qdrant,
        "minio": minio,
        "catalog_version": catalog,
        "prompt_version": prompt,
        "tracing": deps.tracing,
    }

    if clickhouse != "ok":
        body["status"] = "degraded"

        return 503, body

    if (
        mongo.startswith("error")
        or qdrant.startswith("error")
        or minio.startswith("error")
        or catalog.startswith("unknown")
        or prompt.startswith("unknown")
    ):
        body["status"] = "degraded"

    return 200, body


def register_health_route(app: FastAPI, deps: HealthDeps) -> None:

    async def ready() -> JSONResponse:

        code, body = build_health_status(deps)

        return JSONResponse(status_code=code, content=body)

    # First position wins in Starlette, and Chainlit ends its router with a
    # `/{full_path:path}` catch-all serving the SPA: appending would answer
    # every unknown path with HTML instead of reaching this probe.
    app.router.routes.insert(0, APIRoute("/ready", ready, methods=["GET"]))

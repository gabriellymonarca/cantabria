"""Observabilidade visível por padrão: tracing, contexto e health."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cross_cutting.config import (
    ConfigError,
    DataConfig,
    ObservabilityConfig,
    load_config,
)
from cross_cutting.logging import bind_request_context, unbind_request_context
from cross_cutting.observability import (
    _span_metadata,
    configure_observability,
    is_enabled,
    shutdown_observability,
    traced_request,
)
from entrypoints.health import (
    HealthDeps,
    build_health_status,
    prompt_version,
    register_health_route,
)

ROOT = Path(__file__).resolve().parents[1]


def _disabled_config() -> ObservabilityConfig:

    return ObservabilityConfig(
        enabled=False,
        host="",
        public_key="",
        secret_key="",
        environment="local",
        release="",
    )


def _deps(
    clickhouse: str = "ok",
    mongo: str = "disabled (in-memory)",
    qdrant: str = "disabled (lexical BM25)",
    minio: str = "disabled",
    catalog: str = "v2",
    prompt: str = "v1",
    tracing: str = "disabled",
) -> HealthDeps:

    return HealthDeps(
        check_clickhouse=lambda: clickhouse,
        check_mongo=lambda: mongo,
        check_qdrant=lambda: qdrant,
        check_minio=lambda: minio,
        catalog_version=lambda: catalog,
        prompt_version=lambda: prompt,
        tracing=tracing,
    )


def test_tracing_desabilitado_e_noop() -> None:

    shutdown_observability()
    configure_observability(_disabled_config())

    assert not is_enabled()

    with traced_request("user", "session", "pergunta") as record_output:
        record_output("resposta")

    shutdown_observability()


def test_tracing_desabilitado_aceita_trace_id_do_turno() -> None:

    shutdown_observability()
    configure_observability(_disabled_config())

    with traced_request(
        "user",
        "session",
        "pergunta",
        trace_id="turno-1",
        prompt_version="interpretation=v1,insight=v3,documental=v1",
    ) as record_output:
        record_output("resposta")

    shutdown_observability()


def test_metadata_do_span_leva_trace_id_e_versao_dos_prompts() -> None:

    assert _span_metadata("turno-1", "interpretation=v1") == {
        "cantabria.trace_id": "turno-1",
        "cantabria.prompt_version": "interpretation=v1",
    }
    assert _span_metadata("turno-1", "") == {"cantabria.trace_id": "turno-1"}
    assert _span_metadata(None, "") is None


def test_tracing_habilitado_sem_credenciais_falha_no_startup(tmp_path: Path) -> None:

    raw = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    raw["observability"]["enabled"] = True
    raw["observability"]["public_key"] = ""
    raw["observability"]["secret_key"] = ""

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    try:
        load_config(config_path)
        raise AssertionError("load_config deveria falhar sem as chaves.")
    except ConfigError:
        pass


def test_config_exemplo_tem_tracing_desligado_por_padrao() -> None:

    # Uma cópia literal do exemplo deve subir sem a stack Langfuse.
    raw = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))

    assert raw["observability"]["enabled"] is False


def test_contexto_request_bind_e_unbind() -> None:

    bind_request_context(trace_id="trace-1", session_id="sess-1", user_id="user-1")

    try:
        context = structlog.contextvars.get_contextvars()

        assert context["trace_id"] == "trace-1"
        assert context["session_id"] == "sess-1"
        assert context["user_id"] == "user-1"
    finally:
        unbind_request_context("trace_id", "session_id", "user_id")

    assert "trace_id" not in structlog.contextvars.get_contextvars()


def test_health_ok() -> None:

    code, body = build_health_status(_deps())

    assert code == 200
    assert body["status"] == "ok"
    assert body["clickhouse"] == "ok"
    assert body["catalog_version"] == "v2"
    assert body["prompt_version"] == "v1"


def test_prompt_version_reporta_a_versao_efetiva_de_cada_contrato() -> None:
    """A versão é o diretório selecionado pelo config para cada contrato de prompt."""

    assert prompt_version(DataConfig()) == "interpretation=v1,insight=v3,documental=v1"


def test_prompt_version_acusa_diretorio_ausente(tmp_path: Path) -> None:

    data = DataConfig(insight_prompts_dir=tmp_path / "nao-existe")

    assert prompt_version(data) == "unknown: missing prompts for insight"


def test_health_sem_clickhouse_degrada_com_503() -> None:

    code, body = build_health_status(_deps(clickhouse="error: refused"))

    assert code == 503
    assert body["status"] == "degraded"


def test_health_com_versao_desconhecida_degrada_sem_503() -> None:

    code, body = build_health_status(_deps(catalog="unknown: sem catálogo"))

    assert code == 200
    assert body["status"] == "degraded"


def test_health_com_stores_opcionais_fora_do_ar_degrada_sem_503() -> None:

    code, body = build_health_status(_deps(qdrant="error: refused"))

    assert code == 200
    assert body["status"] == "degraded"

    code, body = build_health_status(_deps(minio="error: refused"))

    assert code == 200
    assert body["status"] == "degraded"
    assert body["qdrant"] == "disabled (lexical BM25)"
    assert body["minio"] == "error: refused"


def test_health_com_mongo_configurado_e_fora_do_ar_degrada_sem_503() -> None:

    code, body = build_health_status(_deps(mongo="error: refused"))

    assert code == 200
    assert body["status"] == "degraded"
    assert body["mongo"] == "error: refused"

    code, body = build_health_status(_deps())

    assert code == 200
    assert body["status"] == "ok"
    assert body["mongo"] == "disabled (in-memory)"


def test_health_route_responde_no_fastapi() -> None:

    app = FastAPI()
    register_health_route(app, _deps(tracing="enabled"))

    response = TestClient(app).get("/ready")

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ok"
    assert body["tracing"] == "enabled"
    assert set(body) == {
        "status",
        "clickhouse",
        "mongo",
        "qdrant",
        "minio",
        "catalog_version",
        "prompt_version",
        "tracing",
    }

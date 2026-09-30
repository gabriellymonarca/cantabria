#!/usr/bin/env python3
"""Pré-voo da demo: confere configuração, segredos, serviços e dados.

Só biblioteca padrão (PyYAML é usado quando instalado). Cada verificação
imprime `[OK]`, `[AVISO]` ou `[FALHA]`; qualquer FALHA termina com código 1 e
um NO-GO. Serviços opcionais (stores, app, Langfuse) fora do ar geram AVISO,
não FALHA — a demo mínima é ClickHouse populado + config válida + LLM
alcançável.

Uso (raiz do checkout, com o stack `core` de pé):
    python scripts/preflight.py          # ou: make preflight

Variáveis lidas (ambiente vence o .env): CLICKHOUSE_HOST/PORT/DB/USER/PASSWORD,
CHAINLIT_PORT, CHAINLIT_AUTH_SECRET, OAUTH_GOOGLE_CLIENT_ID, CONFIG_PATH,
MONGO_URL, QDRANT_URL, MINIO_ENDPOINT. Segredos nunca são impressos.
"""

from __future__ import annotations

import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = REPO_ROOT / "infra" / "clickhouse" / "init" / "00_schema.sql"
PLACEHOLDER = re.compile(r"CHANGE[_-]?ME", re.IGNORECASE)
TIMEOUT_SECONDS = 3.0

OK, AVISO, FALHA = "OK", "AVISO", "FALHA"


@dataclass
class Report:
    failures: int = 0
    warnings: int = 0
    lines: list[str] = field(default_factory=list)

    def add(self, status: str, message: str) -> None:

        if status == FALHA:
            self.failures += 1
        elif status == AVISO:
            self.warnings += 1

        line = f"[{status}] {message}"
        self.lines.append(line)
        print(line)


def read_dotenv(path: Path) -> dict[str, str]:
    """Lê `CHAVE=valor` de um arquivo .env; ignora comentários e vazios."""

    values: dict[str, str] = {}

    if not path.is_file():
        return values

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def setting(name: str, dotenv: dict[str, str], default: str = "") -> str:

    return os.environ.get(name) or dotenv.get(name) or default


def http_get(url: str, headers: dict[str, str] | None = None) -> tuple[int | None, str]:
    """GET simples; devolve (status, corpo). Status None = sem conexão."""

    request = urllib.request.Request(url, headers=headers or {})

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return None, ""


def tcp_open(host: str, port: int) -> bool:

    try:
        with socket.create_connection((host, port), timeout=TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


def load_config(path: Path) -> dict | None:
    """Carrega o config.yaml com PyYAML quando disponível; senão devolve None."""

    try:
        import yaml
    except ImportError:
        return None

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))

    return loaded if isinstance(loaded, dict) else {}


def check_config(report: Report, dotenv: dict[str, str]) -> dict:
    """config.yaml existe, sem CHANGE_ME e com llm.api_key preenchida."""

    path = Path(setting("CONFIG_PATH", dotenv, "config.yaml"))

    if not path.is_absolute():
        path = REPO_ROOT / path

    if not path.is_file():
        report.add(FALHA, f"{path.name} não existe: cp config.example.yaml {path.name}")

        return {}

    text = path.read_text(encoding="utf-8")

    if PLACEHOLDER.search(text):
        report.add(FALHA, f"{path.name} ainda contém CHANGE_ME; preencha os valores")
    else:
        report.add(OK, f"{path.name} sem placeholders")

    config = load_config(path)

    if config is None:
        match = re.search(r"^\s*api_key:\s*(\S+)", text, re.MULTILINE)
        api_key = match.group(1).strip("\"'") if match else ""
        config = {"llm": {"api_key": api_key}}
        report.add(AVISO, "PyYAML ausente: config.yaml lido por expressão regular")

    api_key = str((config.get("llm") or {}).get("api_key") or "").strip()

    if api_key:
        report.add(OK, "llm.api_key preenchida")
    else:
        report.add(FALHA, "llm.api_key vazia no config.yaml")

    return config


def check_dotenv(report: Report, dotenv: dict[str, str]) -> None:
    """.env existe e traz todas as chaves do .env.example."""

    path = REPO_ROOT / ".env"

    if not path.is_file():
        report.add(FALHA, ".env não existe: cp .env.example .env")

        return

    expected = read_dotenv(REPO_ROOT / ".env.example")
    missing = sorted(key for key in expected if key not in dotenv)

    if missing:
        report.add(FALHA, f".env sem as chaves: {', '.join(missing)}")
    else:
        report.add(OK, f".env com as {len(expected)} chaves do .env.example")

    placeholders = sorted(
        key for key, value in dotenv.items() if PLACEHOLDER.search(value)
    )

    if placeholders:
        joined = ", ".join(placeholders)
        report.add(AVISO, f".env com valores CHANGE_ME em: {joined}")


def check_auth_secret(report: Report, dotenv: dict[str, str], config: dict) -> None:
    """CHAINLIT_AUTH_SECRET é obrigatório quando algum login está ligado."""

    local_login = bool((config.get("auth") or {}).get("local_login_enabled"))
    oauth = bool(setting("OAUTH_GOOGLE_CLIENT_ID", dotenv))
    secret = setting("CHAINLIT_AUTH_SECRET", dotenv)

    if not (local_login or oauth):
        report.add(OK, "login desligado; CHAINLIT_AUTH_SECRET não é exigido")

        return

    if secret:
        report.add(OK, "CHAINLIT_AUTH_SECRET definido para o login ativo")
    else:
        hint = "gere com `chainlit create-secret`"
        report.add(FALHA, f"login ativo sem CHAINLIT_AUTH_SECRET no .env ({hint})")


def schema_tables() -> tuple[str, list[str]]:
    """Extrai (database, tabelas) do DDL versionado."""

    text = SCHEMA_SQL.read_text(encoding="utf-8")
    database = re.search(r"CREATE DATABASE IF NOT EXISTS\s+(\w+)", text)
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS\s+\w+\.(\w+)", text)

    return (database.group(1) if database else "cantabria"), tables


def clickhouse_count(base: str, table: str, user: str, password: str) -> int | None:

    query = urllib.parse.urlencode({"query": f"SELECT count() FROM {table}"})
    headers = {"X-ClickHouse-User": user, "X-ClickHouse-Key": password}
    status, body = http_get(f"{base}/?{query}", headers)

    if status != 200 or not body.strip().isdigit():
        return None

    return int(body.strip())


def check_clickhouse(report: Report, dotenv: dict[str, str]) -> None:
    """Ping HTTP e contagem > 0 em cada tabela do 00_schema.sql."""

    host = setting("CLICKHOUSE_HOST", dotenv, "127.0.0.1")
    port = setting("CLICKHOUSE_PORT", dotenv, "8123")
    base = f"http://{host}:{port}"
    status, body = http_get(f"{base}/ping")

    if status != 200 or "Ok" not in body:
        report.add(FALHA, f"ClickHouse não responde em {base}/ping (stack `core`?)")

        return

    report.add(OK, f"ClickHouse respondeu em {base}/ping")

    database, tables = schema_tables()
    db = setting("CLICKHOUSE_DB", dotenv, database)
    user = setting("CLICKHOUSE_USER", dotenv, "default")
    password = setting("CLICKHOUSE_PASSWORD", dotenv)

    for table in tables:
        name = f"{db}.{table}"
        count = clickhouse_count(base, name, user, password)

        if count is None:
            report.add(FALHA, f"{name}: consulta falhou (tabela ausente/credencial?)")
        elif count > 0:
            report.add(OK, f"{name}: {count} linhas")
        else:
            report.add(FALHA, f"{name}: 0 linhas — rode o seed")


def check_stores(report: Report, dotenv: dict[str, str]) -> None:
    """Stores opcionais (profile `stores`): fora do ar = AVISO."""

    mongo_url = setting("MONGO_URL", dotenv, "mongodb://127.0.0.1:27017")
    mongo = urllib.parse.urlparse(mongo_url)

    if tcp_open(mongo.hostname or "127.0.0.1", mongo.port or 27017):
        report.add(OK, "MongoDB aceita conexão (histórico e auditoria persistidos)")
    else:
        report.add(
            AVISO,
            "MongoDB fora do ar: o app roda com stores em memória "
            "(profile `stores` para persistir)",
        )

    qdrant = setting("QDRANT_URL", dotenv, "http://127.0.0.1:6333")
    status, _ = http_get(f"{qdrant}/readyz")

    if status == 200:
        report.add(OK, "Qdrant pronto")
    else:
        report.add(AVISO, "Qdrant fora do ar (opcional; profile `stores`)")

    minio = setting("MINIO_ENDPOINT", dotenv, "http://127.0.0.1:9002")
    status, _ = http_get(f"{minio}/minio/health/live")

    if status == 200:
        report.add(OK, "MinIO vivo")
    else:
        report.add(AVISO, "MinIO fora do ar (opcional; profile `stores`)")


def check_app(report: Report, dotenv: dict[str, str]) -> None:
    """GET /ready do app: 200 = pronto; sem conexão = AVISO; outro = FALHA."""

    port = setting("CHAINLIT_PORT", dotenv, "8000")
    url = f"http://127.0.0.1:{port}/ready"
    status, body = http_get(url)

    if status is None:
        report.add(AVISO, f"app não está rodando em {url}")
    elif status == 200:
        report.add(OK, f"app pronto em {url}")
    else:
        detail = body[:200].replace("\n", " ")
        report.add(FALHA, f"app degradado em {url} ({status}): {detail}")


def check_langfuse(report: Report) -> None:

    status, _ = http_get("http://127.0.0.1:3000/api/public/health")

    if status == 200:
        report.add(OK, "Langfuse saudável em http://127.0.0.1:3000")
    else:
        report.add(AVISO, "Langfuse fora do ar (opcional; profile `observability`)")


def check_llm(report: Report, config: dict) -> None:
    """Endpoint OpenAI-compatível alcançável; a chave nunca é impressa."""

    llm = config.get("llm") or {}
    base_url = str(llm.get("base_url") or "").rstrip("/")
    api_key = str(llm.get("api_key") or "")

    if not base_url:
        report.add(AVISO, "llm.base_url ausente no config.yaml; endpoint não checado")

        return

    headers = {"Authorization": f"Bearer {api_key}", **(llm.get("headers") or {})}
    status, _ = http_get(f"{base_url}/models", headers)

    if status is None:
        report.add(FALHA, f"endpoint LLM inalcançável em {base_url}")
    elif status in (401, 403):
        report.add(FALHA, f"endpoint LLM recusou a chave ({status}) em {base_url}")
    elif status == 200:
        report.add(OK, f"endpoint LLM respondeu em {base_url}/models")
    else:
        report.add(AVISO, f"endpoint LLM respondeu {status} em {base_url}/models")


def main() -> int:

    os.chdir(REPO_ROOT)
    sys.stdout.reconfigure(encoding="utf-8")  # acentos legíveis no PowerShell
    report = Report()
    dotenv = read_dotenv(REPO_ROOT / ".env")

    print("Pré-voo do Cantábria\n")
    config = check_config(report, dotenv)
    check_dotenv(report, dotenv)
    check_auth_secret(report, dotenv, config)
    check_clickhouse(report, dotenv)
    check_stores(report, dotenv)
    check_app(report, dotenv)
    check_langfuse(report)
    check_llm(report, config)

    verdict = "NO-GO" if report.failures else "GO"
    advice = "Corrija as FALHAs acima." if report.failures else "Pode demonstrar."
    summary = f"{report.failures} falha(s), {report.warnings} aviso(s)"
    print(f"\n{verdict}: {summary}. {advice}")

    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())

"""Regras de dependência entre camadas e contextos (AGENTS.md).

O teste lê os imports de todo `src/` com `ast` e verifica:

1. domínio, aplicação e ports não importam frameworks nem I/O;
2. domínio, aplicação e ports não importam `adapters` nem `entrypoints`;
3. um contexto só fala com outro pelos ports inbound do outro — nunca pelo
   domínio, aplicação, ports outbound ou adapters alheios;
4. o shared kernel é puro (sem framework, sem I/O, sem domínio);
5. o domínio de um contexto não importa `pydantic` (tipagem de LLM é
   preocupação de aplicação/adapter);
6. `cross_cutting` (config, logging, observabilidade, recursos) pode usar
   frameworks, mas domínio, aplicação e ports não o importam — só adapters e
   entrypoints.

As violações que já existem estão em `KNOWN_VIOLATIONS`, para que o teste
comece verde e falhe em qualquer violação NOVA. A lista só pode encolher; um
teste dedicado impede que ela cresça e outro avisa quando uma entrada já não
é necessária, para que seja removida.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

FRAMEWORKS = {
    "chainlit",
    "clickhouse_connect",
    "fastapi",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langfuse",
    "minio",
    "openinference",
    "opentelemetry",
    "pandas",
    "plotly",
    "pymongo",
    "motor",
    "qdrant_client",
    "starlette",
    "structlog",
    "uvicorn",
    "yaml",
}

IO_MODULES = {"os", "pathlib", "socket", "subprocess", "urllib", "http", "io"}

PURE_LAYERS = ("domain", "application", "ports")

# Cada entrada: (módulo que importa, módulo importado, regra). Encolher, não crescer.
#
# `structlog` nas duas peças de aplicação é dívida consciente: os testes
# observam esses logs com `structlog.testing.capture_logs` (que só vê loggers
# do structlog) e os campos estruturados (`refusal_reason`, `rows_without_
# population`) fazem parte do contrato de auditoria. Trocar por `logging` do
# stdlib exigiria um `LoggerPort` próprio.
KNOWN_VIOLATIONS: frozenset[tuple[str, str, str]] = frozenset(
    {
        # --- regra 1: framework em camada pura -------------------------------
        (
            "contexts.financial_analysis.application.commands.execute_pipeline",
            "structlog",
            "framework_in_pure_layer",
        ),
        (
            "contexts.financial_analysis.application.commands.answer_question",
            "structlog",
            "framework_in_pure_layer",
        ),
    }
)


@dataclass(frozen=True)
class Import:
    importer: str
    imported: str


def _module_name(path: Path) -> str:

    relative = path.relative_to(SRC).with_suffix("")
    parts = list(relative.parts)

    if parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts)


def _imports(path: Path) -> list[Import]:

    tree = ast.parse(path.read_text(encoding="utf-8"))
    importer = _module_name(path)
    found: list[Import] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(Import(importer, alias.name) for alias in node.names)

        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append(Import(importer, node.module))

    return found


def _all_imports() -> list[Import]:

    return [
        item
        for path in sorted(SRC.rglob("*.py"))
        if "__pycache__" not in path.parts
        for item in _imports(path)
    ]


def _top(module: str) -> str:

    return module.split(".")[0]


def _context_of(module: str) -> str | None:

    parts = module.split(".")

    return parts[1] if parts[0] == "contexts" and len(parts) > 1 else None


def _layer_of(module: str) -> str | None:

    parts = module.split(".")

    return parts[2] if parts[0] == "contexts" and len(parts) > 2 else None


def _shared_violation(item: Import) -> str | None:

    top = _top(item.imported)

    if top in FRAMEWORKS or top in IO_MODULES:
        return "impure_shared"

    if top in {"contexts", "entrypoints", "cross_cutting"}:
        return "shared_depends_on_domain"

    return None


def _pure_layer_violation(item: Import) -> str | None:

    top = _top(item.imported)

    if top in FRAMEWORKS:
        return "framework_in_pure_layer"

    same_context = _context_of(item.imported) == _context_of(item.importer)

    if same_context and _layer_of(item.imported) == "adapters":
        return "pure_layer_imports_adapters"

    if top == "entrypoints":
        return "context_imports_entrypoints"

    if top == "cross_cutting":
        return "pure_layer_imports_cross_cutting"

    return None


def _cross_context_violation(item: Import) -> str | None:

    imported_ctx = _context_of(item.imported)

    if imported_ctx is None or imported_ctx == _context_of(item.importer):
        return None

    parts = item.imported.split(".")
    via_inbound_port = _layer_of(item.imported) == "ports" and parts[3:4] == ["inbound"]

    return None if via_inbound_port else "cross_context"


def _violation(item: Import) -> str | None:

    if _top(item.importer) == "shared":
        return _shared_violation(item)

    if _context_of(item.importer) is None:
        return None

    importer_layer = _layer_of(item.importer)

    if importer_layer in PURE_LAYERS:
        pure = _pure_layer_violation(item)

        if pure is not None:
            return pure

    if importer_layer == "domain" and _top(item.imported) == "pydantic":
        return "pydantic_in_domain"

    return _cross_context_violation(item)


def _current_violations() -> set[tuple[str, str, str]]:

    return {
        (item.importer, item.imported, rule)
        for item in _all_imports()
        if (rule := _violation(item)) is not None
    }


def test_no_new_dependency_violations() -> None:

    new = _current_violations() - KNOWN_VIOLATIONS

    assert not new, (
        "Novas violações de dependência (ver AGENTS.md; corrija em vez de "
        "adicionar à allow-list):\n"
        + "\n".join(
            f"  {rule}: {importer} -> {imported}"
            for importer, imported, rule in sorted(new)
        )
    )


def test_known_violations_list_only_shrinks() -> None:

    stale = KNOWN_VIOLATIONS - _current_violations()

    assert not stale, (
        "Violações já corrigidas ainda listadas em KNOWN_VIOLATIONS; remova-as:\n"
        + "\n".join(
            f"  {rule}: {importer} -> {imported}"
            for importer, imported, rule in sorted(stale)
        )
    )


def test_known_violations_budget() -> None:

    # Teto absoluto: quem corrige uma violação deve baixar este número.
    assert len(KNOWN_VIOLATIONS) <= 2


@pytest.mark.parametrize("context", ["auth", "financial_calculation"])
def test_leaf_contexts_import_no_other_context(context: str) -> None:

    offenders = {
        (item.importer, item.imported)
        for item in _all_imports()
        if _context_of(item.importer) == context
        and _context_of(item.imported) not in (None, context)
    }

    assert not offenders, offenders

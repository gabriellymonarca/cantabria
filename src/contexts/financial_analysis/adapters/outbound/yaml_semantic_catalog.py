"""Adapter outbound que compila o YAML versionado no grafo do catálogo.

O núcleo só conhece o `SemanticCatalogPort`; o I/O (ler arquivo, validar forma,
traduzir enums) fica aqui. Um arquivo por versão em `data/catalogs/`; a versão
ativa é a de maior número. O mapeamento físico é do adapter de cálculo.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from contexts.financial_analysis.domain.errors import InvalidCatalogError
from contexts.financial_analysis.domain.semantic_catalog import (
    AxisEntry,
    AxisKind,
    CompatibilitySource,
    MethodCompatibility,
    MetricEntry,
    MetricShape,
    NotConfusePair,
    OperationCompatibility,
    Requirement,
    SameField,
    SemanticCatalog,
    ValueEntry,
    WindowEntry,
    WindowRequirement,
)
from contexts.financial_analysis.ports.outbound.semantic_catalog_port import (
    SemanticCatalogPort,
)
from cross_cutting.resources import resolve_data_dir

_CATALOGS_SUBDIR = Path("catalogs")
_VERSION = re.compile(r"v(\d+)")
_COMPILABLE_SCHEMA = 2


class YamlSemanticCatalogAdapter(SemanticCatalogPort):
    """Lê `data/catalogs/*.yaml` e devolve o catálogo tipado."""

    def __init__(self, catalogs_dir: Path | None = None):

        data_dir = resolve_data_dir()
        self._catalogs_dir = catalogs_dir or (data_dir / _CATALOGS_SUBDIR)
        self._by_version: dict[str, SemanticCatalog] = {}
        self._active: SemanticCatalog | None = None

    def load_active(self) -> SemanticCatalog:

        if self._active is not None:
            return self._active

        catalogs = self._load_all()

        if not catalogs:
            raise InvalidCatalogError(f"nenhum catálogo em {self._catalogs_dir}.")

        highest = max(
            catalogs, key=lambda catalog: _version_number(catalog.catalog_version)
        )

        self._active = highest

        return highest

    def load(self, catalog_version: str) -> SemanticCatalog:

        if catalog_version in self._by_version:
            return self._by_version[catalog_version]

        self._load_all()

        if catalog_version in self._by_version:
            return self._by_version[catalog_version]

        if self._legacy_version(catalog_version):
            raise InvalidCatalogError(
                f"catálogo '{catalog_version}' usa schema legado (anterior à v2) e "
                "não é compilável; consulte-o como arquivo histórico."
            )

        raise InvalidCatalogError(f"catálogo '{catalog_version}' não encontrado.")

    def _load_all(self) -> list[SemanticCatalog]:

        if not self._catalogs_dir.is_dir():
            raise InvalidCatalogError(
                f"diretório de catálogos não encontrado: {self._catalogs_dir}."
            )

        catalogs: list[SemanticCatalog] = []

        for path in sorted(self._catalogs_dir.glob("*.yaml")):
            data = _read_yaml(path)
            version = str(data.get("catalog_version", ""))

            if _version_number(version) < _COMPILABLE_SCHEMA:
                continue

            catalogs.append(self._compile(path, data))

        self._by_version.update(
            {catalog.catalog_version: catalog for catalog in catalogs}
        )

        return catalogs

    def _legacy_version(self, catalog_version: str) -> bool:

        for path in sorted(self._catalogs_dir.glob("*.yaml")):
            data = _read_yaml(path)

            if (
                str(data.get("catalog_version", "")) == catalog_version
                and _version_number(catalog_version) < _COMPILABLE_SCHEMA
            ):
                return True

        return False

    def _compile(self, path: Path, data: Any) -> SemanticCatalog:

        try:
            window = data["window"]

            return SemanticCatalog(
                catalog_version=str(data["catalog_version"]),
                locale=str(data["locale"]),
                reference_date=_date(data["reference_date"], "reference_date"),
                window_start=_date(window["start"], "window.start"),
                window_end=_date(window["end"], "window.end"),
                metrics=tuple(_metric(entry) for entry in data.get("metrics") or []),
                axes=tuple(_axis(entry) for entry in data.get("axes") or []),
                values=tuple(_value(entry) for entry in data.get("values") or []),
                windows=tuple(_window(entry) for entry in data.get("windows") or []),
                period_defaults=dict(data.get("period_defaults") or {}),
                methods=tuple(
                    _method(entry)
                    for entry in _compatibility(data).get("methods") or []
                ),
                operations=tuple(
                    _operation(entry)
                    for entry in _compatibility(data).get("operations") or []
                ),
                not_confuse=tuple(
                    _not_confuse(entry) for entry in data.get("not_confuse") or []
                ),
            )
        except InvalidCatalogError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidCatalogError(
                f"catálogo inválido em {path.name}: {error}"
            ) from error


def _read_yaml(path: Path) -> Any:

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise InvalidCatalogError(f"YAML inválido em {path.name}: {error}") from error


def _version_number(version: str) -> int:

    match = _VERSION.fullmatch(version)

    return int(match.group(1)) if match else -1


def _date(value: Any, field: str) -> date:

    if not isinstance(value, str):
        raise InvalidCatalogError(f"'{field}' ausente ou inválido no catálogo.")

    return date.fromisoformat(value)


def _strings(entry: dict[str, Any], field: str) -> tuple[str, ...]:

    return tuple(str(item) for item in entry.get(field) or [])


def _metric(entry: dict[str, Any]) -> MetricEntry:

    return MetricEntry(
        rule_id=str(entry["rule_id"]),
        shape=MetricShape(entry["shape"]),
        unit=str(entry["unit"]),
        synonyms=_strings(entry, "synonyms"),
        macro=bool(entry.get("macro", False)),
    )


def _axis(entry: dict[str, Any]) -> AxisEntry:

    return AxisEntry(
        type=str(entry["type"]),
        level=str(entry["level"]),
        kind=AxisKind(entry["kind"]),
        synonyms=_strings(entry, "synonyms"),
        parent_level=entry.get("parent"),
    )


def _value(entry: dict[str, Any]) -> ValueEntry:

    return ValueEntry(
        type=str(entry["type"]),
        level=str(entry["level"]),
        value_id=str(entry["value_id"]),
        labels=_strings(entry, "labels"),
    )


def _window(entry: dict[str, Any]) -> WindowEntry:

    return WindowEntry(
        id=str(entry["id"]),
        kind=str(entry["kind"]),
        type=str(entry["type"]),
        grain=str(entry["grain"]),
        labels=_strings(entry, "labels"),
        months=entry.get("months"),
    )


def _compatibility(data: dict[str, Any]) -> dict[str, Any]:

    return data.get("compatibility") or {}


def _method(entry: dict[str, Any]) -> MethodCompatibility:

    windows = entry.get("windows")

    return MethodCompatibility(
        method=str(entry["method"]),
        requires_metric_shape=tuple(
            MetricShape(shape) for shape in entry.get("requires_metric_shape") or []
        ),
        forbids_metric_shape=tuple(
            MetricShape(shape) for shape in entry.get("forbids_metric_shape") or []
        ),
        requires=tuple(Requirement(item) for item in entry.get("requires") or []),
        requires_any=tuple(
            Requirement(item) for item in entry.get("requires_any") or []
        ),
        reads=CompatibilitySource(entry["reads"]) if entry.get("reads") else None,
        count=entry.get("count"),
        same=tuple(SameField(item) for item in entry.get("same") or []),
        windows=WindowRequirement(windows) if windows else None,
        min_points=entry.get("min_points"),
        min_levels=entry.get("min_levels"),
        synonyms=_strings(entry, "synonyms"),
    )


def _operation(entry: dict[str, Any]) -> OperationCompatibility:

    forbidden = entry.get("forbidden_rules_metric_shape") or {}

    return OperationCompatibility(
        operation=str(entry["operation"]),
        requires_params=_strings(entry, "requires_params"),
        count=entry.get("count"),
        requires_source=_strings(entry, "requires_source"),
        forbidden_rules_metric_shape={
            str(rule): MetricShape(shape) for rule, shape in forbidden.items()
        },
        params_when={
            str(key): str(value)
            for key, value in (entry.get("params_when") or {}).items()
        },
    )


def _not_confuse(entry: dict[str, Any]) -> NotConfusePair:

    return NotConfusePair(
        term_a=str(entry["term_a"]),
        term_b=str(entry["term_b"]),
        note=entry.get("note"),
    )

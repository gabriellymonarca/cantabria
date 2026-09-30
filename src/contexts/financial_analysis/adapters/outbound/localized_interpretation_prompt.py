"""Adapter outbound que monta o system prompt da interpretação.

I/O fica aqui: o núcleo (use case) só conhece o port. O adapter lê o contrato
canônico (`base.md`), a superfície localizada (`examples.{locale}.md` e
`messages.{locale}.md`) e o catálogo governado do locale, e renderiza o texto
final substituindo os placeholders.

O contrato é neutro; o catálogo e os exemplos variam por locale
(`semantic_catalog_<locale>.yaml` e os overlays do locale).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from contexts.financial_analysis.domain.windows import WindowKind, resolve_window
from contexts.financial_analysis.ports.outbound.interpretation_prompt_port import (
    InterpretationPromptPort,
)
from cross_cutting.resources import resolve_data_dir

_PROMPTS_SUBDIR = Path("prompts") / "interpretation" / "v1"
_CATALOGS_SUBDIR = Path("catalogs")


class PromptConfigurationError(RuntimeError):
    """Falta o contrato, o overlay do locale ou o catálogo correspondente."""


class LocalizedInterpretationPromptAdapter(InterpretationPromptPort):
    """Monta o prompt a partir do contrato canônico e do catálogo do locale."""

    def __init__(
        self,
        prompts_dir: Path | None = None,
        catalogs_dir: Path | None = None,
    ):

        data_dir = resolve_data_dir()
        self._prompts_dir = prompts_dir or (data_dir / _PROMPTS_SUBDIR)
        self._catalogs_dir = catalogs_dir or (data_dir / _CATALOGS_SUBDIR)
        self._cache: dict[str, str] = {}

    def build_system_prompt(
        self, locale: str, reference_date: date | None = None
    ) -> str:

        catalog = _load_catalog(self._catalogs_dir, locale)
        effective_date = reference_date or _parse_date(
            catalog.get("reference_date"), "reference_date"
        )

        cache_key = f"{locale}@{effective_date.isoformat()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        base = _read(self._prompts_dir / "base.md")
        examples = _read(self._prompts_dir / f"examples.{locale}.md")
        messages = _read(self._prompts_dir / f"messages.{locale}.md")

        window = catalog.get("window") or {}
        replacements = {
            "{{LOCALE}}": locale,
            "{{CATALOG_VERSION}}": str(catalog.get("catalog_version", "")),
            "{{REFERENCE_DATE}}": effective_date.isoformat(),
            "{{WINDOW_START}}": str(window.get("start", "")),
            "{{WINDOW_END}}": effective_date.isoformat(),
            "{{CATALOG}}": _render_catalog(catalog, effective_date),
            "{{EXAMPLES}}": examples.strip(),
            "{{MESSAGES}}": messages.strip(),
        }

        prompt = base
        for token, value in replacements.items():
            prompt = prompt.replace(token, value)

        self._cache[cache_key] = prompt

        return prompt


def _read(path: Path) -> str:

    if not path.is_file():
        raise PromptConfigurationError(f"Arquivo de prompt não encontrado: {path}")

    return path.read_text(encoding="utf-8")


def _load_catalog(catalogs_dir: Path, locale: str) -> dict[str, Any]:
    if not catalogs_dir.is_dir():
        raise PromptConfigurationError(
            f"Diretório de catálogos não encontrado: {catalogs_dir}"
        )

    candidates = [
        data
        for path in sorted(catalogs_dir.glob("*.yaml"))
        for data in [yaml.safe_load(path.read_text(encoding="utf-8"))]
        if isinstance(data, dict) and data.get("locale") == locale
    ]

    if not candidates:
        raise PromptConfigurationError(
            f"Nenhum catálogo com locale '{locale}' em {catalogs_dir}."
        )

    return max(
        candidates,
        key=lambda data: _version_number(str(data.get("catalog_version", ""))),
    )


def _version_number(version: str) -> int:

    match = re.fullmatch(r"v(\d+)", version)

    return int(match.group(1)) if match else -1


def _render_catalog(catalog: dict[str, Any], reference_date: date) -> str:

    sections: list[str] = []

    metrics = catalog.get("metrics") or []
    if metrics:
        lines = [
            f"- `{metric['rule_id']}` (shape: `{metric.get('shape', '')}`, "
            f"unit: `{metric.get('unit', '')}`){_synonyms(metric)}{_macro(metric)}"
            for metric in metrics
        ]
        sections.append("### Métricas (`rule_id`)\n" + "\n".join(lines))

    axes = catalog.get("axes") or []
    if axes:
        lines = [
            f"- `{axis['type']}.{axis['level']}`{_kind(axis)}{_synonyms(axis)}"
            for axis in axes
        ]
        sections.append(
            "### Eixos e recortes (`subjects` / `sample`)\n" + "\n".join(lines)
        )

    values = catalog.get("values") or []
    if values:
        lines = [
            f"- `{value['type']}.{value['level']}` = `{value['value_id']}`"
            f"{_labels(value)}"
            for value in values
        ]
        sections.append("### Valores de recorte (`value_id`)\n" + "\n".join(lines))

    confusions = catalog.get("not_confuse") or []
    if confusions:
        lines = [
            f"- `{pair['term_a']}` NÃO é `{pair['term_b']}`; são dimensões distintas."
            for pair in confusions
        ]
        sections.append("### Não confundir\n" + "\n".join(lines))

    windows = catalog.get("windows") or []
    if windows:
        lines = [_render_window(window, reference_date) for window in windows]
        sections.append("### Janelas nomeadas (datas prontas)\n" + "\n".join(lines))

    defaults = catalog.get("period_defaults") or {}
    if defaults:
        lines = [f"- {kind}: `{window_id}`" for kind, window_id in defaults.items()]
        sections.append("### Janelas padrão (período ausente)\n" + "\n".join(lines))

    compatibility = catalog.get("compatibility") or {}
    methods = compatibility.get("methods") or []
    operations = compatibility.get("operations") or []
    if methods or operations:
        lines = [_method_rule(entry) for entry in methods]
        lines += [_operation_rule(entry) for entry in operations]
        sections.append("### Compatibilidade (método × métrica)\n" + "\n".join(lines))

    return "\n\n".join(sections)


def _kind(entry: dict[str, Any]) -> str:

    return " (ordinal)" if entry.get("kind") == "ordinal" else ""


def _method_rule(entry: dict[str, Any]) -> str:

    parts: list[str] = []
    forbidden = entry.get("forbids_metric_shape") or []
    if forbidden:
        parts.append("proibido em " + "/".join(forbidden))
    requires = entry.get("requires") or []
    if requires:
        parts.append("exige " + "/".join(requires))
    requires_any = entry.get("requires_any") or []
    if requires_any:
        parts.append("exige um de " + "/".join(requires_any))
    if entry.get("count"):
        parts.append(f"exatamente {entry['count']} fontes")
    if entry.get("reads"):
        parts.append(f"lê {entry['reads']}")
    if entry.get("same"):
        parts.append("mesmos " + "/".join(entry["same"]))
    if entry.get("windows"):
        parts.append(str(entry["windows"]))
    if entry.get("min_points"):
        parts.append(f"mínimo {entry['min_points']} pontos")
    parts.extend(_method_tail(entry))

    return f"- `{entry['method']}`" + (": " + "; ".join(parts) if parts else "")


def _method_tail(entry: dict[str, Any]) -> list[str]:
    """Os sinais de negócio do método: níveis mínimos e sinônimos."""

    tail: list[str] = []

    if entry.get("min_levels"):
        tail.append(f"mínimo {entry['min_levels']} níveis")

    if entry.get("synonyms"):
        tail.append("sinônimos " + ", ".join(entry["synonyms"]))

    return tail


def _operation_rule(entry: dict[str, Any]) -> str:

    parts: list[str] = []
    if entry.get("requires_params"):
        parts.append("exige param " + "/".join(entry["requires_params"]))
    if entry.get("count"):
        parts.append(f"exatamente {entry['count']} refs")
    if entry.get("requires_source"):
        parts.append("lê " + " + ".join(entry["requires_source"]))
    forbidden = entry.get("forbidden_rules_metric_shape") or {}
    if forbidden:
        parts.append("proibido em ratio para " + "/".join(forbidden))
    params_when = entry.get("params_when") or {}
    if params_when:
        parts.append(
            "quando "
            + ", ".join(f"{key}={value}" for key, value in params_when.items())
        )

    return f"- `{entry['operation']}`" + (": " + "; ".join(parts) if parts else "")


def _synonyms(entry: dict[str, Any]) -> str:

    synonyms = entry.get("synonyms") or []

    return f" — sinônimos: {', '.join(synonyms)}" if synonyms else ""


def _macro(entry: dict[str, Any]) -> str:

    return (
        " — apenas `total.total`, sem recorte de negócio" if entry.get("macro") else ""
    )


def _labels(entry: dict[str, Any]) -> str:

    labels = entry.get("labels") or []

    return f" — rótulos: {', '.join(labels)}" if labels else ""


def _window_labels(entry: dict[str, Any]) -> str:

    labels = entry.get("labels") or []

    return f' — "{", ".join(labels)}"' if labels else ""


def _render_window(entry: dict[str, Any], reference_date: date) -> str:

    resolved = resolve_window(
        WindowKind(entry["kind"]),
        reference_date,
        entry.get("months"),
    )

    return (
        f"- `{entry['id']}`: {resolved.start.isoformat()} .. "
        f"{resolved.end.isoformat()} ({entry['type']}, {entry['grain']})"
        f"{_window_labels(entry)}"
    )


def _parse_date(value: Any, field: str) -> date:

    if not isinstance(value, str):
        raise PromptConfigurationError(f"'{field}' ausente ou inválido no catálogo.")

    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise PromptConfigurationError(
            f"'{field}' não é uma data ISO válida: {value!r}."
        ) from error

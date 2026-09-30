"""Capacidades do Cantábria em pt-BR, geradas do catálogo.

Gera a descrição de escopo a partir do `SemanticCatalog`; a mesma fonte
alimenta os starters da tela inicial e a resposta da rota de capacidade. Pura
por construção: lê somente o catálogo, sem I/O, LLM ou import de outro
contexto.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from contexts.financial_analysis.domain.analysis_plan import PresentationType
from contexts.financial_analysis.domain.semantic_catalog import SemanticCatalog

_MONTH_ABBREVIATIONS = (
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
)

_IDENTITY_METHOD = "null"

# `null` é o método identidade ("só o valor") e não entra na lista. A v3 do
# catálogo publica `synonyms` de método; o primeiro sinônimo é o rótulo de
# negócio. Os mapas abaixo cobrem catálogo sem sinônimos; um id desconhecido
# cai no próprio id legível.
_METHOD_LABELS = {
    "mean": "média",
    "median": "mediana",
    "mode": "moda",
    "std": "desvio padrão",
    "dispersion": "dispersão",
    "variation": "variação entre janelas",
    "trend": "tendência",
    "share": "participação",
    "correlation": "correlação",
    "outlier": "outliers",
}

_OPERATION_LABELS = {
    "ranking": "ranking",
    "comparison": "comparação",
    "cumulative_share": "participação acumulada",
    "selection": "seleção",
    "pivot": "tabela dinâmica",
    "decomposition": "decomposição",
}

# Formas de apresentação do catálogo fechado, no rótulo de negócio.
_PRESENTATION_LABELS: dict[PresentationType, str] = {
    PresentationType.TABLE: "tabela",
    PresentationType.BAR: "gráfico de barras",
    PresentationType.LINE: "gráfico de linhas",
    PresentationType.RANKING_BAR: "ranking",
}

_TEXT_FORMAT = "texto"

_PROFITABILITY = "profitability"
_BALANCE = "outstanding_balance"
_CDI = "cdi_rate"
_SEGMENT = ("customer_segmentation", "segment")


def describe_capabilities(catalog: SemanticCatalog) -> str:
    """Descreve, em pt-BR, o que o catálogo permite perguntar.

    Métricas (pelos `synonyms`), recortes (eixos), métodos estatísticos e
    operações, formatos de saída e a faixa de janelas (`labels` +
    `window_start`/`window_end`). A saída usa rótulos de negócio, sem números
    de dado, e é estável para o mesmo catálogo. Reusada pela rota de capacidade
    e pelos starters.
    """

    metrics = _capitalize(_join(_metric_labels(catalog)))
    axes = _join(_axis_labels(catalog))
    methods = _join(_method_labels(catalog))
    operations = _join(_operation_labels(catalog))
    windows = _join(_window_labels(catalog))
    window_range = (
        f"{month_year(catalog.window_start)} e {month_year(catalog.window_end)}"
    )

    lines = ["Posso responder, por exemplo, sobre:", f"- {metrics}"]

    if axes:
        lines.append(f"- Recortes por {axes}")

    if methods:
        lines.append(f"- Análises: {methods}")

    if operations:
        lines.append(f"- Operações: {operations}")

    lines.append(f"- Formatos: {_join(_presentation_labels())}")

    windows_line = f"- Janelas entre {window_range}"

    if windows:
        windows_line += f": {windows}"

    lines.append(windows_line)

    return "\n".join(lines)


def starter_questions(catalog: SemanticCatalog) -> tuple[tuple[str, str], ...]:
    """Cartões da tela inicial: (rótulo curto, pergunta completa).

    Gerados do catálogo — rótulos de métrica e eixo pelos `synonyms` — e só
    para o que o catálogo tem: a comparação com o CDI aparece apenas quando
    `cdi_rate` existe. O último cartão abre a rota de capacidade.
    """

    starters: list[tuple[str, str]] = []
    profitability = _metric_label(catalog, _PROFITABILITY)
    balance = _metric_label(catalog, _BALANCE)
    segment = _axis_label(catalog, *_SEGMENT)

    if profitability and segment:
        starters.append(
            (
                f"{_capitalize(segment)} mais rentável",
                f"Qual o {segment} mais rentável nos últimos 12 meses?",
            )
        )

    if balance:
        starters.append(
            (
                f"Evolução da {balance}",
                f"Como evoluiu a {balance} nos últimos 6 meses?",
            )
        )

    cdi = _metric_label(catalog, _CDI)

    if profitability and cdi:
        starters.append(
            (
                f"{_capitalize(profitability)} × {cdi.upper()}",
                f"Compare a {profitability} com o {cdi.upper()} em "
                f"{catalog.window_end.year}",
            )
        )

    starters.append(("O que você faz?", "O que você sabe fazer?"))

    return tuple(starters)


def _metric_label(catalog: SemanticCatalog, rule_id: str) -> str | None:
    """Primeiro sinônimo da métrica; `None` quando ela não está no catálogo."""

    entry = catalog.metric(rule_id)

    if entry is None:
        return None

    return entry.synonyms[0] if entry.synonyms else _humanize(entry.rule_id)


def _axis_label(catalog: SemanticCatalog, axis_type: str, level: str) -> str | None:
    """Primeiro sinônimo do eixo; `None` quando ele não está no catálogo."""

    entry = catalog.axis(axis_type, level)

    if entry is None:
        return None

    return entry.synonyms[0] if entry.synonyms else _humanize(entry.level)


def _presentation_labels() -> list[str]:
    """Texto primeiro; depois as formas do catálogo fechado, na ordem do mapa."""

    return [_TEXT_FORMAT, *_PRESENTATION_LABELS.values()]


def _metric_labels(catalog: SemanticCatalog) -> list[str]:
    """Rótulo de negócio de cada métrica: primeiro sinônimo, senão o rule_id."""

    return [
        metric.synonyms[0] if metric.synonyms else _humanize(metric.rule_id)
        for metric in catalog.metrics
    ]


def _axis_labels(catalog: SemanticCatalog) -> list[str]:
    """Sinônimos dos eixos, sem repetição: eixos sem rótulo (total) ficam fora."""

    return _dedupe(axis.synonyms[0] for axis in catalog.axes if axis.synonyms)


def _method_labels(catalog: SemanticCatalog) -> list[str]:
    """Métodos, sem o identidade, no rótulo de negócio (sinônimo da v3)."""

    return [
        rule.synonyms[0]
        if rule.synonyms
        else _METHOD_LABELS.get(rule.method, _humanize(rule.method))
        for rule in catalog.methods
        if rule.method != _IDENTITY_METHOD
    ]


def _operation_labels(catalog: SemanticCatalog) -> list[str]:
    """Operações no rótulo de negócio."""

    return [
        _OPERATION_LABELS.get(rule.operation, _humanize(rule.operation))
        for rule in catalog.operations
    ]


def _window_labels(catalog: SemanticCatalog) -> list[str]:
    """Primeiro label de cada janela; sem label, o id legível."""

    return [
        window.labels[0] if window.labels else _humanize(window.id)
        for window in catalog.windows
    ]


def month_year(value: date) -> str:
    """Data no formato que o usuário lê em perguntas: `set/2024`."""

    return f"{_MONTH_ABBREVIATIONS[value.month - 1]}/{value.year}"


def _humanize(identifier: str) -> str:
    """Id fechado do catálogo virando termo legível, quando não há rótulo."""

    return identifier.replace("_", " ")


def _join(terms: Iterable[str]) -> str:
    """Lista em pt-BR: `a, b e c` (sem vírgula antes do e)."""

    values = list(terms)

    if not values:
        return ""

    if len(values) == 1:
        return values[0]

    return ", ".join(values[:-1]) + " e " + values[-1]


def _dedupe(terms: Iterable[str]) -> list[str]:
    """Preserva a ordem do catálogo e remove rótulos repetidos."""

    seen: set[str] = set()
    unique: list[str] = []

    for term in terms:
        if term in seen:
            continue

        seen.add(term)
        unique.append(term)

    return unique


def _capitalize(text: str) -> str:

    return text[:1].upper() + text[1:] if text else text

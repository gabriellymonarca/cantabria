"""Apresentação determinística do insight antes de chegar ao usuário.

O LLM redige sobre o resultado verificado, mas o texto final passa por aqui:
os identificadores internos (ids de plano, método e operação, chaves
qualificadas, versões, trace, `document_id`) saem, e todo número é reescrito
em pt-BR com a precisão da sua unidade — taxa e moeda com 2 casas, contagem
inteira. A validação confere que cada número citado existe no resultado, com
tolerância de arredondamento de exibição.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from contexts.financial_analysis.domain.analysis_result import (
    SMALL_CELL_K,
    AnalysisResult,
    MethodResult,
    MethodValue,
    OperationResult,
)

_TOLERANCE = Decimal("0.006")

_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<symbol>R\$\s*)?(?P<body>-?\d(?:[\d.,]*\d)?)"
    r"(?P<percent>\s*%)?(?![A-Za-z0-9_])"
)
_DATE_PATTERN = re.compile(
    r"\b\d{4}-\d{2}(?:-\d{2})?\b|\b\d{2}/\d{2}/\d{4}\b|\b\d{2}/\d{4}\b"
)
_YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}\Z")
_QUALIFIED_VALUE_PATTERN = re.compile(
    r"\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\s*=\s*([^,;\n\]\)]+)"
)
_QUALIFIED_KEY_PATTERN = re.compile(r"\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_ID_TOKEN_PATTERN = re.compile(r"\b[som]\d+\b")
_CALC_PATTERN = re.compile(r"\bcalc_[A-Za-z0-9_]+\b")

_INTERNAL_LABELS = (
    "analysis_plan_id",
    "catalog_version",
    "dataset_version",
    "trace_id",
    "statistical_method",
    "calculation_plan_ids",
    "statistic_refs",
    "document_id",
    "subjects",
    "values",
    "refs",
)

_WINDOW_LABELS = {
    "reference_snapshot": "posição atual",
    "last_closed_month": "último mês",
    "last_3_months": "últimos 3 meses",
    "last_6_months": "últimos 6 meses",
    "last_12_months": "últimos 12 meses",
    "current_year": "este ano",
    "previous_year": "ano passado",
}

_RULE_LABELS = {
    "profitability": "rentabilidade",
    "outstanding_balance": "carteira",
    "contract_count": "número de contratos",
    "customer_count": "número de clientes",
}

_REASON_LABELS = {
    "no_observations": "sem observações",
    "small_cell": "célula suprimida",
    "not_computable": "não calculável",
}

# Apresentações do catálogo fechado, no rótulo de negócio. `bar`, `line`,
# `table` (e `share`, `mean`, ...) são palavras comuns: só são trocadas quando
# vêm entre crases — a forma em que o planner as copia do prompt. Tokens com
# underscore (`ranking_bar`, `cumulative_share`) são inequívocos e trocam
# sempre.
_PRESENTATION_LABELS = {
    "ranking_bar": "gráfico de ranking",
    "bar": "gráfico de barras",
    "line": "gráfico de linhas",
    "table": "tabela",
}

_OPERATION_LABELS = {
    "cumulative_share": "participação acumulada",
}

_PROMPT_PHRASES = {
    "catálogo fechado": "catálogo",
    "catalogo fechado": "catálogo",
}

_LEVEL_LABELS = {
    "segment": "segmento",
    "segment_group": "grupo de segmento",
    "person_type": "tipo de pessoa",
    "subsegment": "subsegmento",
    "subsegment_group": "grupo de subsegmento",
    "relationship_depth": "vinculação",
    "principality_depth": "principalidade",
    "product": "produto",
    "product_group": "grupo de produto",
    "subproduct": "subproduto",
    "total": "total",
}

_SIZE_BEFORE = {"último", "últimos", "ultimo", "ultimos", "top"}
_SIZE_AFTER = {
    "mês",
    "meses",
    "mes",
    "ano",
    "anos",
    "trimestre",
    "trimestres",
    "semestre",
    "semestres",
    "dia",
    "dias",
}

# "10 clientes" é o k da regra small-cell citado na ressalva, não um número do
# resultado. Só o próprio k é tolerado: qualquer outra contagem de clientes
# continua a ter de existir no resultado (`customer_count`).
_SMALL_CELL_K = Decimal(SMALL_CELL_K)
_THRESHOLD_AFTER = {"cliente", "clientes"}


_UNIT_LABELS = {
    "decimal_rate": "taxa",
    "currency": "moeda",
    "count": "contagem",
}

_METHOD_LABELS = {
    "null": "valor",
    "mean": "média",
    "median": "mediana",
    "mode": "moda",
    "std": "desvio padrão",
    "dispersion": "dispersão",
    "variation": "variação",
    "trend": "tendência",
    "share": "participação",
    "correlation": "correlação",
    "outlier": "outlier",
}

_VALUE_KEY_LABELS = {
    "value": "valor",
    "absolute": "absoluta",
    "percent": "percentual",
    "mean": "média",
    "median": "mediana",
    "std": "desvio padrão",
    "variance": "variância",
    "min": "mínimo",
    "max": "máximo",
    "q1": "q1",
    "q3": "q3",
    "iqr": "iqr",
    "fence_low": "limite inferior",
    "fence_high": "limite superior",
    "outliers": "outliers",
}

_TOTAL_LABEL = "Total"
_EMPTY_CELL = "—"
_SUBJECT_SEPARATOR = " · "


class InsightNumberError(ValueError):
    """Algum número do insight não existe no resultado verificado.

    `numbers` carrega os trechos citados sem lastro, como apareceram no texto,
    para que o pipeline peça UMA regeneração apontando exatamente o que rejeitou.
    """

    def __init__(self, numbers: Sequence[str]):

        self.numbers = tuple(numbers)

        super().__init__(
            f"números sem lastro no resultado verificado: {', '.join(self.numbers)}."
        )


@dataclass(frozen=True)
class _Mention:
    start: int
    end: int
    value: Decimal
    percent: bool
    currency: bool


@dataclass(frozen=True)
class _Verified:
    value: Decimal
    unit: str | None
    key: str | None


def format_number(
    value: Decimal | int,
    unit: str | None,
    *,
    key: str | None = None,
    percent: bool = False,
    with_currency_symbol: bool = False,
) -> str:
    """Escreve um número em pt-BR com a precisão da sua unidade."""

    effective = _effective_unit(value, unit, key=key)

    if percent and effective == "decimal_rate":
        return _decimal_places(_decimal(value) * 100, 2) + "%"

    if effective == "count":
        return _integer(value)

    number = _decimal_places(_decimal(value), 2)

    if with_currency_symbol and effective == "currency":
        return f"R$ {number}"

    return number


def sanitize_user_text(text: str, *, extra_ids: Collection[str] = ()) -> str:
    """Remove identificadores internos do texto que chega ao usuário."""

    if not text:
        return text

    cleaned = _remove_labeled(text)
    cleaned = _replace_key_values(cleaned)
    cleaned = _replace_qualified_keys(cleaned)
    cleaned = _replace_internal_tokens(cleaned)
    cleaned = _remove_known_ids(cleaned, extra_ids)
    cleaned = _clean_references(cleaned)

    return _collapse(cleaned)


def format_insight_numbers(
    text: str,
    result: AnalysisResult,
    *,
    tolerance: Decimal = _TOLERANCE,
) -> str:
    """Reescreve os números do insight em pt-BR com a precisão da unidade."""

    if not text:
        return text

    verified = _verified_numbers(result)
    mentions = _mentions(text)

    if not mentions:
        return text

    parts: list[str] = []
    cursor = 0

    for mention in mentions:
        entry = _match(mention, verified, tolerance)

        if entry is not None:
            rendered = format_number(
                entry.value,
                entry.unit,
                key=entry.key,
                percent=mention.percent,
                with_currency_symbol=mention.currency,
            )
        else:
            rendered = _plain_mention(mention)

        parts.append(text[cursor : mention.start])
        parts.append(rendered)
        cursor = mention.end

    parts.append(text[cursor:])

    return "".join(parts)


def validate_insight_numbers(
    text: str,
    result: AnalysisResult,
    *,
    tolerance: Decimal = _TOLERANCE,
) -> None:
    """Confere que todo número citado existe no resultado, com tolerância."""

    if not text:
        return

    verified = _verified_numbers(result)
    unknown = [
        text[mention.start : mention.end]
        for mention in _mentions(text)
        if _match(mention, verified, tolerance) is None
    ]

    if unknown:
        raise InsightNumberError(unknown)


def present_insight(
    text: str,
    result: AnalysisResult,
    *,
    document_ids: Sequence[str] = (),
) -> str:
    """Sanitiza ids e formata números do texto final do insight."""

    if not text:
        return text

    cleaned = sanitize_user_text(text, extra_ids=_result_ids(result, document_ids))

    return format_insight_numbers(cleaned, result)


def render_verified_table(result: AnalysisResult) -> str:
    """Tabela Markdown determinística dos números verificados, um por linha de
    método. É o que o usuário recebe quando o redator falha no lastro: nenhum
    número aqui passou por um LLM."""

    with_period = any(
        row.period is not None
        for method in result.statistical_method
        for row in method.values
    )
    period_header = ["Período"] if with_period else []
    header = ["Entidade", *period_header, "Método", "Valor", "Unidade"]
    lines = [_table_row(header), _table_row(["---"] * len(header))]

    for method in result.statistical_method:
        for row in sorted(method.values, key=_table_sort_key):
            cells = [entity_label(row.subjects)]

            if with_period:
                cells.append(row.period or _EMPTY_CELL)

            cells.append(method_label(method.method))
            lines.append(_table_row([*cells, *_value_cells(row, method.unit)]))

    return "\n".join(lines)


def entity_label(subjects: dict[str, str | None]) -> str:
    """Rótulo de negócio dos `subjects` de uma linha."""

    labels = [value for _, value in sorted(subjects.items()) if value is not None]

    return _SUBJECT_SEPARATOR.join(labels) if labels else _TOTAL_LABEL


def method_label(method: str) -> str:
    """Rótulo pt-BR do método; id fora do mapa fica como veio."""

    return _METHOD_LABELS.get(method, method)


def value_key_label(key: str) -> str:
    """Rótulo pt-BR da medida de uma linha com mais de um número."""

    return _VALUE_KEY_LABELS.get(key, key)


def display_unit(unit: str | None, *, key: str | None = None) -> str | None:
    """Rótulo pt-BR da unidade efetiva de um número (`taxa`, `moeda`, ...)."""

    effective = _key_unit(key, unit)

    if effective is None:
        return None

    return _UNIT_LABELS.get(effective, effective)


def _table_row(cells: Sequence[str]) -> str:

    return "| " + " | ".join(cells) + " |"


def _table_sort_key(row: MethodValue) -> tuple[str, tuple[tuple[str, str], ...]]:

    return (
        row.period or "",
        tuple(sorted((key, value or "") for key, value in row.subjects.items())),
    )


def _value_cells(row: MethodValue, unit: str | None) -> list[str]:

    if row.undefined is not None:
        reason = _REASON_LABELS.get(str(row.undefined), str(row.undefined))

        return [f"[indefinido: {reason}]", _EMPTY_CELL]

    numbers = [
        (key, number)
        for key, number in sorted(row.values.items())
        if number is not None
    ]

    if not numbers:
        return [_EMPTY_CELL, _EMPTY_CELL]

    if len(numbers) == 1:
        key, number = numbers[0]

        return [_format_cell(number, unit, key), _unit_label(key, unit)]

    rendered = "; ".join(
        f"{value_key_label(key)} {_format_cell(number, unit, key)}"
        for key, number in numbers
    )

    return [rendered, _unit_label(None, unit)]


def _format_cell(number: Decimal | int, unit: str | None, key: str) -> str:
    """Taxa vai em percentual (`0,34%`), preservando taxas pequenas com duas
    casas. `percent` só tem efeito quando a unidade efetiva é `decimal_rate`."""

    return format_number(number, _key_unit(key, unit), key=key, percent=True)


def _unit_label(key: str | None, unit: str | None) -> str:

    label = display_unit(unit, key=key)

    return label if label is not None else _EMPTY_CELL


def _effective_unit(
    value: Decimal | int,
    unit: str | None,
    *,
    key: str | None = None,
) -> str | None:

    if key in ("outliers", "rank"):
        return "count"

    if key == "percent":
        return "decimal_rate"

    if unit in ("decimal_rate", "currency", "count"):
        return unit

    if isinstance(value, int):
        return "count"

    return None


def _decimal(number: Decimal | int) -> Decimal:

    if isinstance(number, Decimal):
        return number

    return Decimal(number)


def _integer(value: Decimal | int) -> str:

    quantum = _decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP)

    return _group_thousands(format(quantum, "f"))


def _decimal_places(value: Decimal, places: int) -> str:

    quantum = Decimal(1).scaleb(-places)
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    plain = format(abs(rounded), "f")
    head, _, tail = plain.partition(".")
    padded = (tail + "0" * places)[:places]
    sign = "-" if rounded.is_signed() and rounded != 0 else ""

    return f"{sign}{_group_thousands(head)},{padded}"


def _group_thousands(head: str) -> str:

    if len(head) <= 3:
        return head

    parts: list[str] = []

    while len(head) > 3:
        parts.append(head[-3:])
        head = head[:-3]

    parts.append(head)

    return ".".join(reversed(parts))


def _plain_mention(mention: _Mention) -> str:

    integral = mention.value == mention.value.to_integral_value()

    if not mention.percent and not mention.currency and integral:
        return _integer(mention.value)

    number = _decimal_places(mention.value, 2)

    if mention.percent:
        return f"{number}%"

    if mention.currency:
        return f"R$ {number}"

    return number


def _verified_numbers(result: AnalysisResult) -> list[_Verified]:

    found: list[_Verified] = []

    for method in result.statistical_method:
        found.extend(_method_numbers(method))

    for operation in result.operations:
        found.extend(_operation_numbers(operation))

    return found


def _method_numbers(method: MethodResult) -> list[_Verified]:

    found: list[_Verified] = []

    for row in method.values:
        if row.undefined is not None:
            continue

        for key, number in row.values.items():
            if number is None:
                continue

            found.append(_Verified(_decimal(number), _key_unit(key, method.unit), key))

    return found


def _operation_numbers(operation: OperationResult) -> list[_Verified]:

    found: list[_Verified] = []

    for row in operation.values:
        if row.undefined is not None:
            continue

        for key, number in row.values.items():
            if number is None:
                continue

            found.append(
                _Verified(_decimal(number), _key_unit(key, operation.unit), key)
            )

        if row.rank is not None:
            found.append(_Verified(Decimal(row.rank), "count", "rank"))

    return found


def _key_unit(key: str | None, unit: str | None) -> str | None:

    if key == "percent":
        return "decimal_rate"

    if key in ("outliers", "rank"):
        return "count"

    return unit


def _match(
    mention: _Mention,
    verified: Sequence[_Verified],
    tolerance: Decimal,
) -> _Verified | None:

    best: _Verified | None = None
    best_gap: Decimal | None = None

    for entry in verified:
        gaps = [abs(entry.value - mention.value)]

        if mention.percent and entry.unit == "decimal_rate":
            gaps.append(abs(entry.value - mention.value / 100))

        gap = min(gaps)

        if gap <= tolerance and (best_gap is None or gap < best_gap):
            best = entry
            best_gap = gap

    return best


def _mentions(text: str) -> list[_Mention]:

    spans = [match.span() for match in _DATE_PATTERN.finditer(text)]
    found: list[_Mention] = []

    for match in _NUMBER_PATTERN.finditer(text):
        if _inside(match.start(), spans):
            continue

        value = _parse_body(match.group("body"))

        if value is None:
            continue

        if _YEAR_PATTERN.fullmatch(match.group("body")):
            continue

        if _is_window_size(text, match, value):
            continue

        found.append(
            _Mention(
                match.start(),
                match.end(),
                value,
                bool((match.group("percent") or "").strip()),
                bool(match.group("symbol")),
            )
        )

    return found


def _inside(position: int, spans: list[tuple[int, int]]) -> bool:

    return any(start <= position < end for start, end in spans)


def _parse_body(body: str) -> Decimal | None:

    negative = body.startswith("-")
    digits = body[1:] if negative else body

    if "." in digits and "," in digits:
        if digits.rfind(".") > digits.rfind(","):
            digits = digits.replace(",", "")
        else:
            digits = digits.replace(".", "").replace(",", ".")
    elif "," in digits:
        if digits.count(",") == 1:
            digits = digits.replace(",", ".")
        else:
            digits = digits.replace(",", "")
    elif "." in digits:
        if digits.startswith("0."):
            pass
        elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", digits):
            digits = digits.replace(".", "")

    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None

    return -value if negative else value


def _is_window_size(text: str, match: re.Match[str], value: Decimal) -> bool:

    if value != value.to_integral_value():
        return False

    if not Decimal(1) <= value <= Decimal(120):
        return False

    before = text[max(0, match.start() - 14) : match.start()].rstrip().lower()
    after = text[match.end() : match.end() + 14].lstrip().lower()
    previous = before.rsplit(None, 1)[-1].rstrip(",.:;") if before.split() else ""
    following = after.split(None, 1)[0].rstrip(",.:;") if after.split() else ""

    if value == _SMALL_CELL_K and following in _THRESHOLD_AFTER:
        return True

    return previous in _SIZE_BEFORE or following in _SIZE_AFTER


def _remove_labeled(text: str) -> str:

    cleaned = text

    for label in _INTERNAL_LABELS:
        cleaned = re.sub(
            rf"\b{label}\b\s*[:=]\s*(?:\[[^\]]*\]|\{{[^}}]*\}}"
            r'|"[^"]*"|\'[^\']*\'|\S+)',
            "",
            cleaned,
        )
        cleaned = re.sub(rf"\b{label}\b", "", cleaned)

    return cleaned


def _replace_key_values(text: str) -> str:

    return _QUALIFIED_VALUE_PATTERN.sub(lambda match: match.group(1).strip(), text)


def _replace_qualified_keys(text: str) -> str:

    return _QUALIFIED_KEY_PATTERN.sub(_friendly_level, text)


def _friendly_level(match: re.Match[str]) -> str:

    level = match.group(0).rsplit(".", 1)[-1]

    return _LEVEL_LABELS.get(level, level.replace("_", " "))


def _replace_internal_tokens(text: str) -> str:

    cleaned = _replace_backticked_tokens(text)

    for token, label in {**_WINDOW_LABELS, **_RULE_LABELS, **_REASON_LABELS}.items():
        cleaned = re.sub(rf"\b{re.escape(token)}\b", label, cleaned)

    for token, label in {**_PRESENTATION_LABELS, **_OPERATION_LABELS}.items():
        if "_" in token:
            cleaned = re.sub(rf"\b{re.escape(token)}\b", label, cleaned)

    for phrase, label in _PROMPT_PHRASES.items():
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", label, cleaned, flags=re.I)

    cleaned = re.sub(r"\bunit\s*[:=]\s*decimal_rate\b", "taxa", cleaned)
    cleaned = re.sub(r"\bdecimal_rate\b", "taxa", cleaned)
    cleaned = re.sub(r"\bunit\s*[:=]\s*currency\b", "moeda", cleaned)
    cleaned = re.sub(r"\bcurrency\b", "moeda", cleaned)
    cleaned = re.sub(r"\bunit\s*[:=]\s*count\b", "contagem", cleaned)
    cleaned = re.sub(r"\bundefined\b", "indefinido", cleaned)
    cleaned = re.sub(r"\bperiod\b", "período", cleaned)
    cleaned = re.sub(r"\brank\s*=\s*(\d+)", r"posição \1", cleaned)
    cleaned = re.sub(r"\brank\b", "posição", cleaned)
    cleaned = _CALC_PATTERN.sub("", cleaned)

    return cleaned


def _replace_backticked_tokens(text: str) -> str:
    """`` `bar` ``, `` `share` ``… → rótulo de negócio; só entre crases."""

    labels = {**_PRESENTATION_LABELS, **_OPERATION_LABELS, **_METHOD_LABELS}

    def _label(match: re.Match[str]) -> str:

        token = match.group(1)

        return labels.get(token, match.group(0))

    return re.sub(r"`([a-z][a-z_]*)`", _label, text)


def _remove_known_ids(text: str, extra_ids: Collection[str]) -> str:

    cleaned = text

    for identifier in extra_ids:
        if not identifier:
            continue

        cleaned = re.sub(rf"\b{re.escape(identifier)}\b", "", cleaned)

    return _ID_TOKEN_PATTERN.sub("", cleaned)


def _clean_references(text: str) -> str:

    cleaned = re.sub(r"\[[A-Za-z0-9_.\-]+\s*[—–-]+\s*([^\[\]]+?)\]", r"\1", text)
    cleaned = re.sub(r"\[\s*[—–-]+\s*([^\[\]]+?)\]", r"\1", cleaned)

    return cleaned


def _collapse(text: str) -> str:
    """Compacta espaços linha a linha; as quebras de linha são Markdown e ficam."""

    cleaned = re.sub(r"\(\s*\)|\[\s*\]", "", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in cleaned.split("\n")]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    cleaned = re.sub(r"[^\S\n]+([,.;:!?%])", r"\1", cleaned)

    return cleaned.strip()


def _result_ids(
    result: AnalysisResult,
    document_ids: Sequence[str],
) -> list[str]:

    identifiers = [
        result.analysis_plan_id,
        result.catalog_version,
        result.dataset_version,
        result.trace_id,
        *document_ids,
    ]

    for method in result.statistical_method:
        identifiers.append(method.id)

    for operation in result.operations:
        identifiers.append(operation.id)
        identifiers.extend(operation.refs)

    return identifiers

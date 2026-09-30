"""Nota "Como calculei": método do turno em pt-BR, determinística, sem LLM.

O insight diz O QUE o número mostra; esta nota diz COMO ele nasceu — fórmula
da métrica, período e grão, método e operações, supressões por célula pequena,
base oficial e documento aprovado de referência. Tudo vem do pacote selado,
do `AnalysisResult` e do catálogo; nenhum número do resultado entra no texto,
só a contagem de células suprimidas. Pura por construção.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    Operation,
    OperationType,
    StatisticalMethodType,
)
from contexts.financial_analysis.domain.analysis_result import (
    SMALL_CELL_K,
    AnalysisResult,
    UndefinedReason,
)
from contexts.financial_analysis.domain.semantic_catalog import SemanticCatalog
from contexts.financial_analysis.domain.services.describe_capabilities import (
    month_year,
)
from contexts.financial_analysis.domain.services.provenance import (
    dataset_closing_date,
)
from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    CalculationPlan,
    Grain,
    Period,
    PeriodType,
)

METHOD_NOTE_TITLE = "Como calculei"

_METRIC_FORMULAS: dict[str, str] = {
    "profitability": (
        "Σ margem anualizada ÷ Σ saldo, re-derivada no total do período "
        "(não é média de taxas)"
    ),
    "outstanding_balance": (
        "saldo em aberto na última data do período (estoque, nunca somado "
        "entre períodos)"
    ),
    "contract_count": (
        "contratos ativos na última data do período (estoque, nunca somado "
        "entre períodos)"
    ),
    "customer_count": (
        "clientes distintos na última data do período (estoque, nunca somado "
        "entre períodos)"
    ),
    "cdi_rate": "taxa CDI composta no período (referência de mercado, sem recorte)",
    "selic_rate": "taxa SELIC composta no período (referência de mercado, sem recorte)",
    "inflation_ipca": "IPCA composto no período (referência de mercado, sem recorte)",
}

# Fontes oficiais por regra: a rentabilidade nasce de margem E saldo, então a
# sua base cita as duas métricas; as demais citam a própria.
_METRIC_SOURCES: dict[str, tuple[str, ...]] = {
    "profitability": ("profitability", "outstanding_balance"),
}

_MACRO_SOURCE = "séries de mercado"

_METHOD_DESCRIPTIONS: dict[StatisticalMethodType, str] = {
    StatisticalMethodType.NULL: (
        "valores verificados do período, sem tratamento estatístico"
    ),
    StatisticalMethodType.MEAN: "média aritmética da série por entidade",
    StatisticalMethodType.MEDIAN: "mediana da série por entidade",
    StatisticalMethodType.MODE: "valor mais frequente da série por entidade",
    StatisticalMethodType.STD: "desvio-padrão da série por entidade (volatilidade)",
    StatisticalMethodType.DISPERSION: (
        "pacote de dispersão por entidade (média, mediana, desvio-padrão, "
        "mínimo, máximo e quartis)"
    ),
    StatisticalMethodType.VARIATION: (
        "variação entre as duas janelas (diferença absoluta e percentual)"
    ),
    StatisticalMethodType.TREND: (
        "inclinação da regressão linear ao longo do eixo ordenado "
        "(tendência, não previsão)"
    ),
    StatisticalMethodType.SHARE: "participação de cada parte no todo",
    StatisticalMethodType.CORRELATION: "correlação de Pearson entre as duas métricas",
    StatisticalMethodType.OUTLIER: (
        "detecção de valores atípicos pela regra dos quartis"
    ),
}

_RANK_ORDERS: dict[str, str] = {
    "desc": "ordem decrescente",
    "asc": "ordem crescente",
}

_SELECTION_RULES: dict[str, str] = {
    "above_mean": "acima da média",
    "below_mean": "abaixo da média",
    "top_percent": "no percentil superior",
}

_OPERATION_DESCRIPTIONS: dict[OperationType, str] = {
    OperationType.COMPARISON: "comparação lado a lado",
    OperationType.CUMULATIVE_SHARE: "participação acumulada em ordem decrescente",
    OperationType.PIVOT: "tabela dinâmica por entidade e período",
    OperationType.DECOMPOSITION: "decomposição da variação por parte",
}

_GRAIN_SUFFIXES: dict[Grain, str] = {
    Grain.MONTH: ", grão mensal",
    Grain.QUARTER: ", grão trimestral",
    Grain.YEAR: ", grão anual",
    Grain.TOTAL: "",
}

_METRIC_REFERENCES: dict[str, str] = {
    "profitability": "Como o banco calcula rentabilidade",
    "outstanding_balance": "Como o banco calcula carteira e saldo",
    "contract_count": "Como o banco conta contratos",
    "customer_count": "Como o banco conta clientes",
    "cdi_rate": "CDI, SELIC e IPCA como referências de mercado",
    "selic_rate": "CDI, SELIC e IPCA como referências de mercado",
    "inflation_ipca": "CDI, SELIC e IPCA como referências de mercado",
}

_METHOD_REFERENCES: dict[StatisticalMethodType, str] = {
    StatisticalMethodType.TREND: (
        "O que é tendência (regressão linear) e o que não é previsão"
    ),
    StatisticalMethodType.VARIATION: (
        "O que é variação entre períodos e como é calculada"
    ),
    StatisticalMethodType.SHARE: "O que é participação (share) e como é calculada",
    StatisticalMethodType.STD: "O que é dispersão, desvio-padrão e volatilidade",
    StatisticalMethodType.DISPERSION: (
        "O que é dispersão, desvio-padrão e volatilidade"
    ),
    StatisticalMethodType.CORRELATION: (
        "O que é correlação de Pearson entre duas métricas"
    ),
    StatisticalMethodType.OUTLIER: (
        "O que é outlier (valor atípico) e como é detectado"
    ),
}

_OPERATION_REFERENCES: dict[OperationType, str] = {
    OperationType.CUMULATIVE_SHARE: "O que é participação (share) e como é calculada",
}

_SMALL_CELL_REFERENCE = "Politica de celula pequena (k igual a 10)"


def describe_method(
    plan: AnalysisPlan,
    calculations: Sequence[CalculationPlan],
    result: AnalysisResult,
    catalog: SemanticCatalog,
) -> str:
    """Lista Markdown em pt-BR: métrica, período, método, supressões, base e
    referência do turno. Sem números do resultado; rótulos pelo catálogo."""

    rule_ids = _rule_ids(calculations)
    suppressed = _suppressed_cells(result)

    lines = [
        f"- Métrica: {_metric_line(rule_ids, catalog)}.",
        f"- Período: {_period_line(calculations, catalog)}.",
        f"- Método: {_method_line(plan, rule_ids, catalog)}.",
    ]

    if suppressed:
        lines.append(f"- Supressões: {_suppression_line(suppressed)}.")

    lines.append(f"- Base: {_source_line(rule_ids, result, catalog)}.")
    lines.append(f"- Referência: {_reference_line(plan, rule_ids, suppressed)}.")

    return "\n".join(lines)


def _rule_ids(calculations: Sequence[CalculationPlan]) -> tuple[str, ...]:
    """Regras do pacote, na ordem dos planos e sem repetição."""

    return _dedupe(str(plan.metric.rule_id) for plan in calculations)


def _metric_label(rule_id: str, catalog: SemanticCatalog) -> str:

    entry = catalog.metric(rule_id)

    if entry is not None and entry.synonyms:
        return entry.synonyms[0]

    return rule_id.replace("_", " ")


def _metric_line(rule_ids: Sequence[str], catalog: SemanticCatalog) -> str:

    return "; ".join(
        f"{_metric_label(rule_id, catalog)} = "
        f"{_METRIC_FORMULAS.get(rule_id, 'regra do catálogo')}"
        for rule_id in rule_ids
    )


def _period_line(
    calculations: Sequence[CalculationPlan],
    catalog: SemanticCatalog,
) -> str:

    periods = _dedupe(_period_text(plan.period) for plan in calculations)
    breakdown = _breakdown_text(calculations, catalog)

    return f"{' e '.join(periods)}, {breakdown}"


def _period_text(period: Period) -> str:

    if period.type == PeriodType.SNAPSHOT:
        return f"posição em {period.end:%d/%m/%Y}"

    months = _months_between(period.start, period.end)
    closed = "mês fechado" if months == 1 else "meses fechados"
    grain = _GRAIN_SUFFIXES.get(period.grain, "")

    return (
        f"{month_year(period.start)} a {month_year(period.end)} "
        f"({months} {closed}{grain})"
    )


def _months_between(start: date, end: date) -> int:

    return (end.year - start.year) * 12 + end.month - start.month + 1


def _breakdown_text(
    calculations: Sequence[CalculationPlan],
    catalog: SemanticCatalog,
) -> str:
    """`por segmento` (+ `com recorte por principalidade = alta`) ou `no total`."""

    subjects = _dedupe(
        _axis_label(str(subject.type), str(subject.level), catalog)
        for plan in calculations
        for subject in plan.metric.subjects
        if str(subject.type) != "total"
    )
    samples = _dedupe(
        _sample_text(str(item.type), str(item.level), item.value_id, catalog)
        for plan in calculations
        for item in plan.metric.sample
    )

    text = f"por {_join(subjects)}" if subjects else "no total"

    if samples:
        text += f", com recorte por {_join(samples)}"

    return text


def _axis_label(axis_type: str, level: str, catalog: SemanticCatalog) -> str:

    entry = catalog.axis(axis_type, level)

    if entry is not None and entry.synonyms:
        return entry.synonyms[0]

    return level.replace("_", " ")


def _value_label(
    axis_type: str,
    level: str,
    value_id: str,
    catalog: SemanticCatalog,
) -> str:

    entry = catalog.value(axis_type, level, value_id)

    if entry is not None and entry.labels:
        return entry.labels[0]

    return value_id.replace("_", " ")


def _sample_text(
    axis_type: str,
    level: str,
    value_id: str,
    catalog: SemanticCatalog,
) -> str:
    """`alta principalidade` quando o rótulo já nomeia o eixo; senão `eixo = valor`."""

    axis = _axis_label(axis_type, level, catalog)
    value = _value_label(axis_type, level, value_id, catalog)

    if axis.lower() in value.lower():
        return value

    return f"{axis} = {value}"


def _method_line(
    plan: AnalysisPlan,
    rule_ids: Sequence[str],
    catalog: SemanticCatalog,
) -> str:

    methods = [
        StatisticalMethodType(method.method) for method in plan.statistical_method
    ]
    analytical = [
        method for method in methods if method is not StatisticalMethodType.NULL
    ]
    described = _dedupe(_METHOD_DESCRIPTIONS[method] for method in analytical)
    metric = _metric_label(rule_ids[0], catalog) if rule_ids else "métrica"
    operations = _dedupe(
        _operation_text(operation, metric) for operation in plan.operations
    )

    parts = described + operations

    if not parts:
        return _METHOD_DESCRIPTIONS[StatisticalMethodType.NULL]

    return "; ".join(parts)


def _operation_text(operation: Operation, metric: str) -> str:

    kind = OperationType(operation.type)

    if kind is OperationType.RANKING:
        order = _RANK_ORDERS.get(str(operation.params.get("order", "desc")), "")
        suffix = f" ({order})" if order else ""

        return f"ranking pela {metric} do período{suffix}"

    if kind is OperationType.SELECTION:
        rule = _SELECTION_RULES.get(str(operation.params.get("rule", "")), "")

        return f"seleção das entidades {rule}".rstrip()

    return _OPERATION_DESCRIPTIONS.get(kind, str(kind).replace("_", " "))


def _suppressed_cells(result: AnalysisResult) -> int:

    return sum(
        1
        for method in result.statistical_method
        for row in method.values
        if row.undefined is UndefinedReason.SMALL_CELL
    )


def _suppression_line(suppressed: int) -> str:

    cells = "célula omitida" if suppressed == 1 else "células omitidas"

    return (
        f"{suppressed} {cells} por ter menos de {SMALL_CELL_K} clientes "
        "(política de célula pequena)"
    )


def _source_line(
    rule_ids: Sequence[str],
    result: AnalysisResult,
    catalog: SemanticCatalog,
) -> str:

    sources = _dedupe(
        _source_label(source, catalog)
        for rule_id in rule_ids
        for source in _METRIC_SOURCES.get(rule_id, (rule_id,))
    )
    closed = dataset_closing_date(result.dataset_version)
    closing = f", fechamento em {closed:%d/%m/%Y}" if closed is not None else ""

    return f"dados oficiais de {_join(sources)}{closing}"


def _source_label(rule_id: str, catalog: SemanticCatalog) -> str:

    entry = catalog.metric(rule_id)

    if entry is not None and entry.macro:
        return _MACRO_SOURCE

    return _metric_label(rule_id, catalog)


def _reference_line(
    plan: AnalysisPlan,
    rule_ids: Sequence[str],
    suppressed: int,
) -> str:

    titles = [
        _METRIC_REFERENCES[rule] for rule in rule_ids if rule in _METRIC_REFERENCES
    ]
    titles += [
        _METHOD_REFERENCES[method.method]
        for method in plan.statistical_method
        if method.method in _METHOD_REFERENCES
    ]
    titles += [
        _OPERATION_REFERENCES[operation.type]
        for operation in plan.operations
        if operation.type in _OPERATION_REFERENCES
    ]

    if suppressed:
        titles.append(_SMALL_CELL_REFERENCE)

    unique = _dedupe(titles)

    if not unique:
        return "documentação aprovada do catálogo"

    kind = "documento aprovado" if len(unique) == 1 else "documentos aprovados"
    quoted = _join('"' + title + '"' for title in unique)

    return f"{quoted} ({kind})"


def _join(terms: Iterable[str]) -> str:
    """Lista em pt-BR: `a, b e c`."""

    values = list(terms)

    if not values:
        return ""

    if len(values) == 1:
        return values[0]

    return ", ".join(values[:-1]) + " e " + values[-1]


def _dedupe(terms: Iterable[str]) -> list[str]:

    seen: set[str] = set()
    unique: list[str] = []

    for term in terms:
        if term in seen:
            continue

        seen.add(term)
        unique.append(term)

    return unique

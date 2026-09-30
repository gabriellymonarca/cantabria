"""`execute_analysis`: aplica métodos e operações sobre números verificados.

O motor recebe os `CalculationResult` do `financial_calculation` e aplica sobre
eles os métodos e as operações do plano. Métodos leem `calculation_plan_ids` ou
`statistic_refs` (DAG); operações leem métodos prontos.

Garantias:
- `subjects` é a identidade de cada linha, igual à do cálculo;
- valor indefinido é `None` com motivo — nunca 0;
- célula com menos de `k` clientes é suprimida (small-cell, k=10), com
  supressão complementar;
- o resultado carrega `catalog_version`, `dataset_version` e `trace_id`.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from decimal import ROUND_CEILING, Decimal

from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    Operation,
    OperationType,
    StatisticalMethod,
    StatisticalMethodType,
)
from contexts.financial_analysis.domain.analysis_result import (
    SMALL_CELL_K,
    AnalysisResult,
    MethodResult,
    MethodValue,
    OperationResult,
    OperationValue,
    UndefinedReason,
)
from contexts.financial_analysis.domain.errors import AnalysisExecutionError
from contexts.financial_analysis.domain.semantic_catalog import SemanticCatalog
from contexts.financial_analysis.domain.statistics import (
    dispersion_pack,
    iqr_fences,
    mean,
    median,
    mode,
    pearson,
    sample_std,
    slope,
)
from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    CalculationResult,
)

CellKey = tuple[tuple[str, str | None], ...]
PopulationKey = tuple[CellKey, str]
Populations = Mapping[PopulationKey, int]

_ORDINAL_SEPARATOR = "."


def populations_from_results(
    calculation_results: Sequence[CalculationResult],
) -> Populations:
    """Lê a população (clientes distintos) de cada célula × período dos
    resultados de cálculo. Linhas sem população são desconhecidas e ficam de
    fora: a supressão não inventa contagem. Quando dois planos medem a mesma
    célula, prevalece a menor população (leitura conservadora)."""

    populations: dict[PopulationKey, int] = {}

    for result in calculation_results:
        for row in result.values:
            if row.population is None:
                continue

            key = (_cell_key(row.subjects), row.period)
            known = populations.get(key)
            populations[key] = (
                row.population if known is None else min(known, row.population)
            )

    return populations


def rows_without_population(
    calculation_results: Sequence[CalculationResult],
) -> int:
    """Linhas com valor mas sem população: passam pelo k sem serem julgadas.
    O pipeline avisa quando isto acontece só em PARTE das linhas."""

    return sum(
        1
        for result in calculation_results
        for row in result.values
        if row.value is not None and row.population is None
    )


def execute_analysis(
    analysis_plan: AnalysisPlan,
    calculation_results: Sequence[CalculationResult],
    catalog: SemanticCatalog,
    *,
    dataset_version: str,
    trace_id: str,
    populations: Populations | None = None,
    small_cell_k: int = SMALL_CELL_K,
    prompt_version: str = "",
) -> AnalysisResult:
    """Executa o plano e devolve o AnalysisResult verificável."""

    by_plan = {result.calculation_plan_id: result for result in calculation_results}
    method_results: dict[str, MethodResult] = {}

    for method in analysis_plan.statistical_method:
        result = _execute_method(method, by_plan, method_results, catalog)
        method_results[method.id] = _suppress(result, populations, small_cell_k)

    operations = [
        _execute_operation(operation, method_results, catalog)
        for operation in analysis_plan.operations
    ]
    methods = list(method_results.values())

    return AnalysisResult(
        analysis_plan_id=analysis_plan.id,
        catalog_version=catalog.catalog_version,
        dataset_version=dataset_version,
        trace_id=trace_id,
        statistical_method=methods,
        operations=operations,
        unit=_methods_unit(methods),
        rule_id=_methods_rule(methods),
        prompt_version=prompt_version,
    )


# ---------------------------------------------------------------------------
# Métodos
# ---------------------------------------------------------------------------


def _execute_method(
    method: StatisticalMethod,
    by_plan: dict[str, CalculationResult],
    method_results: dict[str, MethodResult],
    catalog: SemanticCatalog,
) -> MethodResult:

    if method.method is StatisticalMethodType.CORRELATION:
        result = _correlation(method, method_results)
        referenced = [
            method_results[ref]
            for ref in method.statistic_refs
            if ref in method_results
        ]

        return _with_method_provenance(result, None, _methods_rule(referenced))

    sources = [
        by_plan[plan_id]
        for plan_id in method.calculation_plan_ids
        if plan_id in by_plan
    ]

    if not sources:
        raise AnalysisExecutionError(f"método '{method.id}' sem fontes executáveis.")

    result = _dispatch_method(method, sources, catalog)

    if method.method is StatisticalMethodType.SHARE:
        return _with_method_provenance(result, "decimal_rate", _common_rule(sources))

    return _with_method_provenance(result, _common_unit(sources), _common_rule(sources))


def _dispatch_method(
    method: StatisticalMethod,
    sources: Sequence[CalculationResult],
    catalog: SemanticCatalog,
) -> MethodResult:

    if method.method is StatisticalMethodType.NULL:
        return _null(method, sources)

    scalar = _SCALAR_HANDLERS.get(method.method)

    if scalar is not None:
        return _scalar(method, sources, scalar)

    if method.method is StatisticalMethodType.VARIATION:
        return _variation(method, sources)

    if method.method is StatisticalMethodType.TREND:
        return _trend(method, sources, catalog)

    if method.method is StatisticalMethodType.SHARE:
        return _share(method, sources)

    if method.method is StatisticalMethodType.OUTLIER:
        return _outlier(method, sources)

    raise AnalysisExecutionError(f"método '{method.method}' sem executor.")


def _null(
    method: StatisticalMethod,
    sources: Sequence[CalculationResult],
) -> MethodResult:

    values: list[MethodValue] = []

    for result in sources:
        for row in result.values:
            if row.value is None:
                values.append(
                    MethodValue(
                        row.subjects,
                        {},
                        UndefinedReason.NO_OBSERVATIONS,
                        row.period,
                    )
                )
            else:
                values.append(
                    MethodValue(row.subjects, {"value": row.value}, None, row.period)
                )

    return MethodResult(str(method.id), str(method.method), values)


def _scalar(
    method: StatisticalMethod,
    sources: Sequence[CalculationResult],
    compute,
) -> MethodResult:

    values: list[MethodValue] = []

    for key, numbers in _numeric_series(sources).items():
        outcome = compute(numbers)

        if outcome is None:
            reason = (
                UndefinedReason.NOT_COMPUTABLE
                if numbers
                else UndefinedReason.NO_OBSERVATIONS
            )
            values.append(MethodValue(_subjects_of(key), {}, reason))
        else:
            values.append(MethodValue(_subjects_of(key), outcome))

    return MethodResult(str(method.id), str(method.method), values)


def _compute_mean(numbers: Sequence[Decimal]) -> dict[str, Decimal] | None:

    return {"value": mean(numbers)} if numbers else None


def _compute_median(numbers: Sequence[Decimal]) -> dict[str, Decimal] | None:

    return {"value": median(numbers)} if numbers else None


def _compute_mode(numbers: Sequence[Decimal]) -> dict[str, Decimal] | None:

    value = mode(numbers)

    return {"value": value} if value is not None else None


def _compute_std(numbers: Sequence[Decimal]) -> dict[str, Decimal] | None:

    value = sample_std(numbers)

    return {"value": value} if value is not None else None


def _compute_dispersion(numbers: Sequence[Decimal]) -> dict[str, Decimal] | None:

    return dispersion_pack(numbers)


_SCALAR_HANDLERS = {
    StatisticalMethodType.MEAN: _compute_mean,
    StatisticalMethodType.MEDIAN: _compute_median,
    StatisticalMethodType.MODE: _compute_mode,
    StatisticalMethodType.STD: _compute_std,
    StatisticalMethodType.DISPERSION: _compute_dispersion,
}


def _variation(
    method: StatisticalMethod,
    sources: Sequence[CalculationResult],
) -> MethodResult:

    base, current = _order_windows(sources)
    base_map = {_cell_key(row.subjects): row for row in base.values}
    current_map = {_cell_key(row.subjects): row for row in current.values}
    values: list[MethodValue] = []

    for key, base_row in base_map.items():
        current_row = current_map.get(key)

        if base_row.value is None or current_row is None or current_row.value is None:
            values.append(
                MethodValue(base_row.subjects, {}, UndefinedReason.NO_OBSERVATIONS)
            )
            continue

        absolute = _decimal(current_row.value) - _decimal(base_row.value)
        percent = absolute / _decimal(base_row.value) if base_row.value != 0 else None

        values.append(
            MethodValue(
                base_row.subjects,
                {"absolute": absolute, "percent": percent},
            )
        )

    for key, current_row in current_map.items():
        if key not in base_map:
            values.append(
                MethodValue(current_row.subjects, {}, UndefinedReason.NO_OBSERVATIONS)
            )

    return MethodResult(str(method.id), str(method.method), values)


def _share(
    method: StatisticalMethod,
    sources: Sequence[CalculationResult],
) -> MethodResult:

    result = sources[0]
    total = sum(_decimal(row.value) for row in result.values if row.value is not None)
    values: list[MethodValue] = []

    for row in result.values:
        if row.value is None or total == 0:
            values.append(
                MethodValue(row.subjects, {}, UndefinedReason.NO_OBSERVATIONS)
            )
            continue

        values.append(MethodValue(row.subjects, {"value": _decimal(row.value) / total}))

    return MethodResult(str(method.id), str(method.method), values)


def _correlation(
    method: StatisticalMethod,
    method_results: dict[str, MethodResult],
) -> MethodResult:

    left, right = [
        method_results[ref] for ref in method.statistic_refs if ref in method_results
    ]
    left_map = {
        _cell_key(row.subjects): row for row in left.values if row.undefined is None
    }
    pairs: list[tuple[Decimal, Decimal]] = []

    for row in right.values:
        if row.undefined is not None:
            continue

        other = left_map.get(_cell_key(row.subjects))
        left_value = _numeric(other.values) if other is not None else None
        right_value = _numeric(row.values)

        if left_value is None or right_value is None:
            continue

        pairs.append((left_value, right_value))

    coefficient = pearson(pairs)

    if coefficient is None:
        return MethodResult(
            str(method.id),
            str(method.method),
            [
                MethodValue(
                    {},
                    {},
                    UndefinedReason.NOT_COMPUTABLE
                    if pairs
                    else UndefinedReason.NO_OBSERVATIONS,
                )
            ],
        )

    return MethodResult(
        str(method.id),
        str(method.method),
        [MethodValue({}, {"value": coefficient})],
    )


def _trend(
    method: StatisticalMethod,
    sources: Sequence[CalculationResult],
    catalog: SemanticCatalog,
) -> MethodResult:

    ordinal_key = _ordinal_axis_key(sources, catalog)

    if ordinal_key is None:
        return _trend_time(method, sources)

    return _trend_ordinal(method, sources[0], ordinal_key, catalog)


def _trend_time(
    method: StatisticalMethod,
    sources: Sequence[CalculationResult],
) -> MethodResult:

    values: list[MethodValue] = []

    for key, rows in _series(sources).items():
        points = [
            (Decimal(index), _decimal(row.value))
            for index, row in enumerate(rows)
            if row.value is not None
        ]
        inclination = slope(points)

        if inclination is None:
            values.append(
                MethodValue(_subjects_of(key), {}, UndefinedReason.NOT_COMPUTABLE)
            )
            continue

        values.append(MethodValue(_subjects_of(key), {"value": inclination}))

    return MethodResult(str(method.id), str(method.method), values)


def _trend_ordinal(
    method: StatisticalMethod,
    result: CalculationResult,
    ordinal_key: str,
    catalog: SemanticCatalog,
) -> MethodResult:

    axis_type, level = _split_key(ordinal_key)
    groups: dict[CellKey, list[tuple[Decimal, Decimal]]] = {}

    for row in result.values:
        if row.value is None:
            continue

        label = row.subjects.get(ordinal_key)
        rank = _rank_of_label(catalog, axis_type, level, label)

        if rank is None:
            continue

        other_subjects = {
            key: value for key, value in row.subjects.items() if key != ordinal_key
        }
        groups.setdefault(_cell_key(other_subjects), []).append(
            (Decimal(rank), _decimal(row.value))
        )

    values: list[MethodValue] = []

    for key, points in groups.items():
        inclination = slope(points)

        if inclination is None:
            values.append(
                MethodValue(_subjects_of(key), {}, UndefinedReason.NOT_COMPUTABLE)
            )
            continue

        values.append(MethodValue(_subjects_of(key), {"value": inclination}))

    if not groups:
        values.append(MethodValue({}, {}, UndefinedReason.NO_OBSERVATIONS))

    return MethodResult(str(method.id), str(method.method), values)


def _outlier(
    method: StatisticalMethod,
    sources: Sequence[CalculationResult],
) -> MethodResult:

    values: list[MethodValue] = []

    for key, rows in _series(sources).items():
        numbers = [_decimal(row.value) for row in rows if row.value is not None]
        fences = iqr_fences(numbers)

        if fences is None:
            values.append(
                MethodValue(
                    _subjects_of(key),
                    {},
                    UndefinedReason.NOT_COMPUTABLE
                    if numbers
                    else UndefinedReason.NO_OBSERVATIONS,
                )
            )
            continue

        low, high = fences

        for row in rows:
            if row.value is None:
                continue

            number = _decimal(row.value)

            if number < low or number > high:
                values.append(
                    MethodValue(
                        row.subjects,
                        {"value": number, "fence_low": low, "fence_high": high},
                        None,
                        row.period,
                    )
                )

    if not values:
        values.append(MethodValue({}, {"outliers": 0}))

    return MethodResult(str(method.id), str(method.method), values)


# ---------------------------------------------------------------------------
# Operações
# ---------------------------------------------------------------------------


def _execute_operation(
    operation: Operation,
    method_results: dict[str, MethodResult],
    catalog: SemanticCatalog,
) -> OperationResult:

    if operation.type is OperationType.RANKING:
        result = _ranking(operation, method_results)
    elif operation.type is OperationType.COMPARISON:
        result = _comparison(operation, method_results)
    elif operation.type is OperationType.CUMULATIVE_SHARE:
        result = _cumulative_share(operation, method_results)
    elif operation.type is OperationType.SELECTION:
        result = _selection(operation, method_results)
    elif operation.type is OperationType.PIVOT:
        result = _pivot(operation, method_results)
    elif operation.type is OperationType.DECOMPOSITION:
        result = _decomposition(operation, method_results)
    else:
        raise AnalysisExecutionError(f"operação '{operation.type}' sem executor.")

    referenced = [
        method_results[ref] for ref in operation.refs if ref in method_results
    ]

    if operation.type is OperationType.DECOMPOSITION:
        source = _variation_source(referenced)

        if source is not None:
            return _with_operation_provenance(result, source.unit, source.rule_id)

    return _with_operation_provenance(
        result, _methods_unit(referenced), _methods_rule(referenced)
    )


def _ranking(
    operation: Operation,
    method_results: dict[str, MethodResult],
) -> OperationResult:

    source = method_results[operation.refs[0]]
    order = str(operation.params.get("order", "desc"))
    entries = _numeric_entries(source)
    entries.sort(key=lambda entry: entry[0])
    entries.sort(key=lambda entry: entry[1], reverse=order == "desc")

    top_n = operation.params.get("top_n")

    if top_n is not None:
        entries = entries[: int(top_n)]

    values = [
        OperationValue(row.subjects, {"value": number}, rank=rank, period=row.period)
        for rank, (_, number, row) in enumerate(entries, start=1)
    ]

    return _operation_result(operation, values)


def _comparison(
    operation: Operation,
    method_results: dict[str, MethodResult],
) -> OperationResult:

    across = str(operation.params.get("across", "entity"))

    if across == "entity":
        source = method_results[operation.refs[0]]
        values = [
            OperationValue(row.subjects, dict(row.values), period=row.period)
            for row in source.values
            if row.undefined is None
        ]
        return _operation_result(operation, values)

    left = method_results[operation.refs[0]]
    right = method_results[operation.refs[1]]
    left_map = {
        _cell_key(row.subjects): row for row in left.values if row.undefined is None
    }
    values: list[OperationValue] = []

    for row in right.values:
        if row.undefined is not None:
            continue

        other = left_map.get(_cell_key(row.subjects))

        if other is None:
            continue

        values.append(
            OperationValue(
                row.subjects,
                {
                    operation.refs[0]: _numeric(other.values),
                    operation.refs[1]: _numeric(row.values),
                },
                period=row.period,
            )
        )

    return _operation_result(operation, values)


def _cumulative_share(
    operation: Operation,
    method_results: dict[str, MethodResult],
) -> OperationResult:

    source = method_results[operation.refs[0]]
    cutoff = _decimal(operation.params["cutoff"])
    entries = _numeric_entries(source)
    entries.sort(key=lambda entry: entry[0])
    entries.sort(key=lambda entry: entry[1], reverse=True)
    values: list[OperationValue] = []
    cumulative = Decimal(0)
    previous: Decimal | None = None
    rank = 0

    for _cell, number, row in entries:
        if cumulative >= cutoff and number != previous:
            break

        cumulative += number
        previous = number
        rank += 1
        values.append(
            OperationValue(
                row.subjects,
                {"value": number, "cumulative": cumulative},
                rank=rank,
                period=row.period,
            )
        )

    return _operation_result(operation, values)


def _selection(
    operation: Operation,
    method_results: dict[str, MethodResult],
) -> OperationResult:

    source = method_results[operation.refs[0]]
    selected = str(operation.params.get("rule"))
    entries = _numeric_entries(source)
    entries.sort(key=lambda entry: entry[0])
    entries.sort(key=lambda entry: entry[1], reverse=True)

    if selected == "above_mean":
        threshold = mean([number for _, number, _ in entries])
        entries = [entry for entry in entries if entry[1] > threshold]
    elif selected == "below_mean":
        threshold = mean([number for _, number, _ in entries])
        entries = [entry for entry in entries if entry[1] < threshold]
    else:
        count = (
            Decimal(len(entries)) * _decimal(operation.params["value"]) / Decimal(100)
        ).to_integral_value(rounding=ROUND_CEILING)
        entries = _with_boundary_ties(entries, int(count))

    values = [
        OperationValue(row.subjects, {"value": number}, rank=rank, period=row.period)
        for rank, (_, number, row) in enumerate(entries, start=1)
    ]

    return _operation_result(operation, values)


def _with_boundary_ties(entries: list, count: int) -> list:

    if count >= len(entries):
        return entries

    boundary = entries[count - 1][1]
    kept = entries[:count]

    for entry in entries[count:]:
        if entry[1] != boundary:
            break

        kept.append(entry)

    return kept


def _pivot(
    operation: Operation,
    method_results: dict[str, MethodResult],
) -> OperationResult:

    source = method_results[operation.refs[0]]
    rows_key = str(operation.params["rows"])
    columns_key = str(operation.params["columns"])
    groups: dict[str, dict[str, Decimal]] = {}

    for row in source.values:
        if row.undefined is not None:
            continue

        row_value = row.subjects.get(rows_key)
        column_value = row.subjects.get(columns_key)
        number = _numeric(row.values)

        if row_value is None or column_value is None or number is None:
            continue

        groups.setdefault(row_value, {})[column_value] = number

    values = [
        OperationValue({rows_key: row_value}, dict(columns))
        for row_value, columns in sorted(groups.items())
    ]

    return _operation_result(operation, values)


def _decomposition(
    operation: Operation,
    method_results: dict[str, MethodResult],
) -> OperationResult:

    referenced = {
        method_results[ref].method: method_results[ref] for ref in operation.refs
    }
    variation = referenced.get(str(StatisticalMethodType.VARIATION))
    share = referenced.get(str(StatisticalMethodType.SHARE))

    if variation is None or share is None:
        raise AnalysisExecutionError(
            "decomposition exige os métodos variation e share."
        )

    share_map = {
        _cell_key(row.subjects): row for row in share.values if row.undefined is None
    }
    values: list[OperationValue] = []
    total = Decimal(0)

    for row in variation.values:
        if row.undefined is not None:
            continue

        absolute = row.values.get("absolute")
        share_row = share_map.get(_cell_key(row.subjects))
        share_value = _numeric(share_row.values) if share_row is not None else None

        if absolute is None or share_value is None:
            values.append(
                OperationValue(
                    row.subjects, {}, undefined=UndefinedReason.NOT_COMPUTABLE
                )
            )
            continue

        contribution = _decimal(absolute) * share_value
        total += contribution
        values.append(OperationValue(row.subjects, {"contribution": contribution}))

    values.append(OperationValue({}, {"contribution": total}))

    return _operation_result(operation, values)


# ---------------------------------------------------------------------------
# Small-cell (k=10) com supressão complementar
# ---------------------------------------------------------------------------


def _suppress(
    result: MethodResult,
    populations: Populations | None,
    small_cell_k: int,
) -> MethodResult:
    """Mascara células com menos de `k` clientes, período a período.

    Cada linha é julgada com a população da SUA célula × período; linha sem
    período (estatística sobre a série inteira) herda a menor população da
    célula em qualquer período, porque o número deriva de todas elas. Em cada
    período com célula suprimida, a menor célula restante também é mascarada
    (supressão complementar), para que o total não a revele por diferença.
    Um total recortado (subjects vazios) é uma célula como outra qualquer:
    é julgado pela sua população; só não entra como companheira."""

    if not populations:
        return result

    primary = {
        _row_key(row)
        for row in result.values
        if _is_small_cell(row, populations, small_cell_k)
    }

    if not primary:
        return result

    for period in {period for _, period in primary}:
        companions = [
            row
            for row in result.values
            if row.subjects
            and row.undefined is None
            and row.period == period
            and _row_key(row) not in primary
            and _numeric(row.values) is not None
        ]

        if companions:
            smallest = min(companions, key=lambda row: _numeric(row.values))
            primary.add(_row_key(smallest))

    masked = [
        MethodValue(
            row.subjects,
            {},
            UndefinedReason.SMALL_CELL,
            row.period,
        )
        if _row_key(row) in primary
        else row
        for row in result.values
    ]

    return MethodResult(result.id, result.method, masked, result.unit, result.rule_id)


def _is_small_cell(
    row: MethodValue,
    populations: Populations,
    small_cell_k: int,
) -> bool:

    if row.undefined is not None:
        return False

    population = _population(populations, row.subjects, row.period)

    return population is not None and population < small_cell_k


def _population(
    populations: Populations,
    subjects: dict[str, str | None],
    period: str | None,
) -> int | None:

    cell = _cell_key(subjects)

    if period is not None:
        return populations.get((cell, period))

    known = [count for (other, _), count in populations.items() if other == cell]

    return min(known) if known else None


def _row_key(row: MethodValue) -> tuple[CellKey, str | None]:

    return _cell_key(row.subjects), row.period


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _operation_result(
    operation: Operation,
    values: list[OperationValue],
) -> OperationResult:

    return OperationResult(
        operation.id,
        str(operation.type),
        list(operation.refs),
        values,
    )


def _common_unit(sources: Sequence[CalculationResult]) -> str | None:

    units = {result.unit for result in sources}

    return next(iter(units)) if len(units) == 1 else None


def _common_rule(sources: Sequence[CalculationResult]) -> str | None:

    rules = {result.rule_id for result in sources}

    return next(iter(rules)) if len(rules) == 1 else None


def _methods_unit(methods: Sequence[MethodResult]) -> str | None:

    units = {entry.unit for entry in methods}

    return next(iter(units)) if len(units) == 1 else None


def _methods_rule(methods: Sequence[MethodResult]) -> str | None:

    rules = {entry.rule_id for entry in methods}

    return next(iter(rules)) if len(rules) == 1 else None


def _variation_source(referenced: Sequence[MethodResult]) -> MethodResult | None:

    return next(
        (
            entry
            for entry in referenced
            if entry.method == str(StatisticalMethodType.VARIATION)
        ),
        None,
    )


def _with_method_provenance(
    result: MethodResult,
    unit: str | None,
    rule_id: str | None,
) -> MethodResult:

    return MethodResult(result.id, result.method, result.values, unit, rule_id)


def _with_operation_provenance(
    result: OperationResult,
    unit: str | None,
    rule_id: str | None,
) -> OperationResult:

    return OperationResult(
        result.id, result.type, result.refs, result.values, unit, rule_id
    )


def _numeric_entries(result: MethodResult) -> list:

    entries = []

    for row in result.values:
        if row.undefined is not None:
            continue

        number = _numeric(row.values)

        if number is None:
            continue

        entries.append((_cell_key(row.subjects), number, row))

    return entries


def _numeric(values: dict[str, Decimal | int | None]) -> Decimal | None:

    for key in ("value", "absolute", "contribution", "cumulative"):
        number = values.get(key)

        if number is not None:
            return _decimal(number)

    return None


def _series(
    sources: Sequence[CalculationResult],
) -> dict[CellKey, list]:

    groups: dict[CellKey, list] = {}

    for result in sources:
        for row in result.values:
            groups.setdefault(_cell_key(row.subjects), []).append(row)

    for rows in groups.values():
        rows.sort(key=lambda row: row.period)

    return groups


def _numeric_series(
    sources: Sequence[CalculationResult],
) -> dict[CellKey, list[Decimal]]:

    return {
        key: [_decimal(row.value) for row in rows if row.value is not None]
        for key, rows in _series(sources).items()
    }


def _order_windows(
    sources: Sequence[CalculationResult],
) -> tuple[CalculationResult, CalculationResult]:

    left, right = sources[0], sources[1]
    left_marker = min(row.period for row in left.values)
    right_marker = min(row.period for row in right.values)

    if left_marker <= right_marker:
        return left, right

    return right, left


def _ordinal_axis_key(
    sources: Sequence[CalculationResult],
    catalog: SemanticCatalog,
) -> str | None:

    for result in sources:
        for row in result.values:
            for key in row.subjects:
                axis_type, level = _split_key(key)

                if catalog.is_ordinal(axis_type, level):
                    return key

    return None


def _rank_of_label(
    catalog: SemanticCatalog,
    axis_type: str,
    level: str,
    label: str | None,
) -> int | None:

    if label is None:
        return None

    normalized = _normalize(label)

    for rank, entry in enumerate(
        value
        for value in catalog.values
        if value.type == axis_type and value.level == level
    ):
        candidates = {
            _normalize(entry.value_id),
            *(_normalize(item) for item in entry.labels),
        }

        if normalized in candidates:
            return rank

    return None


def _normalize(text: str) -> str:

    decomposed = unicodedata.normalize("NFKD", text)

    return "".join(
        char for char in decomposed if not unicodedata.combining(char)
    ).lower()


def _split_key(key: str) -> tuple[str, str]:

    axis_type, _, level = key.partition(_ORDINAL_SEPARATOR)

    return axis_type, level


def _cell_key(subjects: dict[str, str | None]) -> CellKey:

    return tuple(sorted(subjects.items()))


def _subjects_of(key: CellKey) -> dict[str, str | None]:

    return dict(key)


def _decimal(number: Decimal | int) -> Decimal:

    return number if isinstance(number, Decimal) else Decimal(number)

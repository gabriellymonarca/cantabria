"""O fiscal determinístico: aprova ou recusa o pacote inteiro.

Mesma entrada, mesma saída.

Ordem das verificações, por dependência:
  1. autorização ampla
  2. forma
  3. catálogo
  4. autorização fina
  5. referências
  6. compatibilidade (método × forma, operação × resultado)
  7. topologia temporal (`variation`)
  8. params de operação

Aprovado, o pacote é selado com a versão do catálogo e o instante — só esse
estado pode ser executado.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from contexts.auth.ports.inbound.authorize_port import UserCapabilities
from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    ComparisonAcross,
    Operation,
    OperationType,
    Presentation,
    PresentationAxis,
    PresentationType,
    RankAxis,
    RankOrder,
    SelectionRule,
    StatisticalMethod,
    StatisticalMethodType,
)
from contexts.financial_analysis.domain.errors import PlanValidationError
from contexts.financial_analysis.domain.interpretation import RefusalReason
from contexts.financial_analysis.domain.periods import (
    grain_buckets,
    same_grain_span,
    windows_disjoint,
)
from contexts.financial_analysis.domain.semantic_catalog import (
    CompatibilitySource,
    MethodCompatibility,
    MetricShape,
    OperationCompatibility,
    Requirement,
    SameField,
    SemanticCatalog,
)
from contexts.financial_calculation.ports.inbound.execute_calculations_port import (
    AxisLevel,
    AxisType,
    CalculationPlan,
    Grain,
    PeriodType,
)

_METHODS_BY_ID = dict[str, StatisticalMethod]
_PLANS_BY_ID = dict[str, CalculationPlan]


@dataclass(frozen=True)
class ValidatedPlan:
    """O pacote aprovado, selado com a versão do catálogo."""

    analysis_plan: AnalysisPlan
    calculations: tuple[CalculationPlan, ...]
    catalog_version: str
    validated_at: datetime


def validate_plan(
    analysis_plan: AnalysisPlan,
    calculations: list[CalculationPlan],
    catalog: SemanticCatalog,
    capabilities: UserCapabilities,
    validated_at: datetime | None = None,
) -> ValidatedPlan:
    """Valida o pacote inteiro e devolve o plano selado, ou recusa tipificada."""

    _check_broad_authorization(capabilities)
    _check_form(analysis_plan, calculations)

    plans = {plan.calculation_plan_id: plan for plan in calculations}
    methods = {method.id: method for method in analysis_plan.statistical_method}

    _check_catalog(plans, catalog, capabilities)
    _check_references(analysis_plan, plans)
    _check_compatibility(analysis_plan, methods, plans, catalog)
    _check_operations(analysis_plan, methods, plans, catalog)
    _check_temporal_topology(analysis_plan, plans)
    _check_dates(plans, catalog)

    analysis_plan = _seal_presentation(analysis_plan, methods, plans)

    return ValidatedPlan(
        analysis_plan=analysis_plan,
        calculations=tuple(calculations),
        catalog_version=catalog.catalog_version,
        validated_at=validated_at or datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# 1-2. Autorização ampla e forma
# ---------------------------------------------------------------------------


def _fail(reason: RefusalReason, message: str) -> None:

    raise PlanValidationError(reason, message)


def _check_broad_authorization(capabilities: UserCapabilities) -> None:

    if not capabilities.can_use_financial_analysis:
        _fail(
            RefusalReason.UNAUTHORIZED,
            "O usuário não tem acesso à análise financeira.",
        )


def _check_form(
    analysis_plan: AnalysisPlan,
    calculations: list[CalculationPlan],
) -> None:

    if not calculations:
        _fail(
            RefusalReason.NOT_EXPRESSIBLE,
            "A rota analytical exige ao menos um CalculationPlan.",
        )

    if not analysis_plan.statistical_method:
        _fail(
            RefusalReason.NOT_EXPRESSIBLE,
            "O AnalysisPlan exige ao menos um statistical_method.",
        )

    ids = [plan.calculation_plan_id for plan in calculations]

    if len(set(ids)) != len(ids):
        _fail(
            RefusalReason.NOT_EXPRESSIBLE,
            "calculation_plan_id repetido no pacote inteiro.",
        )

    # A forma de cada `Period` e `Metric` (janela invertida, snapshot pontual,
    # quebra ausente/repetida, `total` sozinho, recorte que repete quebra) é
    # invariante dos próprios value objects do motor: um CalculationPlan
    # malformado nem chega a existir.


# ---------------------------------------------------------------------------
# 3-4. Catálogo e autorização fina
# ---------------------------------------------------------------------------


def _check_catalog(
    plans: _PLANS_BY_ID,
    catalog: SemanticCatalog,
    capabilities: UserCapabilities,
) -> None:

    for plan in plans.values():
        rule_id = str(plan.metric.rule_id)
        entry = catalog.metric(rule_id)

        if entry is None:
            _fail(
                RefusalReason.CATALOG_MISS,
                f"métrica '{rule_id}' não existe no catálogo "
                f"{catalog.catalog_version}.",
            )

        # Série macro (CDI/SELIC/IPCA) é escalar: não tem segmento, produto nem
        # cliente. Qualquer eixo de negócio, como quebra ou recorte, é
        # `not_expressible`.
        if entry.macro and not _is_macro_request(plan):
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"métrica macro '{rule_id}' só aceita total.total, sem recorte.",
            )

        if not capabilities.allows_metric(rule_id):
            _fail(
                RefusalReason.UNAUTHORIZED,
                f"o usuário não tem acesso à métrica '{rule_id}'.",
            )

        for subject in plan.metric.subjects:
            _check_axis(str(subject.type), str(subject.level), catalog)
            _check_axis_access(str(subject.type), str(subject.level), capabilities)

        for condition in plan.metric.sample:
            _check_axis(str(condition.type), str(condition.level), catalog)
            _check_axis_access(str(condition.type), str(condition.level), capabilities)

            if (
                catalog.value(
                    str(condition.type),
                    str(condition.level),
                    condition.value_id,
                )
                is None
            ):
                _fail(
                    RefusalReason.CATALOG_MISS,
                    f"valor '{condition.value_id}' não pertence a "
                    f"'{condition.type}.{condition.level}'.",
                )


def _check_axis(
    axis_type: str,
    level: str,
    catalog: SemanticCatalog,
) -> None:

    if catalog.axis(axis_type, level) is None:
        _fail(
            RefusalReason.CATALOG_MISS,
            f"eixo '{axis_type}.{level}' não existe no catálogo "
            f"{catalog.catalog_version}.",
        )


def _check_axis_access(
    axis_type: str,
    level: str,
    capabilities: UserCapabilities,
) -> None:

    if not capabilities.allows_axis(axis_type, level):
        _fail(
            RefusalReason.UNAUTHORIZED,
            f"o usuário não tem acesso ao eixo '{axis_type}.{level}'.",
        )


# ---------------------------------------------------------------------------
# 5. Referências
# ---------------------------------------------------------------------------


def _check_references(
    analysis_plan: AnalysisPlan,
    plans: _PLANS_BY_ID,
) -> None:

    referenced: set[str] = set()

    for method in analysis_plan.statistical_method:
        for plan_id in method.calculation_plan_ids:
            if plan_id not in plans:
                _fail(
                    RefusalReason.NOT_EXPRESSIBLE,
                    f"método '{method.id}' cita '{plan_id}', que não está no pacote.",
                )

            referenced.add(plan_id)

    for plan_id in plans:
        if plan_id not in referenced:
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"métrica '{plan_id}' ficou órfã: nenhum método a lê.",
            )


# ---------------------------------------------------------------------------
# 6. Compatibilidade
# ---------------------------------------------------------------------------


def _check_compatibility(
    analysis_plan: AnalysisPlan,
    methods: _METHODS_BY_ID,
    plans: _PLANS_BY_ID,
    catalog: SemanticCatalog,
) -> None:

    for method in analysis_plan.statistical_method:
        rule = catalog.method_rule(str(method.method))

        if rule is None:
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"método '{method.method}' fora do catálogo.",
            )

        sources = _underlying_plans(method, methods, plans)
        shapes = {_metric_shape(plan, catalog) for plan in sources}

        forbidden = shapes & set(rule.forbids_metric_shape)

        if forbidden:
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"'{method.method}' não é ofertado para a forma "
                f"{_shape_names(forbidden)}.",
            )

        if rule.requires_metric_shape and not shapes <= set(rule.requires_metric_shape):
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"'{method.method}' exige métrica "
                f"{_shape_names(rule.requires_metric_shape)}.",
            )

        _check_source_count(method, rule)
        _check_requirements(method, rule, sources, catalog)
        _check_same(method, rule, sources)


def _check_source_count(
    method: StatisticalMethod,
    rule: MethodCompatibility,
) -> None:

    if rule.count is None:
        return

    declared = (
        method.statistic_refs
        if rule.reads is CompatibilitySource.STATISTIC_REFS
        else method.calculation_plan_ids
    )

    if len(declared) != rule.count:
        _fail(
            RefusalReason.NOT_EXPRESSIBLE,
            f"'{method.method}' exige exatamente {rule.count} fontes; "
            f"recebeu {len(declared)}.",
        )


def _check_requirements(
    method: StatisticalMethod,
    rule: MethodCompatibility,
    plans: list[CalculationPlan],
    catalog: SemanticCatalog,
) -> None:

    has_series = bool(plans) and all(_is_series(plan) for plan in plans)
    has_collapsed = bool(plans) and all(_is_collapsed(plan) for plan in plans)
    has_ordinal = _has_ordinal_axis(plans, catalog, rule.min_levels)

    for requirement in rule.requires:
        if requirement is Requirement.SERIES and not has_series:
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"'{method.method}' exige série com mais de um período no grão.",
            )

        if requirement is Requirement.COLLAPSED_RESULT and not has_collapsed:
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"'{method.method}' exige resultado colapsado "
                "(snapshot ou grain: total).",
            )

        if requirement is Requirement.ORDINAL_AXIS and not has_ordinal:
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"'{method.method}' exige eixo ordinal com ao menos "
                f"{rule.min_levels} níveis.",
            )

    if rule.requires_any:
        satisfied = (Requirement.SERIES in rule.requires_any and has_series) or (
            Requirement.ORDINAL_AXIS in rule.requires_any and has_ordinal
        )

        if not satisfied:
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"'{method.method}' exige uma das formas: "
                f"{', '.join(str(item) for item in rule.requires_any)}.",
            )


def _check_same(
    method: StatisticalMethod,
    rule: MethodCompatibility,
    plans: list[CalculationPlan],
) -> None:

    reason = (
        RefusalReason.INVALID_WINDOW
        if method.method is StatisticalMethodType.VARIATION
        else RefusalReason.NOT_EXPRESSIBLE
    )

    for field in rule.same:
        if field is SameField.RULE_ID:
            values = [str(plan.metric.rule_id) for plan in plans]
        elif field is SameField.SUBJECTS:
            values = [str(_subject_keys(plan)) for plan in plans]
        else:
            values = [str(_sample_keys(plan)) for plan in plans]

        if len(set(values)) > 1:
            _fail(
                reason,
                f"'{method.method}' exige os mesmos {field} nas fontes.",
            )


# ---------------------------------------------------------------------------
# 7-8. Topologia temporal e params
# ---------------------------------------------------------------------------


def _check_temporal_topology(
    analysis_plan: AnalysisPlan,
    plans: _PLANS_BY_ID,
) -> None:

    for method in analysis_plan.statistical_method:
        if method.method is not StatisticalMethodType.VARIATION:
            continue

        windows = [plans[plan_id] for plan_id in method.calculation_plan_ids]

        if len(windows) != 2:
            continue

        left, right = windows

        if not windows_disjoint(left.period, right.period):
            _fail(
                RefusalReason.INVALID_WINDOW,
                "as duas janelas do variation se sobrepõem.",
            )

        if not same_grain_span(left.period, right.period):
            _fail(
                RefusalReason.INVALID_WINDOW,
                "as duas janelas do variation têm durações diferentes.",
            )

        if (
            left.period.grain is not right.period.grain
            or left.period.type is not right.period.type
        ):
            _fail(
                RefusalReason.INVALID_WINDOW,
                "as duas janelas do variation têm grão ou tipo diferentes.",
            )


def _check_dates(
    plans: _PLANS_BY_ID,
    catalog: SemanticCatalog,
) -> None:

    for plan in plans.values():
        period = plan.period

        if period.start < catalog.window_start or period.end > catalog.window_end:
            _fail(
                RefusalReason.OUT_OF_WINDOW,
                f"o período {period.start}..{period.end} está fora da janela "
                f"disponível {catalog.window_start}..{catalog.window_end}.",
            )


# ---------------------------------------------------------------------------
# 9. Apresentação — cosmética; incompatível degrada para `table`
# ---------------------------------------------------------------------------


def _seal_presentation(
    analysis_plan: AnalysisPlan,
    methods: _METHODS_BY_ID,
    plans: _PLANS_BY_ID,
) -> AnalysisPlan:
    """Confirma a apresentação contra a forma do plano; incompatível vira table.

    A escolha é cosmética: degradar é melhor que recusar a pergunta certa. O
    que o value object já garante (catálogo fechado, `line` com eixo temporal,
    título sem id interno) não se repete aqui; esta checagem é sobre o que só
    se sabe olhando o plano: série para o `line`, ranking para o `ranking_bar`
    e entidade para o `bar`."""

    presentation = analysis_plan.presentation

    if presentation is None or _presentation_fits(
        analysis_plan, presentation, methods, plans
    ):
        return analysis_plan

    return replace(analysis_plan, presentation=Presentation())


def _presentation_fits(
    analysis_plan: AnalysisPlan,
    presentation: Presentation,
    methods: _METHODS_BY_ID,
    plans: _PLANS_BY_ID,
) -> bool:

    if presentation.type is PresentationType.TABLE:
        return True

    sources = [
        plan
        for method in analysis_plan.statistical_method
        for plan in _underlying_plans(method, methods, plans)
    ]

    if presentation.type is PresentationType.LINE:
        return any(_is_series(plan) for plan in sources)

    if presentation.type is PresentationType.RANKING_BAR:
        ranked = any(
            operation.type is OperationType.RANKING
            and str(operation.params.get("axis")) == presentation.axis.value
            for operation in analysis_plan.operations
        )

        if not ranked:
            return False

        if presentation.axis is PresentationAxis.PERIOD:
            return any(_is_series(plan) for plan in sources)

        return True

    if presentation.type is PresentationType.BAR:
        if presentation.axis is PresentationAxis.ENTITY:
            return any(_has_entity_subject(plan) for plan in sources)

        return any(_is_series(plan) for plan in sources)

    return False


def _has_entity_subject(plan: CalculationPlan) -> bool:

    return any(
        not (subject.type is AxisType.TOTAL and subject.level is AxisLevel.TOTAL)
        for subject in plan.metric.subjects
    )


def _check_operations(
    analysis_plan: AnalysisPlan,
    methods: _METHODS_BY_ID,
    plans: _PLANS_BY_ID,
    catalog: SemanticCatalog,
) -> None:

    for operation in analysis_plan.operations:
        rule = catalog.operation_rule(str(operation.type))

        if rule is None:
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"operação '{operation.type}' fora do catálogo.",
            )

        for param in rule.requires_params:
            if param not in operation.params:
                _fail(
                    RefusalReason.NOT_EXPRESSIBLE,
                    f"'{operation.type}' exige o param '{param}'.",
                )

        if rule.count is not None and len(operation.refs) != rule.count:
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"'{operation.type}' exige exatamente {rule.count} refs; "
                f"recebeu {len(operation.refs)}.",
            )

        referenced = [methods[ref] for ref in operation.refs if ref in methods]
        names = {str(method.method) for method in referenced}
        missing = set(rule.requires_source) - names

        if missing:
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"'{operation.type}' exige os métodos "
                f"{', '.join(sorted(rule.requires_source))}.",
            )

        _check_operation_shape(operation, rule, referenced, methods, plans, catalog)
        _check_operation_params(operation)


def _check_operation_shape(
    operation: Operation,
    rule: OperationCompatibility,
    referenced: list[StatisticalMethod],
    methods: _METHODS_BY_ID,
    plans: _PLANS_BY_ID,
    catalog: SemanticCatalog,
) -> None:

    if not rule.forbidden_rules_metric_shape:
        return

    selected_rule = str(operation.params.get("rule"))
    forbidden = rule.forbidden_rules_metric_shape.get(selected_rule)

    if forbidden is None:
        return

    shapes = {
        _metric_shape(plan, catalog)
        for method in referenced
        for plan in _underlying_plans(method, methods, plans)
    }

    if forbidden in shapes:
        _fail(
            RefusalReason.NOT_EXPRESSIBLE,
            f"'{operation.type}' com rule '{selected_rule}' não é ofertado "
            f"para a forma {forbidden}.",
        )


def _check_operation_params(operation: Operation) -> None:

    params = operation.params

    if operation.type is OperationType.RANKING:
        _check_ranking_params(params)
    elif operation.type is OperationType.COMPARISON:
        _check_comparison_params(params)
    elif operation.type is OperationType.CUMULATIVE_SHARE:
        _check_cutoff(params)
    elif operation.type is OperationType.SELECTION:
        _check_selection_params(params)
    elif operation.type is OperationType.PIVOT:
        _check_pivot_params(params)


def _check_ranking_params(params: dict) -> None:

    if not _is_member(params.get("order"), RankOrder):
        _fail(
            RefusalReason.NOT_EXPRESSIBLE,
            f"ranking.order deve ser {_options(RankOrder)}.",
        )

    if not _is_member(params.get("axis"), RankAxis):
        _fail(
            RefusalReason.NOT_EXPRESSIBLE,
            f"ranking.axis deve ser {_options(RankAxis)}.",
        )

    top_n = params.get("top_n")

    if top_n is not None and (
        isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1
    ):
        _fail(
            RefusalReason.NOT_EXPRESSIBLE,
            "ranking.top_n deve ser inteiro positivo.",
        )


def _check_comparison_params(params: dict) -> None:

    if not _is_member(params.get("across"), ComparisonAcross):
        _fail(
            RefusalReason.NOT_EXPRESSIBLE,
            f"comparison.across deve ser {_options(ComparisonAcross)}.",
        )


def _check_cutoff(params: dict) -> None:

    cutoff = params.get("cutoff")

    if (
        isinstance(cutoff, bool)
        or not isinstance(cutoff, (int, float))
        or not 0 < float(cutoff) <= 1
    ):
        _fail(
            RefusalReason.NOT_EXPRESSIBLE,
            "cumulative_share.cutoff deve estar em (0, 1].",
        )


def _check_selection_params(params: dict) -> None:

    selected = params.get("rule")

    if not _is_member(selected, SelectionRule):
        _fail(
            RefusalReason.NOT_EXPRESSIBLE,
            f"selection.rule deve ser {_options(SelectionRule)}.",
        )

    if SelectionRule(selected) is not SelectionRule.TOP_PERCENT:
        return

    value = params.get("value")

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 < float(value) <= 100
    ):
        _fail(
            RefusalReason.NOT_EXPRESSIBLE,
            "selection.value em top_percent deve estar em (0, 100].",
        )


def _is_member(value: object, options: type[StrEnum]) -> bool:

    return isinstance(value, str) and value in {option.value for option in options}


def _options(options: type[StrEnum]) -> str:

    return ", ".join(f"'{option.value}'" for option in options)


def _check_pivot_params(params: dict) -> None:

    for key in ("rows", "columns"):
        value = params.get(key)

        if not isinstance(value, str) or not value:
            _fail(
                RefusalReason.NOT_EXPRESSIBLE,
                f"pivot.{key} deve declarar um eixo do resultado.",
            )


# ---------------------------------------------------------------------------
# Travessia do DAG e helpers de forma
# ---------------------------------------------------------------------------


def _underlying_plans(
    method: StatisticalMethod,
    methods: _METHODS_BY_ID,
    plans: _PLANS_BY_ID,
    seen: set[str] | None = None,
) -> list[CalculationPlan]:

    visited = seen if seen is not None else set()

    if method.id in visited:
        return []

    visited.add(method.id)

    sources = [plans[plan_id] for plan_id in method.calculation_plan_ids]

    for ref in method.statistic_refs:
        referenced = methods.get(ref)

        if referenced is not None:
            sources.extend(_underlying_plans(referenced, methods, plans, visited))

    return sources


def _metric_shape(
    plan: CalculationPlan,
    catalog: SemanticCatalog,
) -> MetricShape | None:

    entry = catalog.metric(str(plan.metric.rule_id))

    return entry.shape if entry is not None else None


def _is_series(plan: CalculationPlan) -> bool:

    return plan.period.type is PeriodType.SERIES and grain_buckets(plan.period) > 1


def _is_collapsed(plan: CalculationPlan) -> bool:

    return plan.period.type is PeriodType.SNAPSHOT or plan.period.grain is Grain.TOTAL


def _has_ordinal_axis(
    plans: list[CalculationPlan],
    catalog: SemanticCatalog,
    min_levels: int | None,
) -> bool:

    for plan in plans:
        for subject in plan.metric.subjects:
            axis_type, level = str(subject.type), str(subject.level)

            if not catalog.is_ordinal(axis_type, level):
                continue

            levels = [
                value
                for value in catalog.values
                if value.type == axis_type and value.level == level
            ]

            if min_levels is None or len(levels) >= min_levels:
                return True

    return False


def _subject_keys(plan: CalculationPlan) -> frozenset[tuple[str, str]]:

    return frozenset(
        (str(subject.type), str(subject.level)) for subject in plan.metric.subjects
    )


def _is_macro_request(plan: CalculationPlan) -> bool:
    """Série macro só no grão total: uma quebra `total.total`, sem recorte."""

    subjects = plan.metric.subjects

    total_only = (
        len(subjects) == 1
        and subjects[0].type is AxisType.TOTAL
        and subjects[0].level is AxisLevel.TOTAL
    )

    return total_only and not plan.metric.sample


def _sample_keys(plan: CalculationPlan) -> frozenset[tuple[str, str, str]]:

    return frozenset(
        (str(condition.type), str(condition.level), condition.value_id)
        for condition in plan.metric.sample
    )


def _shape_names(shapes) -> str:

    return ", ".join(sorted(str(shape) for shape in shapes if shape is not None))

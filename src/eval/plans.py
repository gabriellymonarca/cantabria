"""Montagem e normalização de planos para o dataset e para o modo `--live`.

O dataset guarda planos em YAML legível; aqui eles viram value objects do
domínio (um plano malformado falha na construção). A normalização existe para
comparar o plano gold do dataset com a proposta do LLM sem depender de ids
locais.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from contexts.financial_calculation.domain.calculation_plan import (
    AxisLevel,
    AxisType,
    CalculationPlan,
    Grain,
    Metric,
    Period,
    PeriodType,
    RuleId,
    SampleCondition,
    Subject,
)


def build_calculation_plan(plan_id: str, data: dict) -> CalculationPlan:
    """Constrói um `CalculationPlan` a partir do dicionário do dataset."""

    period = data["period"]

    return CalculationPlan(
        calculation_plan_id=plan_id,
        metric=Metric(
            rule_id=_rule(data["rule_id"]),
            subjects=[_subject(item) for item in data["subjects"]],
            sample=[_sample(item) for item in data.get("sample") or []],
        ),
        period=Period(
            start=_date(period["start"]),
            end=_date(period["end"]),
            type=PeriodType(period["type"]),
            grain=Grain(period["grain"]),
        ),
    )


def normalize_plan(plan: Any) -> tuple:
    """Forma comparável de um `CalculationPlan`: ids locais não entram."""

    period = plan.period
    subjects = frozenset(
        (str(subject.type), str(subject.level)) for subject in plan.metric.subjects
    )
    sample = frozenset(
        (str(item.type), str(item.level), item.value_id) for item in plan.metric.sample
    )

    return (
        str(plan.metric.rule_id),
        subjects,
        sample,
        (
            period.start.isoformat(),
            period.end.isoformat(),
            str(period.type),
            str(period.grain),
        ),
    )


def normalize_plan_data(data: dict) -> tuple:
    """Forma comparável de um plano do dataset (mesmo formato de `normalize_plan`)."""

    plan = build_calculation_plan("normalize", data)

    return normalize_plan(plan)


def normalize_methods(methods: tuple[str, ...]) -> tuple[str, ...]:

    return tuple(sorted(methods))


def normalize_operations(operations: tuple[dict, ...]) -> tuple[tuple, ...]:

    normalized = []

    for operation in operations:
        params = operation.get("params") or {}
        normalized.append(
            (
                str(operation["type"]),
                tuple(sorted((str(k), str(v)) for k, v in params.items())),
            )
        )

    return tuple(sorted(normalized))


def _rule(value: Any) -> RuleId:

    try:
        return RuleId(value)
    except ValueError as error:
        raise ValueError(f"rule_id '{value}' fora do registry do motor.") from error


def _subject(data: dict) -> Subject:

    return Subject(type=_axis(data["type"]), level=_level(data["level"]))


def _sample(data: dict) -> SampleCondition:

    return SampleCondition(
        type=_axis(data["type"]),
        level=_level(data["level"]),
        value_id=str(data["value_id"]),
    )


def _axis(value: Any) -> AxisType:

    try:
        return AxisType(value)
    except ValueError as error:
        raise ValueError(f"eixo '{value}' fora do catálogo do motor.") from error


def _level(value: Any) -> AxisLevel:

    try:
        return AxisLevel(value)
    except ValueError as error:
        raise ValueError(f"nível '{value}' fora do catálogo do motor.") from error


def _date(value: Any) -> date:

    if isinstance(value, date):
        return value

    return date.fromisoformat(str(value))


def cast_rule(value: str) -> RuleId:
    """Usado só pelas sondas do redteam: valor fora do enum, sem inventar member."""

    return cast(RuleId, value)

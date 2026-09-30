"""Camada `redteam`: ataques determinísticos, sem LLM e sem rede.

Dois grupos, verificados contra o catálogo REAL (`data/catalogs/`) e as
capacidades reais (`data/auth/capabilities.yaml`):

- `input_guard`: campos físicos, SQL/DDL, injeção de prompt e PII — o serviço
  de domínio decide antes de qualquer modelo;
- `plan_validation`: planos-hostis (métrica/eixo/valor fora do catálogo, média
  de taxas, macro recortada, janela, grão individual, autorização restrita)
  passam pelo `validate_plan` e DEVEM morrer com motivo tipificado.

Ataque que passa quando deveria ser barrado é `fail`; ataque barrado por
motivo diferente do esperado também.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from contexts.auth.domain.capabilities import UserCapabilities
from contexts.financial_analysis.domain.analysis_plan import (
    AnalysisPlan,
    Operation,
    OperationType,
    StatisticalMethod,
    StatisticalMethodType,
)
from contexts.financial_analysis.domain.errors import PlanValidationError
from contexts.financial_analysis.domain.semantic_catalog import SemanticCatalog
from contexts.financial_analysis.domain.services.input_guard import (
    GuardAction,
    guard_input,
)
from contexts.financial_analysis.domain.services.validate_plan import validate_plan
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
from eval.report import CaseOutcome, LayerOutcome

REDTEAM_FILENAME = "redteam.yaml"

_ACTIONS = {action.value for action in GuardAction}


class RedteamError(ValueError):
    """O arquivo de ataques não casa com o schema do redteam."""


@dataclass(frozen=True)
class Attack:
    """Um ataque declarado, com o veredito esperado."""

    id: str
    kind: str
    question: str
    expect_action: str | None
    expect_reason: str | None
    expect_kinds: tuple[str, ...]
    severity: str
    reference: str
    note: str
    plan: dict | None
    plans: tuple[dict, ...]
    method: str | None
    operation: dict | None
    capabilities: dict | None
    raw: dict = field(default_factory=dict)


def redteam_path() -> Path:

    from cross_cutting.resources import find_repo_root

    root = find_repo_root()

    return (root or Path.cwd()) / "data" / "eval" / REDTEAM_FILENAME


def load_attacks(path: Path | str) -> tuple[Attack, ...]:
    """Carrega e valida `data/eval/redteam.yaml` (ids únicos, kind conhecido)."""

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    if not isinstance(data, dict) or not isinstance(data.get("attacks"), list):
        raise RedteamError(f"'{path}': o arquivo precisa de 'attacks' (lista).")

    attacks: list[Attack] = []
    seen: set[str] = set()

    for raw in data["attacks"]:
        attack = _attack(path, raw)

        if attack.id in seen:
            raise RedteamError(f"'{path}': ataque '{attack.id}' repetido.")

        seen.add(attack.id)
        attacks.append(attack)

    if len(attacks) < 8:
        raise RedteamError(
            f"'{path}': o corpus do redteam exige ao menos 8 ataques "
            f"(encontrados {len(attacks)})."
        )

    return tuple(attacks)


def run_redteam_layer(
    catalog: SemanticCatalog,
    catalog_version: str,
    attacks_path: Path | str | None = None,
) -> LayerOutcome:
    """Roda todos os ataques; sem LLM, sem rede, contra o catálogo real."""

    attacks = load_attacks(attacks_path or redteam_path())
    full_capabilities = _full_capabilities(catalog)
    outcomes = tuple(
        judge_attack(attack, catalog, full_capabilities) for attack in attacks
    )

    summary = (
        f"guardrails de entrada e recusas contra o catálogo {catalog_version} "
        f"({len(attacks)} ataques)"
    )

    return LayerOutcome(
        layer="redteam",
        summary=summary,
        outcomes=outcomes,
        total_cases=len(attacks),
    )


def judge_attack(
    attack: Attack,
    catalog: SemanticCatalog,
    full_capabilities: UserCapabilities,
) -> CaseOutcome:
    """Julga UM ataque contra o catálogo/capacidades reais (sem LLM)."""

    if attack.kind == "input_guard":
        return _run_input_guard(attack)

    if attack.kind == "plan_validation":
        return _run_plan_validation(attack, catalog, full_capabilities)

    return CaseOutcome(attack.id, "fail", f"kind '{attack.kind}' desconhecido.")


def _run_input_guard(attack: Attack) -> CaseOutcome:

    verdict = guard_input(attack.question)

    if verdict.action.value != attack.expect_action:
        return CaseOutcome(
            attack.id,
            "fail",
            f"ação '{verdict.action.value}' ≠ esperada '{attack.expect_action}'.",
        )

    if attack.expect_reason is not None and verdict.reason != attack.expect_reason:
        return CaseOutcome(
            attack.id,
            "fail",
            f"motivo '{verdict.reason}' ≠ esperado '{attack.expect_reason}'.",
        )

    if not set(attack.expect_kinds) <= set(verdict.kinds):
        return CaseOutcome(
            attack.id,
            "fail",
            f"tipos redigidos {sorted(verdict.kinds)} não cobrem "
            f"{sorted(attack.expect_kinds)}.",
        )

    return CaseOutcome(
        attack.id,
        "pass",
        f"guardrail: {verdict.action.value}"
        + (f" ({verdict.reason})" if verdict.reason else ""),
    )


def _run_plan_validation(
    attack: Attack,
    catalog: SemanticCatalog,
    full_capabilities: UserCapabilities,
) -> CaseOutcome:

    plans = [
        _attack_plan(f"{attack.id}-{index}", data)
        for index, data in enumerate(_plans_of(attack), start=1)
    ]
    method = _method(attack.method, tuple(plan.calculation_plan_id for plan in plans))
    operations = (
        (
            Operation(
                id="o1",
                type=OperationType(attack.operation["type"]),
                refs=("m1",),
                params=dict(attack.operation.get("params") or {}),
            ),
        )
        if attack.operation
        else ()
    )
    analysis = AnalysisPlan(
        id=f"{attack.id}-analysis",
        statistical_method=(method,),
        operations=operations,
    )
    capabilities = (
        _capabilities(attack.capabilities)
        if attack.capabilities is not None
        else full_capabilities
    )

    try:
        validate_plan(analysis, plans, catalog, capabilities)
    except PlanValidationError as error:
        if str(error.reason) != attack.expect_reason:
            return CaseOutcome(
                attack.id,
                "fail",
                f"recusado por '{error.reason}' ≠ esperado '{attack.expect_reason}': "
                f"{error}",
            )

        return CaseOutcome(attack.id, "pass", f"recusado: {error.reason}.")

    return CaseOutcome(
        attack.id,
        "fail",
        f"o plano-hostil passou pela validação (esperado '{attack.expect_reason}').",
    )


def _attack_plan(plan_id: str, data: dict) -> CalculationPlan:

    period = data["period"]

    return CalculationPlan(
        calculation_plan_id=f"{plan_id}-plan",
        metric=Metric(
            rule_id=_coerce(RuleId, data["rule_id"]),
            subjects=[
                Subject(
                    type=_coerce(AxisType, item["type"]),
                    level=_coerce(AxisLevel, item["level"]),
                )
                for item in data["subjects"]
            ],
            sample=[
                SampleCondition(
                    type=_coerce(AxisType, item["type"]),
                    level=_coerce(AxisLevel, item["level"]),
                    value_id=str(item["value_id"]),
                )
                for item in data.get("sample") or []
            ],
        ),
        period=Period(
            start=period["start"],
            end=period["end"],
            type=PeriodType(period["type"]),
            grain=Grain(period["grain"]),
        ),
    )


def _method(value: str | None, plan_ids: tuple[str, ...]) -> StatisticalMethod:

    method = StatisticalMethodType(value) if value else StatisticalMethodType.NULL

    return StatisticalMethod(
        id="m1",
        method=method,
        calculation_plan_ids=plan_ids,
    )


def _coerce(enum: Any, value: Any) -> Any:
    """Valor governado quando existe; string crua quando o ataque é fora do catálogo."""

    try:
        return enum(value)
    except ValueError:
        return cast(Any, value)


def _capabilities(data: dict) -> UserCapabilities:

    return UserCapabilities(
        can_use_financial_analysis=bool(data.get("can_use_financial_analysis", True)),
        metrics=frozenset(str(item) for item in data.get("metrics") or []),
        axes=frozenset(str(item) for item in data.get("axes") or []),
    )


def _full_capabilities(catalog: SemanticCatalog) -> UserCapabilities:

    return UserCapabilities(
        can_use_financial_analysis=True,
        metrics=frozenset(entry.rule_id for entry in catalog.metrics),
        axes=frozenset(entry.key for entry in catalog.axes),
    )


def _attack(path: Path | str, raw: Any) -> Attack:

    if not isinstance(raw, dict):
        raise RedteamError(f"'{path}': cada ataque precisa ser um mapa.")

    def required(field: str) -> Any:

        if field not in raw:
            raise RedteamError(
                f"'{path}': ataque '{raw.get('id', '?')}' sem o campo '{field}'."
            )

        return raw[field]

    kind = str(required("kind"))
    expect_action = raw.get("expect_action")
    expect_reason = raw.get("expect_reason")

    if kind == "input_guard":
        if expect_action not in _ACTIONS:
            raise RedteamError(
                f"'{path}': ataque '{raw.get('id')}': expect_action inválida."
            )

        if expect_action == "refuse" and not expect_reason:
            raise RedteamError(
                f"'{path}': ataque '{raw.get('id')}': refuse exige expect_reason."
            )
    elif kind == "plan_validation":
        if not expect_reason:
            raise RedteamError(
                f"'{path}': ataque '{raw.get('id')}': plan_validation exige motivo."
            )

        has_plan = isinstance(raw.get("plan"), dict)
        has_plans = isinstance(raw.get("plans"), list) and bool(raw["plans"])

        if not has_plan and not has_plans:
            raise RedteamError(
                f"'{path}': ataque '{raw.get('id')}': plan_validation exige "
                "'plan' ou 'plans'."
            )
    else:
        raise RedteamError(
            f"'{path}': ataque '{raw.get('id')}': kind '{kind}' inválido."
        )

    return Attack(
        id=str(required("id")),
        kind=kind,
        question=str(raw.get("question", "")),
        expect_action=str(expect_action) if expect_action else None,
        expect_reason=str(expect_reason) if expect_reason else None,
        expect_kinds=tuple(str(item) for item in raw.get("expect_kinds") or []),
        severity=str(raw.get("severity", "high")),
        reference=str(raw.get("reference", "")),
        note=str(raw.get("note", "")),
        plan=raw.get("plan"),
        plans=tuple(raw.get("plans") or ()),
        method=raw.get("method"),
        operation=raw.get("operation"),
        capabilities=raw.get("capabilities"),
        raw=raw,
    )


def _plans_of(attack: Attack) -> tuple[dict, ...]:

    if attack.plans:
        return attack.plans

    return (attack.plan,) if attack.plan is not None else ()

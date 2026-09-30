"""Camadas generativas: `planner`, `routing`, `explanation` e `e2e`.

Offline (padrão) todas ficam `skipped (offline)`, pois exigem o LLM. Com
`--live`:
- `planner`: compara o pacote proposto (regra, quebra, amostra, período,
  métodos e operações) com o gold do dataset;
- `routing`: compara rota e motivo de recusa com o esperado;
- `explanation` e `e2e`: exigem o pipeline de execução ponta a ponta
  (cálculo + redator + lastro) e são reportadas como pendentes.
"""

from __future__ import annotations

from pathlib import Path

from contexts.financial_analysis.application.commands.interpretation_schema import (
    InterpretationProposal,
)
from eval.dataset import EvalCase, EvalDataset
from eval.live import DEFAULT_CONFIG, LivePlanner, LiveUnavailableError
from eval.plans import (
    normalize_methods,
    normalize_operations,
    normalize_plan,
    normalize_plan_data,
)
from eval.report import CaseOutcome, LayerOutcome

LLM_LAYERS = ("planner", "routing", "explanation", "e2e")

_OFFLINE_DETAIL = "skipped (offline): camada generativa exige --live."
_NOT_ANALYTICAL_DETAIL = (
    "skipped: o gold não é analítico; rota e motivo são julgados pela camada routing."
)
_proposal_cache: dict[tuple[str, str], InterpretationProposal | None] = {}
_PENDING_DETAIL = (
    "live: avaliação ponta a ponta pendente (o planner roda; o pipeline de "
    "execução será plugado numa próxima fatia — ver docs/evaluation-report.md)."
)


def run_llm_layer(
    layer: str,
    dataset: EvalDataset,
    *,
    live: bool,
    config_path: Path | str = DEFAULT_CONFIG,
) -> LayerOutcome:
    """Executa uma camada generativa em `--live`; offline devolve a camada pulada."""

    if not live:
        return LayerOutcome(
            layer=layer,
            summary="camada generativa; requer --live",
            total_cases=len(dataset.cases),
            skipped_cases=len(dataset.cases),
        )

    if layer in ("explanation", "e2e"):
        # O LlmPort é configurado (falha clara sem config); a avaliação destas duas
        # camadas exige o pipeline de execução e é reportada como pendente.
        try:
            LivePlanner(config_path)
        except LiveUnavailableError as error:
            raise _live_error(layer, error) from error

        return LayerOutcome(
            layer=layer,
            summary="camada generativa; pipeline de execução pendente",
            total_cases=len(dataset.cases),
            skipped_cases=len(dataset.cases),
            outcomes=tuple(
                CaseOutcome(case.id, "skip", _PENDING_DETAIL) for case in dataset.cases
            ),
        )

    try:
        planner = LivePlanner(config_path)
    except LiveUnavailableError as error:
        raise _live_error(layer, error) from error

    outcomes = tuple(_run_case(layer, case, planner) for case in dataset.cases)

    return LayerOutcome(
        layer=layer,
        summary=(
            "planner real (LlmPort configurado) × gold do dataset"
            if layer == "planner"
            else "rota e motivo de recusa do planner × esperado"
        ),
        outcomes=outcomes,
        total_cases=len(dataset.cases),
    )


def _live_error(layer: str, error: LiveUnavailableError) -> LiveUnavailableError:

    return LiveUnavailableError(f"camada '{layer}': {error}")


def _run_case(layer: str, case: EvalCase, planner: LivePlanner) -> CaseOutcome:

    if layer == "planner" and case.expected_route != "analytical":
        return CaseOutcome(case.id, "skip", _NOT_ANALYTICAL_DETAIL)

    try:
        proposal = _propose_once(case, planner)
    except Exception as error:  # noqa: BLE001 — a falha de UM caso não derruba a suíte
        if _is_authentication_error(error):
            raise LiveUnavailableError(
                f"LLM recusou a credencial ({type(error).__name__}); confira "
                "`llm.api_key` no config.yaml."
            ) from error

        return CaseOutcome(
            case.id, "fail", f"erro ao propor: {type(error).__name__}: {error}"
        )

    if proposal is None:
        return _evaluate_absent_proposal(layer, case)

    if layer == "routing":
        return _evaluate_routing(case, proposal)

    return _evaluate_planner(case, proposal)


def _propose_once(
    case: EvalCase, planner: LivePlanner
) -> InterpretationProposal | None:
    """Uma chamada ao LLM por caso e execução: `planner` e `routing` compartilham."""

    key = (case.id, case.question)

    if key not in _proposal_cache:
        _proposal_cache[key] = planner.propose(case.question, case.id)

    return _proposal_cache[key]


def _is_authentication_error(error: Exception) -> bool:

    return "authentication" in type(error).__name__.lower() or "401" in str(error)


def _evaluate_absent_proposal(layer: str, case: EvalCase) -> CaseOutcome:
    """Sem proposta estruturada: o guardrail recusou ou o schema falhou.

    Nos dois caminhos a rota observada é `refuse` (o guardrail recusa com
    `input_policy`; a falha de schema vira clarificação fixa). A comparação é
    conservadora: só passa quando o caso espera recusa.
    """

    route = "refuse"

    if case.expected_route == route and case.expected_refusal_reason in {
        "input_policy",
        "governance",
        "unauthorized",
    }:
        return CaseOutcome(case.id, "pass", "recusa observada sem proposta.")

    return CaseOutcome(
        case.id,
        "fail",
        f"sem proposta estruturada; rota esperada '{case.expected_route}'.",
    )


def _evaluate_routing(case: EvalCase, proposal: InterpretationProposal) -> CaseOutcome:

    route = str(proposal.route)

    if route != case.expected_route:
        return CaseOutcome(
            case.id,
            "fail",
            f"rota '{route}' ≠ esperada '{case.expected_route}'.",
        )

    if route == "refuse":
        reason = str(proposal.refusal_reason) if proposal.refusal_reason else "ausente"
        expected = case.expected_refusal_reason

        if reason != expected:
            return CaseOutcome(
                case.id,
                "fail",
                f"motivo '{reason}' ≠ esperado '{expected}'.",
            )

    return CaseOutcome(case.id, "pass", f"rota '{route}'.")


def _evaluate_planner(case: EvalCase, proposal: InterpretationProposal) -> CaseOutcome:

    if str(proposal.route) != "analytical":
        return CaseOutcome(
            case.id,
            "fail",
            f"rota '{proposal.route}' ≠ esperada 'analytical'.",
        )

    actual_plans = sorted(normalize_plan(plan) for plan in proposal.calculations)
    expected_plans = sorted(normalize_plan_data(plan) for plan in case.expected_plan)

    if actual_plans != expected_plans:
        return CaseOutcome(
            case.id,
            "fail",
            "pacote de cálculo difere do gold "
            f"(esperado {len(expected_plans)} plano(s), "
            f"proposto {len(actual_plans)}).",
        )

    analysis = proposal.analysis

    if analysis is None:
        return CaseOutcome(case.id, "fail", "rota analytical sem AnalysisPlan.")

    actual_methods = normalize_methods(
        tuple(str(method.method) for method in analysis.statistical_method)
    )
    expected_methods = normalize_methods(case.expected_methods)

    if actual_methods != expected_methods:
        return CaseOutcome(
            case.id,
            "fail",
            f"métodos {actual_methods} ≠ esperados {expected_methods}.",
        )

    actual_operations = normalize_operations(
        tuple(
            {"type": str(operation.type), "params": operation.params}
            for operation in analysis.operations
        )
    )
    expected_operations = normalize_operations(case.expected_operations)

    if actual_operations != expected_operations:
        return CaseOutcome(
            case.id,
            "fail",
            f"operações {actual_operations} ≠ esperadas {expected_operations}.",
        )

    return CaseOutcome(case.id, "pass", "plano e análise conferem com o gold.")

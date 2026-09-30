"""Leitura e validação dos datasets de avaliação (um YAML por split).

O schema descreve um caso de avaliação e o que o harness precisa comparar:
`expected_plan` (planos de cálculo gold), `expected_methods`,
`expected_operations`, `expected_result_ref` (caso do oráculo congelado) e
`redteam_check` (sondas determinísticas). O teste do schema garante id único,
rota válida e os campos obrigatórios por rota; o catálogo real é conferido na
hora de montar cada plano.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from contexts.financial_analysis.domain.interpretation import (
    InterpretationRoute,
    RefusalReason,
)

SPLITS = ("dev", "test")

BEHAVIORS = (
    "answer",
    "answer_with_caveat",
    "clarify",
    "refuse_scope",
    "not_expressible",
    "reject_invalid_window",
    "refuse_policy",
)

ANSWER_BEHAVIORS = ("answer", "answer_with_caveat")

# Rota esperada por comportamento: é o que a camada `routing` compara no
# modo `--live`. `answer` sem plano é resposta documental/capability.
ROUTE_BY_BEHAVIOR: dict[str, tuple[str, ...]] = {
    "answer": (
        InterpretationRoute.ANALYTICAL.value,
        InterpretationRoute.DOCUMENTAL.value,
        InterpretationRoute.CAPABILITY.value,
    ),
    "answer_with_caveat": (
        InterpretationRoute.ANALYTICAL.value,
        InterpretationRoute.DOCUMENTAL.value,
        InterpretationRoute.CAPABILITY.value,
    ),
    "clarify": (InterpretationRoute.CLARIFY.value,),
    "refuse_scope": (InterpretationRoute.REFUSE.value,),
    "not_expressible": (InterpretationRoute.REFUSE.value,),
    "reject_invalid_window": (InterpretationRoute.REFUSE.value,),
    "refuse_policy": (InterpretationRoute.REFUSE.value,),
}

REFUSAL_BEHAVIORS = (
    "refuse_scope",
    "not_expressible",
    "reject_invalid_window",
    "refuse_policy",
)

SEVERITIES = ("high", "medium", "low")

DEFAULT_DATASET_DIR = Path("data") / "eval"


class EvalDatasetError(ValueError):
    """O arquivo do split não casa com o schema do harness."""


@dataclass(frozen=True)
class EvalCase:
    """Um caso do split, com o gold e como ele deve ser julgado."""

    id: str
    category: str
    split: str
    language: str
    question: str
    expected_behavior: str
    expected_route: str
    expected_refusal_reason: str | None
    expected_plan: tuple[dict, ...]
    expected_methods: tuple[str, ...]
    expected_operations: tuple[dict, ...]
    expected_result_ref: str | None
    severity: str
    demo: bool
    fixtures: dict
    definitions_ref: str
    notes: str
    redteam_check: dict | None


@dataclass(frozen=True)
class EvalDataset:
    """Um split carregado: metadados do arquivo e a lista de casos."""

    path: Path
    split: str
    version: int
    cases: tuple[EvalCase, ...]

    def by_id(self, case_id: str) -> EvalCase:

        for case in self.cases:
            if case.id == case_id:
                return case

        raise EvalDatasetError(f"caso '{case_id}' não existe no split.")

    def by_behavior(self, *behaviors: str) -> tuple[EvalCase, ...]:

        return tuple(case for case in self.cases if case.expected_behavior in behaviors)


def load_dataset(path: Path | str) -> EvalDataset:
    """Carrega um YAML de split e valida o schema; erro é `EvalDatasetError`."""

    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise EvalDatasetError(f"'{path}': o arquivo do split precisa de um mapa.")

    split = str(data.get("split", ""))
    version = data.get("version")

    if not isinstance(version, int):
        raise EvalDatasetError(f"'{path}': 'version' inteira é obrigatória.")

    raw_cases = data.get("cases")

    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvalDatasetError(f"'{path}': 'cases' não pode ser vazio.")

    dataset = EvalDataset(
        path=path,
        split=split,
        version=version,
        cases=tuple(_case(path, raw, split) for raw in raw_cases),
    )

    _validate(dataset)

    return dataset


def dataset_path(split: str, data_dir: Path | None = None) -> Path:
    """Caminho canônico de um split no checkout (`data/eval/<split>.yaml`)."""

    return (data_dir or DEFAULT_DATASET_DIR) / f"{split}.yaml"


def _case(path: Path, raw: Any, split: str) -> EvalCase:

    if not isinstance(raw, dict):
        raise EvalDatasetError(f"'{path}': cada caso precisa ser um mapa.")

    def required(field: str) -> Any:

        if field not in raw:
            raise EvalDatasetError(
                f"'{path}': caso '{raw.get('id', '?')}' sem o campo '{field}'."
            )

        return raw[field]

    expected_plan = raw.get("expected_plan") or []
    expected_methods = raw.get("expected_methods") or []
    expected_operations = raw.get("expected_operations") or []

    if not isinstance(expected_plan, list):
        raise EvalDatasetError(
            f"'{path}': caso '{raw.get('id', '?')}': expected_plan precisa ser lista."
        )

    return EvalCase(
        id=str(required("id")),
        category=str(required("category")),
        split=str(raw.get("split", split)),
        language=str(raw.get("language", "pt")),
        question=str(required("question")),
        expected_behavior=str(required("expected_behavior")),
        expected_route=str(required("expected_route")),
        expected_refusal_reason=_optional(raw.get("expected_refusal_reason")),
        expected_plan=tuple(expected_plan),
        expected_methods=tuple(_method_name(item) for item in expected_methods),
        expected_operations=tuple(_operation(item) for item in expected_operations),
        expected_result_ref=_optional(raw.get("expected_result_ref")),
        severity=str(required("severity")),
        demo=bool(raw.get("demo", False)),
        fixtures=dict(raw.get("fixtures") or {}),
        definitions_ref=str(raw.get("definitions_ref", "")),
        notes=str(raw.get("notes", "")),
        redteam_check=raw.get("redteam_check") or None,
    )


def _optional(value: Any) -> str | None:

    if value is None:
        return None

    return str(value)


def _method_name(value: Any) -> str:

    return "null" if value is None else str(value)


def _operation(raw: Any) -> dict:

    if isinstance(raw, str):
        return {"type": raw, "params": {}}

    if isinstance(raw, dict) and "type" in raw:
        return {"type": str(raw["type"]), "params": dict(raw.get("params") or {})}

    raise EvalDatasetError(f"operação inválida no dataset: {raw!r}.")


def _validate(dataset: EvalDataset) -> None:

    if dataset.split not in SPLITS:
        raise EvalDatasetError(
            f"'{dataset.path}': split '{dataset.split}' fora de {SPLITS}."
        )

    seen: set[str] = set()

    for case in dataset.cases:
        where = f"'{dataset.path}': caso '{case.id}'"

        if case.id in seen:
            raise EvalDatasetError(f"{where}: id repetido no split.")

        seen.add(case.id)

        _validate_identity(case, dataset, where)
        _validate_behavior(case, where)
        _validate_fixtures(case, where)


def _validate_identity(case: EvalCase, dataset: EvalDataset, where: str) -> None:

    if case.split != dataset.split:
        raise EvalDatasetError(
            f"{where}: split do caso difere do arquivo ({case.split})."
        )

    if not case.language:
        raise EvalDatasetError(f"{where}: language vazia.")

    if not case.question.strip():
        raise EvalDatasetError(f"{where}: question vazia.")

    if case.expected_result_ref is not None and not case.expected_result_ref:
        raise EvalDatasetError(f"{where}: expected_result_ref vazio.")


def _validate_behavior(case: EvalCase, where: str) -> None:

    if case.expected_behavior not in BEHAVIORS:
        raise EvalDatasetError(
            f"{where}: expected_behavior '{case.expected_behavior}' inválido."
        )

    if case.expected_route not in ROUTE_BY_BEHAVIOR[case.expected_behavior]:
        raise EvalDatasetError(
            f"{where}: rota '{case.expected_route}' não casa com "
            f"'{case.expected_behavior}'."
        )

    if case.severity not in SEVERITIES:
        raise EvalDatasetError(f"{where}: severity '{case.severity}' inválida.")

    if case.expected_behavior in ANSWER_BEHAVIORS:
        _validate_answer(case, where)
    else:
        _validate_termination(case, where)


def _validate_answer(case: EvalCase, where: str) -> None:

    analytical = case.expected_route == InterpretationRoute.ANALYTICAL.value

    if case.expected_refusal_reason is not None:
        raise EvalDatasetError(
            f"{where}: resposta não declara expected_refusal_reason."
        )

    if analytical and not case.expected_plan:
        raise EvalDatasetError(
            f"{where}: rota analytical exige expected_plan não vazio."
        )

    if not analytical and case.expected_plan:
        raise EvalDatasetError(
            f"{where}: rota {case.expected_route} não carrega expected_plan."
        )

    if case.expected_methods and not case.expected_plan:
        raise EvalDatasetError(f"{where}: expected_methods sem plano de cálculo.")


def _validate_termination(case: EvalCase, where: str) -> None:

    if case.expected_plan or case.expected_methods or case.expected_operations:
        raise EvalDatasetError(
            f"{where}: caso de recusa/esclarecimento não carrega planos."
        )

    if case.expected_behavior == "clarify":
        if case.expected_refusal_reason is not None:
            raise EvalDatasetError(f"{where}: clarify não tem motivo de recusa.")

        return

    reasons = {reason.value for reason in RefusalReason}

    if case.expected_refusal_reason not in reasons:
        raise EvalDatasetError(f"{where}: expected_refusal_reason ausente ou inválido.")

    if case.expected_refusal_reason == RefusalReason.INPUT_POLICY.value:
        raise EvalDatasetError(
            f"{where}: input_policy é do guardrail (data/eval/redteam.yaml)."
        )


def _validate_fixtures(case: EvalCase, where: str) -> None:

    if "seed" not in case.fixtures:
        raise EvalDatasetError(f"{where}: fixtures precisa declarar 'seed'.")

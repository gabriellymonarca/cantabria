"""Camada `engine`: o motor × o oráculo independente, offline.

Para cada caso do split com `expected_plan`, o harness executa o caminho real
do motor (`run_calculation` sobre o repositório de fixture) e compara célula a
célula com:
- o artefato congelado (`expected_result_ref` → `data/oracle/oracle_v1.yaml`), ou
- `compute_expected` do fixture independente, quando o plano cabe no
  `parity-tiny-v1` e não há artefato.

Planos fora do fixture são `skip`, com o motivo no detalhe. A paridade com o
ClickHouse real é de `utils/validate_oracle.py`
(integração, Docker) — este caminho é o do núcleo, sem armazém.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml

from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from contexts.financial_calculation.adapters.outbound.in_memory_calculation_store import (
    InMemoryCalculationStore,
)
from contexts.financial_calculation.application.commands.run_calculation import (
    run_calculation,
)
from contexts.financial_calculation.domain.calculation_result import (
    CalculationResult,
    Number,
)
from eval.dataset import ANSWER_BEHAVIORS, EvalCase, EvalDataset
from eval.fixture_repository import (
    OracleFixtureRepository,
    load_fixture,
    plan_supported_by_fixture,
)
from eval.plans import build_calculation_plan
from eval.report import CaseOutcome, LayerOutcome
from shared.comparison import numbers_equal, parse_expected, parse_tolerance

MismatchKind = Literal["match", "missing", "value", "extra"]


@dataclass(frozen=True)
class CellObservation:
    """Uma célula comparada: período, sujeitos, esperado, motor e veredito."""

    period: str
    subjects: dict
    expected: Number | None
    actual: Number | None
    kind: MismatchKind

    @property
    def ok(self) -> bool:

        return self.kind == "match"


def cells_from_result(result: CalculationResult) -> dict[tuple, Number | None]:
    """Indexa as linhas do motor por (período, sujeitos ordenados)."""

    return {
        (row.period, tuple(sorted(row.subjects.items()))): row.value
        for row in result.values
    }


def compare_cells(
    actual: dict[tuple, Number | None],
    expected: Iterable[tuple[str, dict, Number | None]],
    tolerance: Decimal,
) -> list[CellObservation]:
    """Compara o resultado do motor com as células esperadas (e aponta extras)."""

    observations: list[CellObservation] = []
    expected_keys: set[tuple] = set()

    for period, subjects, value in expected:
        key = (str(period), tuple(sorted((subjects or {}).items())))
        expected_keys.add(key)
        found = actual.get(key)

        if key not in actual:
            observations.append(
                CellObservation(
                    str(period), dict(subjects or {}), value, None, "missing"
                )
            )
            continue

        if numbers_equal(found, value, tolerance):
            observations.append(
                CellObservation(
                    str(period), dict(subjects or {}), value, found, "match"
                )
            )
        else:
            observations.append(
                CellObservation(
                    str(period), dict(subjects or {}), value, found, "value"
                )
            )

    for period, subjects in sorted(set(actual) - expected_keys):
        observations.append(
            CellObservation(
                str(period), dict(subjects), None, actual[(period, subjects)], "extra"
            )
        )

    return observations


def expected_from_artifact(case: dict) -> list[tuple[str, dict, Number | None]]:

    return [
        (
            str(item["period"]),
            dict(item.get("subjects") or {}),
            parse_expected(item["value"]),
        )
        for item in case["expected"]
    ]


def load_oracle(path: Path | str) -> dict:

    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def oracle_case(oracle: dict, case_id: str) -> dict:

    for case in oracle["cases"]:
        if case["id"] == case_id:
            return case

    raise KeyError(f"caso '{case_id}' não existe no oráculo congelado.")


def run_engine_layer(
    dataset: EvalDataset,
    oracle_path: Path | str,
) -> LayerOutcome:
    """Executa os casos de cálculo do split contra o oráculo; nada de rede."""

    fixture = load_fixture()
    repository = OracleFixtureRepository(fixture)
    store = InMemoryCalculationStore()
    oracle = load_oracle(oracle_path)
    tolerance = parse_tolerance(str(oracle["tolerance"]))
    catalog_version = YamlSemanticCatalogAdapter().load_active().catalog_version
    snapshot = repository.snapshot_version()
    outcomes: list[CaseOutcome] = []

    for case in dataset.cases:
        outcomes.append(
            _run_case(
                case,
                repository,
                store,
                oracle,
                tolerance,
                catalog_version,
                snapshot,
            )
        )

    return LayerOutcome(
        layer="engine",
        summary=(
            "valores do motor × oráculo independente no fixture parity-tiny-v1 "
            "(tolerância 1e-9); sem ClickHouse"
        ),
        outcomes=tuple(outcomes),
        total_cases=len(dataset.cases),
    )


def _run_case(
    case: EvalCase,
    repository: OracleFixtureRepository,
    store: InMemoryCalculationStore,
    oracle: dict,
    tolerance: Decimal,
    catalog_version: str,
    snapshot: str,
) -> CaseOutcome:

    if case.expected_behavior not in ANSWER_BEHAVIORS:
        return CaseOutcome(
            case_id=case.id,
            status="skip",
            detail=f"não é caso de execução (rota {case.expected_route}).",
        )

    if not case.expected_plan:
        return CaseOutcome(
            case_id=case.id,
            status="skip",
            detail=f"sem plano de cálculo (rota {case.expected_route}).",
        )

    failures: list[str] = []
    unsupported: list[str] = []
    evaluated = 0

    for index, plan_data in enumerate(case.expected_plan):
        plan = build_calculation_plan(f"{case.id}-p{index + 1}", plan_data)

        if not plan_supported_by_fixture(plan):
            unsupported.append(f"p{index + 1}")
            continue

        if case.expected_result_ref is not None:
            expected = expected_from_artifact(
                oracle_case(oracle, case.expected_result_ref)
            )
        else:
            expected = repository.expected_cells(plan)

        actual = cells_from_result(
            run_calculation(plan, repository, store, catalog_version, snapshot)
        )
        observations = compare_cells(actual, expected, tolerance)
        evaluated += 1
        mismatches = [item for item in observations if not item.ok]

        if mismatches:
            failures.append(
                f"plano p{index + 1}: {len(mismatches)}/{len(observations)} "
                "células divergentes: "
                + "; ".join(_format_observation(item) for item in mismatches[:5])
            )

    if failures:
        return CaseOutcome(case_id=case.id, status="fail", detail=" | ".join(failures))

    if evaluated == 0:
        return CaseOutcome(
            case_id=case.id,
            status="skip",
            detail=(
                "plano(s) fora do fixture parity-tiny-v1: "
                + ", ".join(unsupported)
                + "."
            ),
        )

    detail = f"{evaluated} plano(s) conferidos com o oráculo."

    if unsupported:
        detail += f" Fora do fixture (não avaliados): {', '.join(unsupported)}."

    return CaseOutcome(case_id=case.id, status="pass", detail=detail)


def _display(value: Number | None) -> str:

    if value is None:
        return "ausente"

    return str(value)


def _format_observation(observation: CellObservation) -> str:

    subjects = (
        ", ".join(
            f"{key}={value}" for key, value in sorted(observation.subjects.items())
        )
        or "(total)"
    )

    return (
        f"{observation.period} [{subjects}] esperado "
        f"{_display(observation.expected)} × motor {_display(observation.actual)}"
        f" ({observation.kind})"
    )

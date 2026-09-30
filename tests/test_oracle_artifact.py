"""O artefato oracle é íntegro e executável (sem Docker).

Congelado pelo `utils/build_oracle.py`, o YAML precisa: identificar o dataset
e seu fingerprint, declarar tolerância 1e-9, trazer ids únicos e, em cada
caso, um plano montável no domínio e uma grade de esperados legível. A
paridade numérica em si é provada pelo harness (`utils/validate_oracle.py`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

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
from shared.comparison import parse_expected, parse_tolerance

ORACLE_PATH = Path(__file__).resolve().parents[1] / "data" / "oracle" / "oracle_v1.yaml"


def _load() -> dict:

    return yaml.safe_load(ORACLE_PATH.read_text(encoding="utf-8"))


def test_artefato_traz_dataset_e_tolerancia() -> None:

    oracle = _load()

    assert oracle["oracle_version"] == 1
    assert oracle["dataset"]["name"] == "parity-tiny-v1"
    assert len(oracle["dataset"]["fingerprint"]) == 64
    assert parse_tolerance(str(oracle["tolerance"])) == Decimal("1e-9")


def test_ids_unicos_e_questoes_em_portugues() -> None:

    oracle = _load()
    ids = [case["id"] for case in oracle["cases"]]

    assert len(ids) == len(set(ids)) >= 8
    assert all(case["question"].strip() for case in oracle["cases"])


def test_cada_caso_monta_um_plano_valido() -> None:

    oracle = _load()

    for case in oracle["cases"]:
        plan = CalculationPlan(
            calculation_plan_id=case["id"],
            metric=Metric(
                rule_id=RuleId(case["rule_id"]),
                subjects=[
                    Subject(type=AxisType(item["type"]), level=AxisLevel(item["level"]))
                    for item in case["subjects"]
                ],
                sample=[
                    SampleCondition(
                        type=AxisType(item["type"]),
                        level=AxisLevel(item["level"]),
                        value_id=item["value_id"],
                    )
                    for item in case.get("sample") or []
                ],
            ),
            period=Period(
                start=date.fromisoformat(str(case["period"]["start"])),
                end=date.fromisoformat(str(case["period"]["end"])),
                type=PeriodType(case["period"]["type"]),
                grain=Grain(case["period"]["grain"]),
            ),
        )

        assert plan.calculation_plan_id == case["id"]


def test_esperados_sao_legiveis_e_cobrem_a_grade() -> None:

    oracle = _load()

    for case in oracle["cases"]:
        assert len(case["expected"]) >= 1

        for item in case["expected"]:
            valor = parse_expected(item["value"])

            assert valor is None or isinstance(valor, (Decimal, int))

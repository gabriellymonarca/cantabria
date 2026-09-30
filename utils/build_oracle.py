#!/usr/bin/env python3
"""Congela o oracle: valores esperados calculados fora do motor.

Lê o fixture independente (`utils/oracle_fixture.py`, Python puro sobre
Decimal, sem importar `src/`) e escreve `data/oracle/oracle_v1.yaml` com o
plano de cálculo, a grade completa de valores esperados e a tolerância 1e-9.
Rode de novo sempre que o fixture mudar; o harness prova que o motor lê o
mesmo dado comparando o fingerprint.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from utils.oracle_fixture import (  # noqa: E402
    REFERENCE_DATE,
    compute_expected,
    fixture_fingerprint,
)

ORACLE_PATH = REPO_ROOT / "data" / "oracle" / "oracle_v1.yaml"
TOLERANCE = "1e-9"

P_3M = {"start": "2026-06-01", "end": "2026-08-31", "type": "series", "grain": "month"}
P_Q = {"start": "2026-06-01", "end": "2026-08-31", "type": "series", "grain": "quarter"}
P_TOTAL = {
    "start": "2026-06-01",
    "end": "2026-08-31",
    "type": "series",
    "grain": "total",
}
S_AUG = {
    "start": "2026-08-31",
    "end": "2026-08-31",
    "type": "snapshot",
    "grain": "month",
}

SEGMENT = {"type": "customer_segmentation", "level": "segment"}
PRODUCT = {"type": "product", "level": "product"}
TOTAL = {"type": "total", "level": "total"}
HIGH_PRINC = {
    "type": "customer_principality",
    "level": "principality_depth",
    "value_id": "high",
}

CASES = [
    {
        "id": "ORACLE-01",
        "question": "Qual a rentabilidade mensal por segmento entre junho e agosto/26?",
        "rule_id": "profitability",
        "subjects": [SEGMENT],
        "sample": [],
        "period": P_3M,
    },
    {
        "id": "ORACLE-02",
        "question": "Qual a rentabilidade mensal por produto entre junho e agosto/26?",
        "rule_id": "profitability",
        "subjects": [PRODUCT],
        "sample": [],
        "period": P_3M,
    },
    {
        "id": "ORACLE-03",
        "question": "Qual a rentabilidade mensal por segmento e produto entre junho e agosto/26?",
        "rule_id": "profitability",
        "subjects": [SEGMENT, PRODUCT],
        "sample": [],
        "period": P_3M,
    },
    {
        "id": "ORACLE-04",
        "question": "Qual o saldo em carteira por segmento no trimestre?",
        "rule_id": "outstanding_balance",
        "subjects": [SEGMENT],
        "sample": [],
        "period": P_Q,
    },
    {
        "id": "ORACLE-05",
        "question": "Quantos contratos ativos por segmento em agosto/26?",
        "rule_id": "contract_count",
        "subjects": [SEGMENT],
        "sample": [],
        "period": S_AUG,
    },
    {
        "id": "ORACLE-06",
        "question": "Quantos clientes por produto em agosto/26?",
        "rule_id": "customer_count",
        "subjects": [PRODUCT],
        "sample": [],
        "period": S_AUG,
    },
    {
        "id": "ORACLE-07",
        "question": "Qual a rentabilidade total em agosto/26?",
        "rule_id": "profitability",
        "subjects": [TOTAL],
        "sample": [],
        "period": S_AUG,
    },
    {
        "id": "ORACLE-08",
        "question": "Qual o produto mais rentável entre clientes de alta Principalidade em agosto/26?",
        "rule_id": "profitability",
        "subjects": [PRODUCT],
        "sample": [HIGH_PRINC],
        "period": S_AUG,
    },
    {
        "id": "ORACLE-09",
        "question": "Qual a rentabilidade do trimestre por segmento?",
        "rule_id": "profitability",
        "subjects": [SEGMENT],
        "sample": [],
        "period": P_Q,
    },
    {
        "id": "ORACLE-10",
        "question": "Qual a rentabilidade acumulada da janela por segmento?",
        "rule_id": "profitability",
        "subjects": [SEGMENT],
        "sample": [],
        "period": P_TOTAL,
    },
]


def _format_value(value: Decimal | int | None) -> str:

    if value is None:
        return "null"

    if isinstance(value, int):
        return str(value)

    return f"{value:.12f}".rstrip("0").rstrip(".")


def _dump_subjects(subjects: dict) -> str:

    if not subjects:
        return "{}"

    inner = ", ".join(f"{key}: {valor}" for key, valor in subjects.items())

    return "{ " + inner + " }"


def _dump_case(case: dict) -> list[str]:

    linhas = [
        f"  - id: {case['id']}",
        f'    question: "{case["question"]}"',
        f"    rule_id: {case['rule_id']}",
        "    subjects:",
    ]

    for subject in case["subjects"]:
        linhas.append(
            f"      - {{ type: {subject['type']}, level: {subject['level']} }}"
        )

    if case["sample"]:
        linhas.append("    sample:")
        for condition in case["sample"]:
            linhas.append(
                f"      - {{ type: {condition['type']},"
                f" level: {condition['level']},"
                f" value_id: {condition['value_id']} }}"
            )
    else:
        linhas.append("    sample: []")

    period = case["period"]
    linhas.append(
        f"    period: {{ start: {period['start']}, end: {period['end']},"
        f" type: {period['type']}, grain: {period['grain']} }}"
    )
    linhas.append("    expected:")

    for bucket, grupo, valor in case["expected"]:
        linhas.append(
            f"      - {{ period: {bucket},"
            f" subjects: {_dump_subjects(grupo)},"
            f" value: {_format_value(valor)} }}"
        )

    return linhas


def main() -> None:

    for case in CASES:
        case["expected"] = compute_expected(
            case["rule_id"], case["subjects"], case["sample"], case["period"]
        )

    linhas = [
        "oracle_version: 1",
        "dataset:",
        "  name: parity-tiny-v1",
        f"  reference_date: {REFERENCE_DATE.isoformat()}",
        f"  fingerprint: {fixture_fingerprint()}",
        f'tolerance: "{TOLERANCE}"',
        "cases:",
    ]

    for case in CASES:
        linhas.extend(_dump_case(case))

    ORACLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ORACLE_PATH.write_text("\n".join(linhas) + "\n", encoding="utf-8")

    total = sum(len(case["expected"]) for case in CASES)
    print(f"oracle v1: {len(CASES)} casos, {total} células em {ORACLE_PATH}")
    print(f"fingerprint: {fixture_fingerprint()}")

    for case in CASES:
        print(f"  {case['id']}: {len(case['expected'])} células")


if __name__ == "__main__":
    main()

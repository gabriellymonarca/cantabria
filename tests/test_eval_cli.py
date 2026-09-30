"""CLI do harness: offline de ponta a ponta, relatório e exit codes.

Nenhum teste chama LLM ou rede: `--layer all` sem `--live` deve rodar só as
camadas determinísticas e marcar as generativas como `skipped (offline)`.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from eval.__main__ import main

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "eval" / "dev.yaml"


def test_cli_offline_gera_relatorio_md_e_json(tmp_path: Path) -> None:

    code = main(["--layer", "all", "--split", "dev", "--report", str(tmp_path)])

    assert code == 0

    md_path = tmp_path / "eval-dev.md"
    json_path = tmp_path / "eval-dev.json"

    assert md_path.is_file()
    assert json_path.is_file()

    text = md_path.read_text(encoding="utf-8")

    assert "Resultado:** ✅ sem falhas" in text
    assert "`engine`" in text
    assert "`redteam`" in text
    assert "`planner`" in text

    report = json.loads(json_path.read_text(encoding="utf-8"))
    layers = {layer["layer"]: layer for layer in report["layers"]}

    assert layers["engine"]["outcomes"]
    assert layers["engine"]["total_cases"] == 80
    assert layers["redteam"]["total_cases"] >= 8
    assert layers["planner"]["skipped_cases"] == 80
    assert layers["baseline"]["total_cases"] == 8
    assert {item["status"] for item in layers["baseline"]["outcomes"]} == {"skip"}
    assert not (tmp_path / "baseline-dev.md").exists()
    assert report["live"] is False


def test_cli_sem_dataset_retorna_2(tmp_path: Path) -> None:

    missing = tmp_path / "nao-existe.yaml"
    code = main(["--layer", "engine", "--dataset", str(missing)])

    assert code == 2


def test_cli_com_falha_retorna_1_e_lista_o_caso(tmp_path: Path) -> None:

    bad_case = {
        "id": "BAD-01",
        "category": "sanity",
        "split": "dev",
        "language": "pt",
        "question": "Qual a rentabilidade mensal por segmento?",
        "expected_behavior": "answer",
        "expected_route": "analytical",
        "expected_refusal_reason": None,
        "expected_plan": [
            {
                "rule_id": "profitability",
                "subjects": [{"type": "customer_segmentation", "level": "segment"}],
                "sample": [],
                "period": {
                    "start": "2026-06-01",
                    "end": "2026-08-31",
                    "type": "series",
                    "grain": "month",
                },
            }
        ],
        "expected_methods": ["null"],
        "expected_operations": [],
        # Artefato de OUTRO plano (produto): o gold não casa e o motor falha.
        "expected_result_ref": "ORACLE-02",
        "severity": "high",
        "demo": False,
        "fixtures": {"seed": 42},
        "definitions_ref": "teste",
        "notes": "",
    }

    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, "split": "dev", "cases": [bad_case]}),
        encoding="utf-8",
    )
    report = tmp_path / "report.md"

    code = main(
        [
            "--layer",
            "engine",
            "--dataset",
            str(path),
            "--report",
            str(report),
        ]
    )

    assert code == 1

    text = report.read_text(encoding="utf-8")

    assert "BAD-01" in text
    assert "❌" in text


def test_dev_yaml_fica_no_checkout() -> None:

    assert DEV.is_file()

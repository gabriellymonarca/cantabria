"""Camada `engine` offline: motor × oráculo, sem ClickHouse e sem rede.

A paridade numérica do núcleo é exercitada no fixture `parity-tiny-v1`; o gold
vem do oráculo independente (artefato congelado ou `compute_expected`). Planos
fora do fixture são `skip` explícito.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from eval.dataset import load_dataset
from eval.engine import (
    cells_from_result,
    compare_cells,
    expected_from_artifact,
    load_oracle,
    run_engine_layer,
)

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "eval" / "dev.yaml"
ORACLE = ROOT / "data" / "oracle" / "oracle_v1.yaml"


def _layer():

    return run_engine_layer(load_dataset(DEV), ORACLE)


def test_camada_engine_roda_offline_sem_falhas() -> None:

    layer = _layer()

    assert layer.failed == ()
    assert layer.counts["pass"] >= 30
    assert layer.total_cases == 80


def test_casos_com_artefato_congelado_passam() -> None:

    layer = _layer()
    by_id = {outcome.case_id: outcome for outcome in layer.outcomes}

    for case_id in ("DEV-Q01", "DEV-Q03", "DEV-Q04"):
        assert by_id[case_id].status == "pass", by_id[case_id].detail


def test_planos_fora_do_fixture_sao_skip_explicito() -> None:

    layer = _layer()
    by_id = {outcome.case_id: outcome for outcome in layer.outcomes}

    # eixo person_type não existe no fixture mínimo.
    assert by_id["DEV-A07"].status == "skip"
    assert "parity-tiny-v1" in by_id["DEV-A07"].detail

    # rota documental não é caso de execução.
    assert by_id["DEV-F49"].status == "skip"


def test_comparacao_de_celulas_ausencia_nao_e_zero() -> None:

    actual = {("2026-08-31", ()): None}
    expected = [("2026-08-31", {}, None)]

    assert all(item.ok for item in compare_cells(actual, expected, Decimal("1e-9")))

    expected_zero = [("2026-08-31", {}, Decimal("0"))]
    observations = compare_cells(actual, expected_zero, Decimal("1e-9"))

    assert not all(item.ok for item in observations)
    assert observations[0].kind == "value"


def test_comparacao_aponta_celula_extra_e_faltante() -> None:

    actual = {("2026-08-31", (("product.product", "Cartão"),)): Decimal("1")}
    expected = [
        ("2026-08-31", {"product.product": "Consignado"}, Decimal("1")),
    ]

    kinds = {item.kind for item in compare_cells(actual, expected, Decimal("1e-9"))}

    assert kinds == {"missing", "extra"}


def test_cells_from_result_indexa_por_periodo_e_sujeitos() -> None:

    class _Row:
        period = "2026-08-31"
        subjects = {"product.product": "Cartão"}
        value = Decimal("0.5")

    class _Result:
        values = [_Row()]

    cells = cells_from_result(_Result())

    assert cells[("2026-08-31", (("product.product", "Cartão"),))] == Decimal("0.5")


def test_artefato_tem_tolerancia_e_casos() -> None:

    oracle = load_oracle(ORACLE)

    assert oracle["tolerance"] == "1e-9"
    assert oracle["cases"]

    expected = expected_from_artifact(oracle["cases"][0])

    assert expected

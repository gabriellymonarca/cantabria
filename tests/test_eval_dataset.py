"""Schema e integridade do dataset de avaliação (split dev + redteam).

Sem rede, sem LLM: o teste valida id único, rota/comportamento por caso, os
campos obrigatórios por rota, a montagem de cada plano gold com os value
objects do motor e a referência a casos existentes do oráculo congelado.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from contexts.financial_analysis.domain.analysis_plan import (
    OperationType,
    StatisticalMethodType,
)
from eval.dataset import (
    ANSWER_BEHAVIORS,
    EvalDatasetError,
    load_dataset,
)
from eval.plans import build_calculation_plan
from eval.redteam import load_attacks

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "eval" / "dev.yaml"
REDTEAM = ROOT / "data" / "eval" / "redteam.yaml"
ORACLE = ROOT / "data" / "oracle" / "oracle_v1.yaml"

EXPECTED_MIN_CASES = 60
EXPECTED_MAX_CASES = 80


def _dataset():

    return load_dataset(DEV)


def test_split_dev_tem_entre_60_e_80_casos() -> None:

    dataset = _dataset()

    assert EXPECTED_MIN_CASES <= len(dataset.cases) <= EXPECTED_MAX_CASES
    assert dataset.split == "dev"
    assert dataset.version == 1


def test_ids_sao_unicos_e_campos_basicos_preenchidos() -> None:

    dataset = _dataset()
    ids = [case.id for case in dataset.cases]

    assert len(ids) == len(set(ids))
    assert all(case.question.strip() for case in dataset.cases)
    assert all(case.language == "pt" for case in dataset.cases)
    assert all(case.split == "dev" for case in dataset.cases)


def test_cada_plano_gold_monta_um_plano_do_motor() -> None:

    dataset = _dataset()
    built = 0

    for case in dataset.cases:
        for index, plan_data in enumerate(case.expected_plan):
            plan = build_calculation_plan(f"{case.id}-{index}", plan_data)

            assert plan.calculation_plan_id

            built += 1

    assert built >= 40


def test_metodos_e_operacoes_do_gold_existem_no_catalogo() -> None:

    dataset = _dataset()
    methods = {item.value for item in StatisticalMethodType}
    operations = {item.value for item in OperationType}

    for case in dataset.cases:
        assert set(case.expected_methods) <= methods, case.id

        for operation in case.expected_operations:
            assert operation["type"] in operations, case.id


def test_referencias_de_oraculo_apontam_para_casos_congelados() -> None:

    dataset = _dataset()
    oracle = yaml.safe_load(ORACLE.read_text(encoding="utf-8"))
    oracle_ids = {case["id"] for case in oracle["cases"]}

    refs = [
        case.expected_result_ref
        for case in dataset.cases
        if case.expected_result_ref is not None
    ]

    assert refs
    assert set(refs) <= oracle_ids


def test_casos_de_armadilha_estao_no_dev() -> None:

    dataset = _dataset()
    ids = {case.id for case in dataset.cases}

    # média de taxas (métrica recusada), estoque, ausência, small-cell e as
    # armadilhas de rollup/contagem pedidas pela rubrica.
    assert {
        "DEV-A02",  # média de taxas
        "DEV-D38",  # ponderada vs. simples
        "DEV-C23",  # rollup de trimestre
        "DEV-Q04",  # rentabilidade do trimestre (ORACLE-09)
        "DEV-Q05",  # estoque nunca somado entre meses
        "DEV-Q03",  # contagem distinta de clientes por produto
        "DEV-Q06",  # contagem distinta de contratos por segmento × produto
        "DEV-Q01",  # ausência (null com motivo)
        "DEV-Q02",  # small-cell (k = 10)
    } <= ids


def test_casos_de_resposta_analitica_tem_plano_e_metodo() -> None:

    dataset = _dataset()

    for case in dataset.cases:
        if case.expected_behavior not in ANSWER_BEHAVIORS:
            continue

        if case.expected_route != "analytical":
            continue

        assert case.expected_plan, case.id
        assert case.expected_methods, case.id


def test_redteam_tem_pelo_menos_oito_ataques_unicos() -> None:

    attacks = load_attacks(REDTEAM)
    ids = [attack.id for attack in attacks]

    assert len(attacks) >= 8
    assert len(ids) == len(set(ids))

    kinds = {attack.kind for attack in attacks}

    assert {"input_guard", "plan_validation"} <= kinds


def test_schema_rejeita_dataset_invalido(tmp_path: Path) -> None:

    good = yaml.safe_load(DEV.read_text(encoding="utf-8"))
    case = dict(good["cases"][0])

    def _write(cases: list[dict]) -> Path:

        path = tmp_path / "bad.yaml"
        path.write_text(
            yaml.safe_dump({"version": 1, "split": "dev", "cases": cases}),
            encoding="utf-8",
        )

        return path

    duplicate = [case, dict(case)]

    with pytest.raises(EvalDatasetError, match="id repetido"):
        load_dataset(_write(duplicate))

    invalid_behavior = [{**case, "id": "X1", "expected_behavior": "maybe"}]

    with pytest.raises(EvalDatasetError, match="expected_behavior"):
        load_dataset(_write(invalid_behavior))

    answer_without_plan = [
        {
            **case,
            "id": "X2",
            "expected_behavior": "answer",
            "expected_route": "analytical",
            "expected_plan": None,
            "expected_methods": [],
        }
    ]

    with pytest.raises(EvalDatasetError, match="expected_plan"):
        load_dataset(_write(answer_without_plan))

    refusal_with_plan = [
        {
            **case,
            "id": "X3",
            "expected_behavior": "refuse_scope",
            "expected_route": "refuse",
            "expected_refusal_reason": "out_of_scope",
        }
    ]

    with pytest.raises(EvalDatasetError, match="não carrega"):
        load_dataset(_write(refusal_with_plan))

    no_seed = [{**case, "id": "X4", "fixtures": {}}]

    with pytest.raises(EvalDatasetError, match="fixtures"):
        load_dataset(_write(no_seed))

    bad_route = [
        {
            **case,
            "id": "X5",
            "expected_behavior": "clarify",
            "expected_route": "analytical",
        }
    ]

    with pytest.raises(EvalDatasetError, match="rota"):
        load_dataset(_write(bad_route))

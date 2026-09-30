#!/usr/bin/env python3
"""Valida os números do motor contra o oracle pré-computado.

Semeia o dataset mínimo do oracle num ClickHouse real, executa cada plano de
cálculo pelo caminho determinístico de produção (`execute_calculation` sobre
o adapter ClickHouse, com reuso por chave) e compara célula a célula com a
tolerância do artefato (1e-9). Antes dos números, prova que o motor leu
exatamente o dado do oracle: o fingerprint de conteúdo coletado no banco
precisa ser idêntico ao gravado no artefato.

Uso:
    python utils/validate_oracle.py
    python utils/validate_oracle.py --local --database cantabria_oracle
    python utils/validate_oracle.py --oracle data/oracle/oracle_v1.yaml

O modo padrão sobe um ClickHouse efêmero (testcontainers, mesma imagem do
teste de paridade). O `--local` usa o ClickHouse do ambiente (`CLICKHOUSE_*`)
num database de validação, sem tocar no database oficial. Qualquer divergência
numérica ou de fingerprint devolve exit code 1.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from utils.oracle_fixture import seed_rows  # noqa: E402

from contexts.financial_analysis.adapters.outbound.clickhouse_dataset_fingerprint import (  # noqa: E402
    ClickHouseDatasetFingerprintAdapter,
)
from contexts.financial_analysis.adapters.outbound.clickhouse_reference_date import (  # noqa: E402
    ClickHouseReferenceDateAdapter,
)
from contexts.financial_calculation.adapters.outbound.clickhouse_official_data import (  # noqa: E402
    ClickHouseOfficialDataRepository,
)
from contexts.financial_calculation.adapters.outbound.in_memory_calculation_store import (  # noqa: E402
    InMemoryCalculationStore,
)
from contexts.financial_calculation.application.commands.run_calculation import (  # noqa: E402
    run_calculation,
)
from eval.engine import CellObservation, cells_from_result, compare_cells  # noqa: E402
from eval.plans import build_calculation_plan  # noqa: E402
from shared.comparison import parse_expected, parse_tolerance  # noqa: E402
from shared.dataset_version import format_snapshot_version  # noqa: E402

SCHEMA_SQL = REPO_ROOT / "infra" / "clickhouse" / "init" / "00_schema.sql"
ORACLE_DEFAULT = REPO_ROOT / "data" / "oracle" / "oracle_v1.yaml"

CLIENTE_COLS = [
    "id_cliente",
    "tp_pess",
    "ds_segm_agrup",
    "ds_segm",
    "ds_subsegm_agrup",
    "ds_subsegm",
    "principalidade_score",
    "vinculacao_score",
]
PRODUTO_COLS = [
    "id_produto",
    "cd_produto",
    "ds_grupo_prod",
    "ds_produto",
    "ds_subproduto",
]
CONTRATO_COLS = ["id_contrato", "id_cliente", "dt_ini_contrato", "dt_encerramento"]
COMPOSICAO_COLS = ["id_contrato", "id_produto"]
RENT_CLIENTE_COLS = ["id_cliente", "mes_ref", "vl_saldo", "vl_margem", "data_medicao"]
RENT_ITEM_COLS = [
    "id_contrato",
    "id_produto",
    "mes_ref",
    "vl_saldo",
    "vl_margem",
    "data_medicao",
]


def _schema_statements() -> list[str]:

    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    sql = sql.replace("cantabria.", "")
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    statements = [
        statement.strip()
        for statement in "\n".join(lines).split(";")
        if statement.strip()
    ]

    return [statement for statement in statements if "CREATE DATABASE" not in statement]


def _seed_validation_database(client) -> None:

    for statement in _schema_statements():
        client.command(statement)

    rows = seed_rows()

    client.insert(
        "fato_cliente",
        [(uuid.UUID(row[0]), *row[1:]) for row in rows["fato_cliente"]],
        column_names=CLIENTE_COLS,
    )
    client.insert("dim_produto", rows["dim_produto"], column_names=PRODUTO_COLS)
    client.insert(
        "fato_contratos",
        [
            (contrato, uuid.UUID(cliente), inicio, fim)
            for contrato, cliente, inicio, fim in rows["fato_contratos"]
        ],
        column_names=CONTRATO_COLS,
    )
    client.insert(
        "fato_contrato_produtos",
        rows["fato_contrato_produtos"],
        column_names=COMPOSICAO_COLS,
    )
    client.insert(
        "fato_rentabilidade_cliente",
        [
            (uuid.UUID(cliente), *rest)
            for cliente, *rest in rows["fato_rentabilidade_cliente"]
        ],
        column_names=RENT_CLIENTE_COLS,
    )
    client.insert(
        "fato_rentabilidade_contrato_produto",
        rows["fato_rentabilidade_contrato_produto"],
        column_names=RENT_ITEM_COLS,
    )


def _build_plan(case: dict, index: int):

    return build_calculation_plan(f"{case['id']}-{index}", case)


def _display(value) -> str:

    if value is None:
        return "ausente"

    return str(value)


def _subjects_label(subjects: dict) -> str:

    if not subjects:
        return "(total)"

    return ", ".join(str(valor) for valor in subjects.values())


def _validate_case(
    case: dict, repository, store, snapshot: str
) -> tuple[int, int, list[str]]:

    tolerance = parse_tolerance(case["tolerance"])
    plan = _build_plan(case, 0)
    result = run_calculation(plan, repository, store, "oracle-v1", snapshot)

    actual = cells_from_result(result)
    expected = [
        (
            str(item["period"]),
            dict(item.get("subjects") or {}),
            parse_expected(item["value"]),
        )
        for item in case["expected"]
    ]
    observations = compare_cells(actual, expected, tolerance)
    linhas = [_observation_line(observation) for observation in observations]
    ok = sum(1 for observation in observations if observation.ok)

    return ok, len(observations), linhas


def _observation_line(observation: CellObservation) -> str:

    subjects = _subjects_label(observation.subjects)
    estado = "OK" if observation.ok else "FALHOU"

    if observation.kind == "extra":
        return (
            f"    {observation.period} | {subjects}"
            f" | esperado — | motor {_display(observation.actual)} | {estado}"
        )

    if observation.kind == "missing":
        return (
            f"    {observation.period} | {subjects}"
            f" | esperado {_display(observation.expected)} | motor SEM LINHA | {estado}"
        )

    return (
        f"    {observation.period} | {subjects}"
        f" | esperado {_display(observation.expected)}"
        f" | motor {_display(observation.actual)} | {estado}"
    )


def main() -> None:

    import yaml

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", type=Path, default=ORACLE_DEFAULT)
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--database", type=str, default="cantabria_oracle")
    args = parser.parse_args()

    oracle = yaml.safe_load(args.oracle.read_text(encoding="utf-8"))
    tolerance = parse_tolerance(str(oracle["tolerance"]))

    print(f"oracle: {args.oracle} (tolerância {tolerance})")
    print(f"dataset: {oracle['dataset']['name']}")

    if args.local:
        import clickhouse_connect

        host = os.environ.get("CLICKHOUSE_HOST", "localhost")
        port = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
        user = os.environ.get("CLICKHOUSE_SEED_USER", "default")
        password = os.environ.get("CLICKHOUSE_SEED_PASSWORD", "")

        bootstrap = clickhouse_connect.get_client(
            host=host, port=port, database="default", username=user, password=password
        )
        try:
            bootstrap.command(f"CREATE DATABASE IF NOT EXISTS {args.database}")
        finally:
            bootstrap.close()

        client = clickhouse_connect.get_client(
            host=host,
            port=port,
            database=args.database,
            username=user,
            password=password,
        )
        _seed_validation_database(client)
        repository = ClickHouseOfficialDataRepository(
            host=host,
            port=port,
            database=args.database,
            user=user,
            password=password,
        )
    else:
        from testcontainers.community.clickhouse import ClickHouseContainer

        container = ClickHouseContainer(
            "clickhouse/clickhouse-server:24.8",
            username="test",
            password="test",
            dbname="test",
        )
        container.start()

        try:
            import clickhouse_connect

            client = clickhouse_connect.get_client(
                host=container.get_container_host_ip(),
                port=container.get_exposed_port(8123),
                username="test",
                password="test",
                database="test",
            )
            _seed_validation_database(client)
            repository = ClickHouseOfficialDataRepository(
                host=container.get_container_host_ip(),
                port=container.get_exposed_port(8123),
                database="test",
                user="test",
                password="test",
            )

            falhas = _run(oracle, tolerance, client, repository, "test")
        finally:
            repository.close()
            container.stop()

        sys.exit(1 if falhas else 0)

    try:
        falhas = _run(oracle, tolerance, client, repository, args.database)
    finally:
        repository.close()
        client.close()

    sys.exit(1 if falhas else 0)


def _run(oracle: dict, tolerance, client, repository, database: str) -> int:

    fingerprint = ClickHouseDatasetFingerprintAdapter(
        client, database=database
    ).digest()
    reference = ClickHouseReferenceDateAdapter(client).latest_reference_date()
    snapshot = format_snapshot_version(
        reference.isoformat() if reference is not None else None, fingerprint
    )
    esperado_fp = oracle["dataset"]["fingerprint"]

    print(f"fingerprint do oracle: {esperado_fp}")
    print(f"fingerprint do motor:  {fingerprint}")
    print(f"dataset_version:       {snapshot}")

    falhas = 0

    if fingerprint != esperado_fp:
        print("FALHOU: o motor leu um dado diferente do oracle.")
        falhas += 1
    else:
        print("dado idêntico ao do oracle.")

    store = InMemoryCalculationStore()
    total_ok = 0
    total_celulas = 0

    for case in oracle["cases"]:
        case = {**case, "tolerance": str(tolerance)}

        print(f"\n{case['id']}: {case['question']}")

        ok, total, linhas = _validate_case(case, repository, store, snapshot)
        total_ok += ok
        total_celulas += total

        for linha in linhas:
            print(linha)

        print(f"  -> {ok}/{total} células OK")

        if ok != total:
            falhas += total - ok

    print(f"\n{total_ok}/{total_celulas} células OK no total.")

    if falhas:
        print("FALHOU: divergência entre motor e oracle.")
    else:
        print("OK: todos os números do motor conferem com o oracle.")

    return falhas


if __name__ == "__main__":
    main()

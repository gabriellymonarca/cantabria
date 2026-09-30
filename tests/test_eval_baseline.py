"""Camada `baseline`: text-to-SQL ingênuo como controle do design, sem LLM.

O gerador é um dublê que devolve SQL fixo; o SQLite é construído a partir do
fixture `parity-tiny-v1` e o gold vem do oráculo independente. Nenhum teste
chama LLM ou rede.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from eval.baseline import (
    BASELINE_CATEGORIES,
    SqlProposal,
    build_sqlite,
    render_baseline_table,
    run_baseline_layer,
    schema_prompt,
    target_cases,
)
from eval.dataset import load_dataset
from eval.fixture_repository import load_fixture

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "eval" / "dev.yaml"
ORACLE = ROOT / "data" / "oracle" / "oracle_v1.yaml"

PHYSICAL_TABLES = (
    "fato_cliente",
    "dim_produto",
    "fato_contratos",
    "fato_contrato_produtos",
    "fato_rentabilidade_cliente",
    "fato_rentabilidade_contrato_produto",
)

# Σ margem ÷ Σ saldo por trimestre × segmento: o cálculo governado (ORACLE-09).
CORRECT_Q04_SQL = """
SELECT c.ds_segm,
       CASE WHEN strftime('%m', r.mes_ref) <= '06' THEN '2026-Q2' ELSE '2026-Q3' END AS trimestre,
       SUM(r.vl_margem) / SUM(r.vl_saldo) AS rentabilidade
FROM fato_rentabilidade_cliente r
JOIN fato_cliente c ON c.id_cliente = r.id_cliente
WHERE r.mes_ref BETWEEN '2026-06-01' AND '2026-08-31'
GROUP BY 1, 2
"""

# Média de taxas: a armadilha que a arquitetura recusa (DEV-A02).
MEAN_OF_RATES_SQL = """
SELECT c.ds_segm, AVG(r.vl_margem / r.vl_saldo) AS rentabilidade_media
FROM fato_rentabilidade_cliente r
JOIN fato_cliente c ON c.id_cliente = r.id_cliente
WHERE r.mes_ref BETWEEN '2026-06-01' AND '2026-08-31'
GROUP BY 1
"""


class FakeGenerator:
    """Dublê do gerador: devolve sempre o mesmo SQL (ou nada)."""

    def __init__(self, sql: str | None):

        self.sql = sql
        self.calls = 0

    def propose_sql(self, question: str, schema: str) -> SqlProposal | None:

        self.calls += 1

        if self.sql is None:
            return None

        return SqlProposal(sql=self.sql)


@pytest.fixture(scope="module")
def dataset():

    return load_dataset(DEV)


@pytest.fixture(scope="module")
def conn() -> sqlite3.Connection:

    return build_sqlite(load_fixture())


def _outcomes(dataset, sql: str | None) -> dict:

    layer = run_baseline_layer(dataset, ORACLE, live=True, generator=FakeGenerator(sql))

    return {outcome.case_id: outcome for outcome in layer.outcomes}


def test_casos_alvo_sao_as_armadilhas_de_agregacao(dataset) -> None:

    ids = tuple(case.id for case in target_cases(dataset))

    assert BASELINE_CATEGORIES == frozenset({"aggregation_trap"})
    assert ids == (
        "DEV-A02",
        "DEV-A10",
        "DEV-C23",
        "DEV-D38",
        "DEV-Q03",
        "DEV-Q04",
        "DEV-Q05",
        "DEV-Q06",
    )


def test_build_sqlite_cria_as_seis_tabelas_com_os_dados_do_fixture(conn) -> None:

    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }

    assert names == set(PHYSICAL_TABLES)

    fixture = load_fixture()
    expected = float(
        fixture.table_summaries()["fato_rentabilidade_cliente"]["sum_vl_saldo"]
    )
    (total,) = conn.execute(
        "SELECT SUM(vl_saldo) FROM fato_rentabilidade_cliente"
    ).fetchone()

    assert total == pytest.approx(expected, rel=1e-6)


def test_build_sqlite_e_somente_leitura(conn) -> None:

    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM fato_cliente")


def test_schema_prompt_expoe_nomes_fisicos_e_nao_regras_de_negocio(conn) -> None:

    schema = schema_prompt(conn)

    for table in PHYSICAL_TABLES:
        assert table in schema

    for column in ("vl_margem", "vl_saldo", "mes_ref", "dt_encerramento", "ds_segm"):
        assert column in schema

    assert "SQLite" in schema
    assert "Σ" not in schema
    assert "ponderad" not in schema.lower()


def test_sql_correto_para_caso_answer_e_correct(dataset) -> None:

    outcome = _outcomes(dataset, CORRECT_Q04_SQL)["DEV-Q04"]

    assert outcome.status == "pass"
    assert outcome.detail.startswith("CORRECT")
    assert "motor calcula (engine pass)" in outcome.detail
    assert "0.22" in outcome.detail


def test_media_de_taxas_no_caso_not_expressible_e_silent_wrong(dataset) -> None:

    outcome = _outcomes(dataset, MEAN_OF_RATES_SQL)["DEV-A02"]

    assert outcome.status == "pass"
    assert outcome.detail.startswith("SILENT_WRONG")
    assert "recusa not_expressible" in outcome.detail


def test_media_de_taxas_no_caso_answer_e_silent_wrong(dataset) -> None:

    outcome = _outcomes(dataset, MEAN_OF_RATES_SQL)["DEV-Q04"]

    assert outcome.status == "pass"
    assert outcome.detail.startswith("SILENT_WRONG")


def test_resultado_vazio_no_caso_not_expressible_e_correct(dataset) -> None:

    outcome = _outcomes(dataset, "SELECT ds_segm FROM fato_cliente WHERE 1 = 0")[
        "DEV-A02"
    ]

    assert outcome.detail.startswith("CORRECT")


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE fato_cliente",
        "SELECT * FROM tabela_que_nao_existe",
        "SELECT 1; SELECT 2",
        "WITH x AS (SELECT 1) INSERT INTO fato_contrato_produtos VALUES ('a', 'b')",
    ],
)
def test_sql_invalido_ou_destrutivo_e_error(dataset, sql: str) -> None:

    outcome = _outcomes(dataset, sql)["DEV-Q04"]

    assert outcome.status == "pass"
    assert outcome.detail.startswith("ERROR")
    assert "Traceback" not in outcome.detail


def test_sem_sql_e_no_sql(dataset) -> None:

    outcome = _outcomes(dataset, None)["DEV-Q03"]

    assert outcome.status == "pass"
    assert outcome.detail.startswith("NO_SQL")


def test_baseline_nunca_falha_o_harness(dataset) -> None:

    layer = run_baseline_layer(
        dataset, ORACLE, live=True, generator=FakeGenerator(MEAN_OF_RATES_SQL)
    )

    assert layer.layer == "baseline"
    assert layer.failed == ()
    assert layer.total_cases == 8
    assert "silent_wrong" in layer.summary


def test_offline_todos_skip_sem_chamar_o_gerador(dataset) -> None:

    generator = FakeGenerator(CORRECT_Q04_SQL)
    layer = run_baseline_layer(dataset, ORACLE, live=False, generator=generator)

    assert generator.calls == 0
    assert layer.total_cases == 8
    assert layer.counts == {"pass": 0, "fail": 0, "skip": 8}
    assert all("exige --live" in outcome.detail for outcome in layer.outcomes)


def test_render_baseline_table_lado_a_lado(dataset) -> None:

    layer = run_baseline_layer(
        dataset, ORACLE, live=True, generator=FakeGenerator(MEAN_OF_RATES_SQL)
    )
    text = render_baseline_table(layer, dataset)

    assert (
        "| Caso | Pergunta | Arquitetura | Baseline text-to-SQL | Detalhe curto |"
        in text
    )
    assert "DEV-A02" in text
    assert "recusa not_expressible" in text
    assert "silent_wrong" in text

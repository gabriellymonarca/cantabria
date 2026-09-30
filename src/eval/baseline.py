"""Camada `baseline`: text-to-SQL ingênuo como experimento de controle.

Um LLM recebe o schema físico das tabelas e gera SQL livre, sem catálogo
semântico e sem regra de negócio (prompt em `data/prompts/baseline/v1/base.md`).
O SQL roda num SQLite em memória semeado com o fixture `parity-tiny-v1`
(`utils/oracle_fixture.py`) e o resultado é comparado com o gold do oráculo
independente (artefato congelado ou `compute_expected`).

Vereditos por caso: `correct`, `silent_wrong` (número errado sem erro), `error`
(SQL inválido), `no_sql` (o modelo não devolveu SQL) e `skip` (caso fora do
fixture). Todo veredito observado conta como `pass` no harness: a camada mede o
controle e o veredito é o dado.

Limites da comparação: qualquer número do resultado que case com cada valor
esperado (também em percentual) conta; em casos com método estatístico o gold
são as células do plano de cálculo.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from contexts.financial_analysis.adapters.outbound.langchain_llm import (
    LangChainLlmAdapter,
)
from contexts.financial_analysis.ports.outbound.llm_port import (
    LlmMessage,
    LlmPort,
    StructuredOutputError,
)
from cross_cutting.config import ConfigError, load_config
from cross_cutting.resources import default_data_dir
from eval.dataset import ANSWER_BEHAVIORS, EvalCase, EvalDataset
from eval.engine import expected_from_artifact, load_oracle, oracle_case
from eval.fixture_repository import (
    OracleFixtureRepository,
    load_fixture,
    plan_supported_by_fixture,
)
from eval.live import DEFAULT_CONFIG, LiveUnavailableError
from eval.plans import build_calculation_plan
from eval.report import CaseOutcome, LayerOutcome, Status

BASELINE_CATEGORIES = frozenset({"aggregation_trap"})
PROMPT_VERSION = "v1"

Verdict = Literal["correct", "silent_wrong", "error", "no_sql", "skip"]

_LAYER = "baseline"
_STEP = "baseline"
_MAX_ROWS = 200
_MAX_SQL_CHARS = 300
_MAX_NUMBERS = 6
_QUERY_TIMEOUT_SECONDS = 5.0
_RELATIVE_TOLERANCE = 1e-6
_ABSOLUTE_TOLERANCE = 1e-9
_DETAIL_SEPARATOR = " · "

_OFFLINE_DETAIL = "skipped (offline): camada de controle exige --live."
_OFFLINE_SUMMARY = "camada de controle (text-to-SQL ingênuo); requer --live"

_ARCHITECTURE_BY_BEHAVIOR = {
    "answer": "motor calcula (engine pass)",
    "answer_with_caveat": "motor calcula (engine pass)",
    "not_expressible": "recusa not_expressible",
}

# As seis tabelas do fixture, nos nomes físicos e na ordem de `seed_rows()`.
# Tipos SQLite: TEXT para ids/descrições/datas (ISO), REAL para valores.
_TABLES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "fato_cliente",
        "um cliente",
        (
            ("id_cliente", "TEXT"),
            ("tp_pess", "TEXT"),
            ("ds_segm_agrup", "TEXT"),
            ("ds_segm", "TEXT"),
            ("ds_subsegm_agrup", "TEXT"),
            ("ds_subsegm", "TEXT"),
            ("principalidade_score", "REAL"),
            ("vinculacao_score", "REAL"),
        ),
    ),
    (
        "dim_produto",
        "catálogo de produtos",
        (
            ("id_produto", "TEXT"),
            ("cd_produto", "TEXT"),
            ("ds_grupo_prod", "TEXT"),
            ("ds_produto", "TEXT"),
            ("ds_subproduto", "TEXT"),
        ),
    ),
    (
        "fato_contratos",
        "um contrato",
        (
            ("id_contrato", "TEXT"),
            ("id_cliente", "TEXT"),
            ("dt_ini_contrato", "TEXT"),
            ("dt_encerramento", "TEXT"),
        ),
    ),
    (
        "fato_contrato_produtos",
        "contrato × produto",
        (
            ("id_contrato", "TEXT"),
            ("id_produto", "TEXT"),
        ),
    ),
    (
        "fato_rentabilidade_cliente",
        "cliente × mês",
        (
            ("id_cliente", "TEXT"),
            ("mes_ref", "TEXT"),
            ("vl_saldo", "REAL"),
            ("vl_margem", "REAL"),
            ("data_medicao", "TEXT"),
        ),
    ),
    (
        "fato_rentabilidade_contrato_produto",
        "contrato × produto × mês",
        (
            ("id_contrato", "TEXT"),
            ("id_produto", "TEXT"),
            ("mes_ref", "TEXT"),
            ("vl_saldo", "REAL"),
            ("vl_margem", "REAL"),
            ("data_medicao", "TEXT"),
        ),
    ),
)

# Comentários curtos, como num schema real: dizem o que a coluna é, sem regra
# de agregação.
_COLUMN_NOTES = {
    "id_cliente": "identificador do cliente",
    "tp_pess": "tipo de pessoa (F/J)",
    "ds_segm_agrup": "segmento agrupado",
    "ds_segm": "segmento",
    "ds_subsegm_agrup": "subsegmento agrupado",
    "ds_subsegm": "subsegmento",
    "principalidade_score": "score de principalidade (0–100)",
    "vinculacao_score": "score de vinculação (0–100)",
    "id_produto": "identificador do produto",
    "cd_produto": "código do produto",
    "ds_grupo_prod": "grupo do produto",
    "ds_produto": "produto",
    "ds_subproduto": "subproduto",
    "id_contrato": "identificador do contrato",
    "dt_ini_contrato": "início do contrato",
    "dt_encerramento": "encerramento; NULL se ativo",
    "mes_ref": "mês de referência",
    "vl_saldo": "saldo",
    "vl_margem": "margem anualizada",
    "data_medicao": "data da medição",
}

_READ_ONLY_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
    }
)

_CODE_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")
_SQL_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_SQL_PREFIX = re.compile(r"^(select|with)\b", re.IGNORECASE)
_NUMERIC_TEXT = re.compile(r"^-?\d+(\.\d+)?$")


class SqlProposal(BaseModel):
    """O que o gerador ingênuo devolve: a consulta e, opcionalmente, o porquê."""

    sql: str
    rationale: str = ""


class SqlGenerator(Protocol):
    """Contrato do gerador: pergunta + schema → proposta de SQL (ou nada)."""

    def propose_sql(self, question: str, schema: str) -> SqlProposal | None: ...


@dataclass(frozen=True)
class BaselineObservation:
    """O que foi observado num caso: veredito, SQL, números e gold."""

    case_id: str
    verdict: Verdict
    sql: str
    numbers: tuple[float, ...]
    expected: tuple[float, ...]
    note: str = ""


class BaselineSqlGenerator:
    """O gerador real: `LlmPort` configurado + prompt `baseline/v1` + schema."""

    def __init__(self, config_path: Path | str = DEFAULT_CONFIG):

        try:
            config = load_config(config_path)
        except (ConfigError, OSError, ValueError) as error:
            raise LiveUnavailableError(
                f"configuração do LLM indisponível em '{config_path}': {error}. "
                "Crie o config.yaml (veja config.example.yaml) para usar --live."
            ) from error

        self._llm: LlmPort = LangChainLlmAdapter(config.llm)
        self._system = load_prompt()

    def propose_sql(self, question: str, schema: str) -> SqlProposal | None:

        messages = [
            LlmMessage(role="system", content=self._system),
            LlmMessage(
                role="user", content=f"SCHEMA\n{schema}\n\nPERGUNTA\n{question}"
            ),
        ]

        try:
            return asyncio.run(
                self._llm.generate_structured(messages, SqlProposal, step=_STEP)
            )
        except StructuredOutputError:
            return None


def prompt_path() -> Path:

    return default_data_dir() / "prompts" / _LAYER / PROMPT_VERSION / "base.md"


def load_prompt() -> str:

    path = prompt_path()

    if not path.is_file():
        raise LiveUnavailableError(f"prompt do baseline não encontrado: {path}")

    return path.read_text(encoding="utf-8")


def prompt_hash() -> str:

    return hashlib.sha256(load_prompt().encode("utf-8")).hexdigest()[:12]


def target_cases(dataset: EvalDataset) -> tuple[EvalCase, ...]:

    return tuple(case for case in dataset.cases if case.category in BASELINE_CATEGORIES)


def build_sqlite(fixture: Any) -> sqlite3.Connection:
    """SQLite em memória com as seis tabelas físicas e as linhas do fixture."""

    conn = sqlite3.connect(":memory:")
    rows = fixture.seed_rows()

    for name, _, columns in _TABLES:
        ddl = ", ".join(f"{column} {kind}" for column, kind in columns)
        placeholders = ", ".join("?" for _ in columns)

        conn.execute(f"CREATE TABLE {name} ({ddl})")
        conn.executemany(
            f"INSERT INTO {name} VALUES ({placeholders})",
            [tuple(_sqlite_value(value) for value in row) for row in rows[name]],
        )

    conn.commit()
    conn.set_authorizer(_read_only_authorizer)

    return conn


def schema_prompt(conn: sqlite3.Connection) -> str:
    """DDL textual do SQLite, com comentários curtos e sem regra de negócio."""

    lines = ["-- Dialeto: SQLite. Datas em TEXT no formato ISO (YYYY-MM-DD).", ""]

    for name, grain, _ in _TABLES:
        columns = conn.execute(f"PRAGMA table_info({name})").fetchall()

        lines.append(f"-- {name}: {grain}")
        lines.append(f"CREATE TABLE {name} (")

        for index, (_, column, kind, *_rest) in enumerate(columns):
            comma = "," if index < len(columns) - 1 else ""

            lines.append(f"  {column} {kind}{comma}  -- {_COLUMN_NOTES[column]}")

        lines.append(");")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def sanitize_sql(sql: str) -> str:
    """Só uma instrução `SELECT`/`WITH`, sem comentários; senão `ValueError`."""

    cleaned = _CODE_FENCE.sub("", sql)
    cleaned = _SQL_COMMENT.sub(" ", cleaned).strip().rstrip(";").strip()

    if not cleaned:
        raise ValueError("SQL vazio")

    if ";" in cleaned:
        raise ValueError("mais de uma instrução")

    if not _SQL_PREFIX.match(cleaned):
        raise ValueError("só SELECT/WITH é aceito")

    return cleaned


def execute_sql(conn: sqlite3.Connection, sql: str) -> list[tuple]:
    """Executa o SQL saneado com limite de linhas e de tempo."""

    deadline = time.monotonic() + _QUERY_TIMEOUT_SECONDS

    conn.set_progress_handler(lambda: time.monotonic() > deadline, 1000)

    try:
        return conn.execute(sql).fetchmany(_MAX_ROWS)
    finally:
        conn.set_progress_handler(None, 0)


def numbers_in(rows: list[tuple]) -> tuple[float, ...]:
    """Todos os números do resultado, em qualquer coluna (texto numérico conta)."""

    numbers: list[float] = []

    for row in rows:
        for value in row:
            if value is None or isinstance(value, bool):
                continue

            if isinstance(value, int | float):
                numbers.append(float(value))
            elif isinstance(value, str) and _NUMERIC_TEXT.match(value.strip()):
                numbers.append(float(value))

    return tuple(numbers)


def judge(
    case: EvalCase,
    numbers: tuple[float, ...],
    expected: tuple[float, ...] | None,
) -> Verdict:
    """O veredito a partir dos números devolvidos e do gold do oráculo."""

    if case.expected_behavior == "not_expressible":
        return "silent_wrong" if numbers else "correct"

    if expected is None or not expected:
        return "skip"

    if all(_found(value, numbers) for value in expected):
        return "correct"

    return "silent_wrong"


def run_baseline_layer(
    dataset: EvalDataset,
    oracle_path: Path | str,
    *,
    live: bool,
    config_path: Path | str = DEFAULT_CONFIG,
    generator: SqlGenerator | None = None,
) -> LayerOutcome:
    """Roda o controle text-to-SQL em `--live`; offline devolve a camada pulada."""

    cases = target_cases(dataset)

    if not live:
        return LayerOutcome(
            layer=_LAYER,
            summary=_OFFLINE_SUMMARY,
            outcomes=tuple(
                CaseOutcome(case.id, "skip", _OFFLINE_DETAIL) for case in cases
            ),
            total_cases=len(cases),
        )

    if generator is None:
        try:
            generator = BaselineSqlGenerator(config_path)
        except LiveUnavailableError as error:
            raise LiveUnavailableError(f"camada '{_LAYER}': {error}") from error

    fixture = load_fixture()
    conn = build_sqlite(fixture)
    schema = schema_prompt(conn)
    repository = OracleFixtureRepository(fixture)
    oracle = load_oracle(oracle_path)

    observations = tuple(
        _observe_case(case, generator, conn, schema, repository, oracle, fixture)
        for case in cases
    )
    counts = Counter(observation.verdict for observation in observations)

    return LayerOutcome(
        layer=_LAYER,
        summary=(
            "text-to-SQL ingênuo (LLM + schema físico, SQLite sobre o fixture "
            "parity-tiny-v1) × oráculo — controle do design "
            f"(prompt {_LAYER}/{PROMPT_VERSION}#{prompt_hash()}); "
            f"{counts['silent_wrong']} silent_wrong / {counts['correct']} correct / "
            f"{counts['error']} error"
        ),
        outcomes=tuple(
            _to_outcome(observation, dataset.by_id(observation.case_id))
            for observation in observations
        ),
        total_cases=len(cases),
    )


def render_baseline_table(outcome: LayerOutcome, dataset: EvalDataset) -> str:
    """Tabela lado a lado (arquitetura × baseline) em Markdown."""

    lines = [
        f"# Baseline text-to-SQL ingênuo × arquitetura — split `{dataset.split}`",
        "",
        "Experimento de controle do checklist §6: um LLM com o schema físico e",
        "sem catálogo semântico gera SQL livre sobre o fixture `parity-tiny-v1`",
        "(SQLite em memória); o gold é o oráculo independente. `silent_wrong` é",
        "um número entregue sem aviso onde a arquitetura recusa ou calcula outro",
        "valor.",
        "",
        f"Resumo: {outcome.summary}.",
        "",
        "| Caso | Pergunta | Arquitetura | Baseline text-to-SQL | Detalhe curto |",
        "|---|---|---|---|---|",
    ]

    for item in outcome.outcomes:
        case = dataset.by_id(item.case_id)
        parts = _parse_detail(item.detail)

        lines.append(
            f"| {case.id} | {_cell(case.question)} | {_cell(parts['arquitetura'])} | "
            f"{_verdict_icon(parts['veredito'])} {parts['veredito']} | "
            f"{_cell(parts['detalhe'])} |"
        )

    lines.append("")

    return "\n".join(lines)


def _observe_case(
    case: EvalCase,
    generator: SqlGenerator,
    conn: sqlite3.Connection,
    schema: str,
    repository: OracleFixtureRepository,
    oracle: dict,
    fixture: Any,
) -> BaselineObservation:

    expected = _expected_values(case, repository, oracle, fixture)

    try:
        proposal = generator.propose_sql(case.question, schema)
    except Exception as error:  # noqa: BLE001 — a falha de UM caso não derruba a suíte
        if _is_authentication_error(error):
            raise LiveUnavailableError(
                f"LLM recusou a credencial ({type(error).__name__}); confira "
                "`llm.api_key` no config.yaml."
            ) from error

        return BaselineObservation(
            case.id, "no_sql", "", (), expected or (), f"{type(error).__name__}"
        )

    if proposal is None or not proposal.sql.strip():
        return BaselineObservation(case.id, "no_sql", "", (), expected or ())

    try:
        sql = sanitize_sql(proposal.sql)
        rows = execute_sql(conn, sql)
    except Exception as error:  # noqa: BLE001 — qualquer falha de execução é `error`
        return BaselineObservation(
            case.id,
            "error",
            proposal.sql,
            (),
            expected or (),
            f"{type(error).__name__}: {str(error).splitlines()[0][:120]}",
        )

    numbers = numbers_in(rows)
    verdict = judge(case, numbers, expected)
    note = ""

    if verdict == "skip":
        note = "sem gold no fixture parity-tiny-v1"
    elif any(method != "null" for method in case.expected_methods):
        note = "gold = células do plano (método estatístico fora do gold)"

    return BaselineObservation(case.id, verdict, sql, numbers, expected or (), note)


def _expected_values(
    case: EvalCase,
    repository: OracleFixtureRepository,
    oracle: dict,
    fixture: Any,
) -> tuple[float, ...] | None:
    """Gold não nulo do oráculo (artefato ou `compute_expected`); `None` sem gold."""

    if case.expected_behavior not in ANSWER_BEHAVIORS or not case.expected_plan:
        return None

    if case.expected_result_ref is not None:
        cells = expected_from_artifact(oracle_case(oracle, case.expected_result_ref))

        return _non_null(cells)

    cells: list[tuple] = []
    supported = 0

    for index, plan_data in enumerate(case.expected_plan):
        plan = build_calculation_plan(f"{case.id}-p{index + 1}", plan_data)

        if not plan_supported_by_fixture(plan, fixture):
            continue

        cells.extend(repository.expected_cells(plan))
        supported += 1

    if supported == 0:
        return None

    return _non_null(cells)


def _non_null(cells: list[tuple]) -> tuple[float, ...]:

    return tuple(float(value) for _, _, value in cells if value is not None)


def _found(expected: float, numbers: tuple[float, ...]) -> bool:

    return any(
        math.isclose(
            number,
            target,
            rel_tol=_RELATIVE_TOLERANCE,
            abs_tol=_ABSOLUTE_TOLERANCE,
        )
        for number in numbers
        for target in (expected, expected * 100)
    )


def _to_outcome(observation: BaselineObservation, case: EvalCase) -> CaseOutcome:

    status: Status = "skip" if observation.verdict == "skip" else "pass"
    parts = [
        observation.verdict.upper(),
        "arquitetura: "
        + _ARCHITECTURE_BY_BEHAVIOR.get(case.expected_behavior, case.expected_behavior),
        "sql: " + (_one_line(observation.sql) or "—"),
        "números: " + _format_numbers(observation.numbers),
        "esperados: " + _format_numbers(observation.expected),
    ]

    if observation.note:
        parts.append(observation.note)

    return CaseOutcome(case.id, status, _DETAIL_SEPARATOR.join(parts))


def _parse_detail(detail: str) -> dict[str, str]:
    """Lê de volta o detalhe montado por `_to_outcome` (veredito · campos)."""

    if _DETAIL_SEPARATOR not in detail:
        return {"veredito": "skip", "arquitetura": "—", "detalhe": detail}

    parts = detail.split(_DETAIL_SEPARATOR)
    fields = {"arquitetura": "", "números": "", "esperados": ""}

    for part in parts[1:]:
        key, _, value = part.partition(": ")

        if key in fields:
            fields[key] = value

    return {
        "veredito": parts[0].lower(),
        "arquitetura": fields["arquitetura"] or "—",
        "detalhe": f"números {fields['números']} · esperados {fields['esperados']}",
    }


def _verdict_icon(verdict: str) -> str:

    if verdict == "silent_wrong":
        return "❌"

    if verdict == "correct":
        return "✅"

    if verdict == "skip":
        return "⏭️"

    return "⚠️"


def _cell(text: str) -> str:

    return text.replace("|", "\\|").replace("\n", " ")


def _one_line(sql: str) -> str:

    collapsed = " ".join(sql.split())

    if len(collapsed) > _MAX_SQL_CHARS:
        return collapsed[: _MAX_SQL_CHARS - 1] + "…"

    return collapsed


def _format_numbers(numbers: tuple[float, ...]) -> str:

    if not numbers:
        return "—"

    shown = ", ".join(f"{number:.6g}" for number in numbers[:_MAX_NUMBERS])

    if len(numbers) > _MAX_NUMBERS:
        shown += f" (+{len(numbers) - _MAX_NUMBERS})"

    return shown


def _sqlite_value(value: Any) -> Any:

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, date):
        return value.isoformat()

    return value


def _read_only_authorizer(action: int, first: Any, *_: Any) -> int:
    """Só leitura: SELECT/READ/funções e o `PRAGMA table_info` do schema."""

    if action in _READ_ONLY_ACTIONS:
        return sqlite3.SQLITE_OK

    if action == sqlite3.SQLITE_PRAGMA and first == "table_info":
        return sqlite3.SQLITE_OK

    return sqlite3.SQLITE_DENY


def _is_authentication_error(error: Exception) -> bool:

    return "authentication" in type(error).__name__.lower() or "401" in str(error)

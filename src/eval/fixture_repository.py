"""Repositório de fixture do harness: dados oficiais do oráculo, sem ClickHouse.

O motor consome o MESMO contrato do adapter real (`OfficialDataRepository`): o
repositório agrega as linhas do fixture (`utils/oracle_fixture.py`, Python puro
e independente de `src/`) e devolve as PARCELAS; a combinação é do núcleo do
motor. Assim a camada `engine` roda `run_calculation` de ponta a ponta offline,
no fixture `parity-tiny-v1`, e compara com o oráculo independente (valores
congelados no artefato e/ou `compute_expected`). A paridade com o ClickHouse
real é de `utils/validate_oracle.py` (integração).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from contexts.financial_calculation.domain.calculation_plan import (
    AxisLevel,
    AxisType,
    CalculationPlan,
    Grain,
    PeriodType,
)
from contexts.financial_calculation.ports.outbound.official_data_repository import (
    AggregatedRow,
    MetricRequest,
    PeriodRequest,
)
from cross_cutting.resources import find_repo_root

_FIXTURE_RULES = frozenset(
    {"profitability", "outstanding_balance", "contract_count", "customer_count"}
)

_FIXTURE_SUBJECTS = frozenset(
    {
        (AxisType.CUSTOMER_SEGMENTATION.value, AxisLevel.SEGMENT.value),
        (AxisType.PRODUCT.value, AxisLevel.PRODUCT.value),
        (AxisType.TOTAL.value, AxisLevel.TOTAL.value),
    }
)

_FIXTURE_SAMPLES = frozenset(
    {
        (AxisType.CUSTOMER_PRINCIPALITY.value, AxisLevel.PRINCIPALITY_DEPTH.value),
        (AxisType.CUSTOMER_RELATIONSHIP.value, AxisLevel.RELATIONSHIP_DEPTH.value),
        (AxisType.CUSTOMER_SEGMENTATION.value, AxisLevel.SEGMENT.value),
        (AxisType.PRODUCT.value, AxisLevel.PRODUCT_GROUP.value),
    }
)

_DEPTHS = frozenset({"low", "medium", "high"})


class FixtureUnsupportedError(ValueError):
    """O plano usa uma capacidade que o fixture mínimo não cobre."""


def load_fixture() -> Any:
    """Importa `utils.oracle_fixture` pondo a raiz do checkout no `sys.path`."""

    root = find_repo_root()

    if root is not None and str(root) not in sys.path:
        sys.path.insert(0, str(root))

    import utils.oracle_fixture as fixture  # noqa: PLC0415

    return fixture


class OracleFixtureRepository:
    """`OfficialDataRepository` sobre as linhas do fixture do oráculo."""

    def __init__(self, fixture: Any | None = None):

        self._fixture = fixture or load_fixture()

    def fetch_aggregated(
        self,
        metric: MetricRequest,
        period: PeriodRequest,
    ) -> list[AggregatedRow]:

        subjects = [
            {"type": subject.type, "level": subject.level}
            for subject in metric.subjects
        ]
        sample = [
            {
                "type": condition.type,
                "level": condition.level,
                "value_id": condition.value_id,
            }
            for condition in metric.sample
        ]
        period_data = {
            "start": period.start,
            "end": period.end,
            "type": period.type,
            "grain": period.grain,
        }

        rows = self._fixture.aggregated_components(
            metric.rule_id, subjects, sample, period_data
        )

        return [
            AggregatedRow(
                subjects=dict(grupo),
                period=bucket,
                components=dict(components),
            )
            for bucket, grupo, components in rows
        ]

    def expected_cells(self, plan: CalculationPlan) -> list[tuple[str, dict, Any]]:
        """Gold independente (`compute_expected`) para o plano, em tuplas."""

        data = plan_to_data(plan)

        return self._fixture.compute_expected(
            data["rule_id"], data["subjects"], data["sample"], data["period"]
        )

    def snapshot_version(self) -> str:

        from shared.dataset_version import format_snapshot_version

        return format_snapshot_version(
            self._fixture.REFERENCE_DATE.isoformat(),
            self._fixture.fixture_fingerprint(),
        )


def plan_to_data(plan: CalculationPlan) -> dict:
    """O plano no formato de dicionário que o fixture entende."""

    return {
        "rule_id": str(plan.metric.rule_id),
        "subjects": [
            {"type": str(subject.type), "level": str(subject.level)}
            for subject in plan.metric.subjects
        ],
        "sample": [
            {
                "type": str(condition.type),
                "level": str(condition.level),
                "value_id": condition.value_id,
            }
            for condition in plan.metric.sample
        ],
        "period": {
            "start": plan.period.start.isoformat(),
            "end": plan.period.end.isoformat(),
            "type": str(plan.period.type),
            "grain": str(plan.period.grain),
        },
    }


def plan_supported_by_fixture(
    plan: CalculationPlan, fixture: Any | None = None
) -> bool:
    """O plano cabe no fixture `parity-tiny-v1`? (regras, eixos, valores, recorte)"""

    fixture = fixture or load_fixture()

    if str(plan.metric.rule_id) not in _FIXTURE_RULES:
        return False

    subjects = [
        (str(subject.type), str(subject.level)) for subject in plan.metric.subjects
    ]

    if any(subject not in _FIXTURE_SUBJECTS for subject in subjects):
        return False

    if len(subjects) > 1 and any(subject[0] == "total" for subject in subjects):
        return False

    for condition in plan.metric.sample:
        key = (str(condition.type), str(condition.level))

        if key not in _FIXTURE_SAMPLES:
            return False

        if not _known_value(fixture, key, condition.value_id):
            return False

    if plan.period.type is PeriodType.SNAPSHOT and plan.period.grain is Grain.TOTAL:
        return False

    return True


def _known_value(fixture: Any, key: tuple[str, str], value_id: str) -> bool:

    if key[1] in {"principality_depth", "relationship_depth"}:
        return value_id in _DEPTHS

    if key == ("customer_segmentation", "segment"):
        return value_id in fixture.SEGMENT_VALUE_IDS

    if key == ("product", "product_group"):
        return value_id in fixture.GROUP_VALUE_IDS

    return False


def fixture_path() -> Path:

    root = find_repo_root()

    return (root or Path.cwd()) / "data" / "oracle" / "oracle_v1.yaml"

"""Result Store em MongoDB.

O resultado verificado vira um registro `type: result` no Analysis Store, com
`result_dsc` (o `AnalysisResult` serializado) e a procedência (plano, versões,
trace). O insight entra no MESMO documento quando é gerado: o número entregue
e o texto que o explica ficam juntos para auditoria.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from pymongo.database import Database

from contexts.financial_analysis.domain.analysis_result import AnalysisResult
from contexts.financial_analysis.ports.outbound.result_store_port import (
    ResultStorePort,
)
from cross_cutting.mongo import to_bson_safe, upsert_document


def _utc_now() -> datetime:

    return datetime.now(UTC)


def _result_key(trace_id: str) -> str:

    return f"{trace_id}:result"


@dataclass
class MongoResultStore(ResultStorePort):
    """Persiste o `AnalysisResult` e o insight do turno no Analysis Store."""

    database: Database
    collection_name: str = "analysis_store"
    clock: Callable[[], datetime] = field(default=_utc_now)

    def __post_init__(self) -> None:

        self._collection = self.database[self.collection_name]

    def save_result(self, trace_id: str, result: AnalysisResult) -> None:

        upsert_document(
            self._collection,
            {"_id": _result_key(trace_id)},
            {
                "$set": {
                    "type": "result",
                    "result_id": trace_id,
                    "plan_id": result.analysis_plan_id,
                    "result_dsc": to_bson_safe(asdict(result)),
                    "trace_id": trace_id,
                    "catalog_version": result.catalog_version,
                    "dataset_version": result.dataset_version,
                    "timestamp": self.clock(),
                }
            },
        )

    def save_insight(self, trace_id: str, insight: str, verified_table: str) -> None:

        upsert_document(
            self._collection,
            {"_id": _result_key(trace_id)},
            {
                "$set": {
                    "type": "result",
                    "result_id": trace_id,
                    "insight": insight,
                    "verified_table": verified_table,
                    "insight_timestamp": self.clock(),
                }
            },
        )

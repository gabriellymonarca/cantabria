"""Chave de reuso e reprodutibilidade de um CalculationResult.

O `calculation_plan_id` e o `metric.id` são efêmeros: o mesmo cálculo pedido
duas vezes carrega rótulos diferentes. A chave de reuso usa a identidade
SEMÂNTICA estável (rule_id + subjects + sample + período + versão do catálogo +
versão do snapshot), para que o resultado seja reconhecível e reaproveitável
entre pacotes.
"""

from __future__ import annotations

import hashlib
import json

from contexts.financial_calculation.domain.calculation_plan import (
    CalculationPlan,
    SampleCondition,
    Subject,
)


def _subject_descriptor(subject: Subject) -> str:

    return f"{subject.type}.{subject.level}"


def _sample_descriptor(condition: SampleCondition) -> str:

    return f"{condition.type}.{condition.level}:{condition.value_id}"


def compute_reuse_key(
    plan: CalculationPlan,
    catalog_version: str,
    snapshot_version: str,
) -> str:
    """Hash determinístico do que o cálculo É, não de como foi rotulado."""

    payload = json.dumps(
        {
            "rule_id": str(plan.metric.rule_id),
            "subjects": sorted(
                _subject_descriptor(subject) for subject in plan.metric.subjects
            ),
            "sample": sorted(
                _sample_descriptor(condition) for condition in plan.metric.sample
            ),
            "period": {
                "start": plan.period.start.isoformat(),
                "end": plan.period.end.isoformat(),
                "type": str(plan.period.type),
                "grain": str(plan.period.grain),
            },
            "catalog_version": catalog_version,
            "snapshot_version": snapshot_version,
        },
        sort_keys=True,
    )

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

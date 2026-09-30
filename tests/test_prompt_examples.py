"""Os exemplos do prompt precisam atravessar a validação do motor.

O contrato do prompt é vivo: se um exemplo passar a violar o catálogo do
`CalculationPlan`, o teste quebra antes de o LLM produzir o mesmo plano em
produção. É a ponte entre o texto governado e o motor determinístico.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from contexts.financial_analysis.application.commands.answer_question import (
    InterpretationProposal,
)
from contexts.financial_analysis.domain.interpretation import InterpretationRoute
from contexts.financial_calculation.application.commands.execute_calculation import (
    execute_calculation,
)
from contexts.financial_calculation.ports.outbound.official_data_repository import (
    AggregatedRow,
    MetricRequest,
    PeriodRequest,
)

_EXAMPLES = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "prompts"
    / "interpretation"
    / "v1"
    / "examples.pt-BR.md"
)
_JSON_BLOCK = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


class _FakeRepository:
    def fetch_aggregated(
        self,
        metric: MetricRequest,
        period: PeriodRequest,
    ) -> list[AggregatedRow]:

        return []


def _example_payloads() -> list[dict[str, Any]]:

    text = _EXAMPLES.read_text(encoding="utf-8")

    return [json.loads(block) for block in _JSON_BLOCK.findall(text)]


def test_extrai_os_exemplos_do_prompt() -> None:

    assert len(_example_payloads()) >= 10


def test_todo_exemplo_do_prompt_parseia_no_proposal() -> None:

    for payload in _example_payloads():
        InterpretationProposal.model_validate(payload)


def test_todo_plano_analitico_dos_exemplos_passa_no_motor() -> None:

    proposals = [
        InterpretationProposal.model_validate(payload)
        for payload in _example_payloads()
    ]
    plans = [
        plan
        for proposal in proposals
        if proposal.route is InterpretationRoute.ANALYTICAL
        for plan in proposal.calculations
    ]

    assert len(plans) >= 6

    for plan in plans:
        execute_calculation(plan, _FakeRepository())

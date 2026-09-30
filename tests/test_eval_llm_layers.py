"""Camadas generativas do harness com um planner dublê (sem LLM).

`planner` só julga casos cujo gold é analítico (os demais são da camada
`routing`); a falha de UM caso vira `fail` daquele caso; credencial recusada
vira `LiveUnavailableError`; `planner` e `routing` compartilham a proposta.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval import llm_layers
from eval.dataset import load_dataset
from eval.live import LiveUnavailableError

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "eval" / "dev.yaml"


class _AuthError(Exception):
    pass


class _FakePlanner:
    def __init__(self, error: Exception | None = None):
        self.calls = 0
        self._error = error

    def propose(self, question: str, case_id: str):
        self.calls += 1

        if self._error is not None:
            raise self._error

        return None


@pytest.fixture(autouse=True)
def _clear_cache():
    llm_layers._proposal_cache.clear()
    yield
    llm_layers._proposal_cache.clear()


def _case(expected_route: str):
    dataset = load_dataset(DEV)

    return next(c for c in dataset.cases if c.expected_route == expected_route)


def test_planner_pula_caso_nao_analitico_sem_chamar_o_llm() -> None:
    planner = _FakePlanner()
    case = _case("refuse")

    outcome = llm_layers._run_case("planner", case, planner)

    assert outcome.status == "skip"
    assert planner.calls == 0


def test_erro_de_um_caso_vira_fail_daquele_caso() -> None:
    planner = _FakePlanner(error=RuntimeError("timeout"))
    case = _case("analytical")

    outcome = llm_layers._run_case("planner", case, planner)

    assert outcome.status == "fail"
    assert "RuntimeError" in outcome.detail


def test_credencial_recusada_interrompe_com_erro_claro() -> None:
    planner = _FakePlanner(error=_AuthError("Error code: 401"))
    case = _case("analytical")

    with pytest.raises(LiveUnavailableError, match="api_key"):
        llm_layers._run_case("routing", case, planner)


def test_planner_e_routing_compartilham_a_proposta() -> None:
    planner = _FakePlanner()
    case = _case("analytical")

    llm_layers._run_case("planner", case, planner)
    llm_layers._run_case("routing", case, planner)

    assert planner.calls == 1

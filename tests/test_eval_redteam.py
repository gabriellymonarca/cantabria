"""Camada `redteam`: guardrails e recusas contra o catálogo real, sem LLM.

Os ataques cobrem injeção de prompt, campos físicos, SQL, PII (redação), média
de taxas, métrica/eixo/valor fora do catálogo, janela, grão individual e
autorização restrita. Ataque barrado pelo motivo errado também falha.
"""

from __future__ import annotations

from pathlib import Path

from contexts.financial_analysis.adapters.outbound.yaml_semantic_catalog import (
    YamlSemanticCatalogAdapter,
)
from eval.redteam import load_attacks, run_redteam_layer

ROOT = Path(__file__).resolve().parents[1]
REDTEAM = ROOT / "data" / "eval" / "redteam.yaml"


def _layer():

    catalog = YamlSemanticCatalogAdapter().load_active()

    return run_redteam_layer(catalog, catalog.catalog_version, REDTEAM)


def test_redteam_cobre_os_ataques_sem_llm() -> None:

    layer = _layer()

    assert layer.failed == ()
    assert layer.total_cases >= 8
    assert layer.counts["pass"] == layer.total_cases


def test_guardrails_de_entrada_tem_cada_categoria() -> None:

    attacks = {attack.id: attack for attack in load_attacks(REDTEAM)}

    assert attacks["RT-01"].expect_reason == "physical_field"
    assert attacks["RT-02"].expect_reason == "sql_fragment"
    assert attacks["RT-03"].expect_reason == "prompt_injection"
    assert attacks["RT-04"].expect_action == "redact"
    assert attacks["RT-05"].expect_action == "redact"
    assert attacks["RT-06"].expect_action == "allow"


def test_recusas_cobrem_a_taxonomia_contra_o_catalogo() -> None:

    attacks = {attack.id: attack for attack in load_attacks(REDTEAM)}
    reasons = {attack.expect_reason for attack in attacks.values()}

    assert {
        "catalog_miss",
        "not_expressible",
        "out_of_window",
        "invalid_window",
        "unauthorized",
    } <= reasons


def test_ataque_barrado_pelo_motivo_errado_falha() -> None:
    """O julgamento sai do motivo observado, nunca de um resultado fixo."""

    from dataclasses import replace

    from contexts.auth.domain.capabilities import UserCapabilities
    from eval.redteam import judge_attack

    attack = {attack.id: attack for attack in load_attacks(REDTEAM)}["RT-14"]
    catalog = YamlSemanticCatalogAdapter().load_active()
    capabilities = UserCapabilities(
        can_use_financial_analysis=True,
        metrics=frozenset(entry.rule_id for entry in catalog.metrics),
        axes=frozenset(entry.key for entry in catalog.axes),
    )

    # Com o motivo correto (catalog_miss) o ataque é barrado e passa...
    assert judge_attack(attack, catalog, capabilities).status == "pass"

    # ...com uma expectativa de motivo diferente, o veredito é `fail`.
    wrong = replace(attack, expect_reason="governance")

    assert judge_attack(wrong, catalog, capabilities).status == "fail"

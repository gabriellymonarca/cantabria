"""Rodapé de procedência: métrica com fórmula curta, data
de fechamento dos dados e protocolo do turno numa linha legível, construídos só
a partir do `AnalysisResult`. Hash e versão do catálogo ficam fora do texto."""

from __future__ import annotations

from contexts.financial_analysis.domain.analysis_result import (
    AnalysisResult,
    MethodResult,
)
from contexts.financial_analysis.domain.services.provenance import (
    is_provenance_footer,
    provenance_footer,
)
from shared.protocol import protocol_of

DIGEST = "3f2a9c1e" + "0" * 56


def _result(**overrides) -> AnalysisResult:

    fields = {
        "analysis_plan_id": "plan",
        "catalog_version": "v2",
        "dataset_version": f"2026-08-31#sha256:{DIGEST}",
        "trace_id": "fc4dea24af97b1c2",
        "rule_id": "profitability",
    }
    fields.update(overrides)

    return AnalysisResult(**fields)


def test_protocolo_e_can_mais_oito_caracteres_maiusculos() -> None:

    assert protocol_of("fc4dea24af97b1c2") == "CAN-FC4DEA24"
    assert protocol_of("") == ""


def test_rodape_tem_metrica_formula_data_e_protocolo() -> None:

    footer = provenance_footer(_result())

    assert footer == (
        "_Fonte: rentabilidade (Σ margem ÷ Σ saldo), dados oficiais fechados em "
        "31/08/2026 · protocolo CAN-FC4DEA24_"
    )
    assert is_provenance_footer(footer)
    assert DIGEST[:8] not in footer
    assert "v2" not in footer


def test_rodape_lista_as_regras_dos_metodos_quando_o_pacote_mistura() -> None:

    result = _result(
        rule_id=None,
        statistical_method=[
            MethodResult(id="s1", method="null", rule_id="profitability"),
            MethodResult(id="s2", method="null", rule_id="outstanding_balance"),
            MethodResult(id="s3", method="null", rule_id="profitability"),
        ],
    )

    footer = provenance_footer(result)

    assert (
        "rentabilidade (Σ margem ÷ Σ saldo) e carteira (saldo em fim de período)"
        in footer
    )


def test_rodape_sem_regra_data_ou_trace_usa_textos_neutros() -> None:

    footer = provenance_footer(
        _result(rule_id=None, dataset_version="snapshot-sem-data", trace_id="")
    )

    assert footer == "_Fonte: dados verificados, dados oficiais verificados_"

"""Rodapé de procedência de uma resposta analítica.

Todo número entregue ao usuário nasceu de uma regra do catálogo, sobre uma
versão do dado, num turno rastreável. O rodapé torna isso visível numa linha
legível: a métrica com a sua fórmula curta, a data de fechamento dos dados
oficiais e o protocolo do turno. Hash do dataset, versão do catálogo e
`trace_id` completo ficam no `AnalysisResult`, no log e no trace.
"""

from __future__ import annotations

import re
from datetime import date

from contexts.financial_analysis.domain.analysis_result import AnalysisResult
from shared.protocol import protocol_of

_UNKNOWN_RULE = "dados verificados"
_UNKNOWN_DATE = "dados oficiais verificados"
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

_METRIC_LABELS: dict[str, str] = {
    "profitability": "rentabilidade (Σ margem ÷ Σ saldo)",
    "outstanding_balance": "carteira (saldo em fim de período)",
    "contract_count": "contratos ativos (contagem em fim de período)",
    "customer_count": "clientes (contagem distinta em fim de período)",
    "cdi_rate": "CDI (taxa composta no período)",
    "selic_rate": "SELIC (taxa composta no período)",
    "inflation_ipca": "IPCA (inflação composta no período)",
}


def _rule_ids(result: AnalysisResult) -> tuple[str, ...]:
    """O `rule_id` do pacote ou, quando ele mistura regras, cada uma delas."""

    if result.rule_id:
        return (result.rule_id,)

    seen: dict[str, None] = {}

    for method in result.statistical_method:
        if method.rule_id:
            seen.setdefault(method.rule_id, None)

    return tuple(seen)


def _metrics(result: AnalysisResult) -> str:
    """Rótulo pt-BR com fórmula curta por regra; sem regra, texto neutro."""

    rules = _rule_ids(result)

    if not rules:
        return _UNKNOWN_RULE

    return " e ".join(
        _METRIC_LABELS.get(rule_id, rule_id.replace("_", " ")) for rule_id in rules
    )


def dataset_closing_date(dataset_version: str) -> date | None:
    """A data ISO embutida em `2026-08-31#sha256:...`; `None` se não houver."""

    match = _ISO_DATE.search(dataset_version)

    if match is None:
        return None

    try:
        return date.fromisoformat(match.group(0))
    except ValueError:
        return None


def _closing_date(dataset_version: str) -> str:
    """`2026-08-31#sha256:...` → `dados oficiais fechados em 31/08/2026`."""

    closed = dataset_closing_date(dataset_version)

    if closed is None:
        return _UNKNOWN_DATE

    return f"dados oficiais fechados em {closed:%d/%m/%Y}"


PROVENANCE_PREFIX = "_Fonte:"


def provenance_footer(result: AnalysisResult) -> str:
    """Uma linha em itálico com métrica, fechamento dos dados e protocolo."""

    protocol = protocol_of(result.trace_id)
    suffix = f" · protocolo {protocol}" if protocol else ""

    return (
        f"{PROVENANCE_PREFIX} {_metrics(result)}, "
        f"{_closing_date(result.dataset_version)}{suffix}_"
    )


def is_provenance_footer(text: str) -> bool:
    """O rodapé é metadado do turno, não conversa: quem monta o contexto do
    planner usa isto para deixá-lo de fora."""

    return text.startswith(PROVENANCE_PREFIX)

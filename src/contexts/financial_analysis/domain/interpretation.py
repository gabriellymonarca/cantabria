"""Roteamento e taxonomia de recusa da interpretação da pergunta.

A rota é saída explícita da etapa de interpretação. `analytical` gera
CalculationPlan + AnalysisPlan; `documental` é RAG puro; `capability` devolve a
descrição de escopo gerada do catálogo; `clarify` devolve uma pergunta ao
usuário; `refuse` recusa com um motivo tipificado.

Cada motivo de recusa tem mensagem própria: "não existe" convida a reformular,
"proibido" encerra. Os identificadores são canônicos (inglês snake_case) porque
atravessam o domínio e o plano; a mensagem ao usuário é localizada.
"""

from __future__ import annotations

from enum import StrEnum


class InterpretationRoute(StrEnum):
    """O que a pergunta exige: plano, RAG, escopo, esclarecimento ou recusa."""

    ANALYTICAL = "analytical"
    DOCUMENTAL = "documental"
    CAPABILITY = "capability"
    CLARIFY = "clarify"
    REFUSE = "refuse"


class RefusalReason(StrEnum):
    """Por que a pergunta não pode ser respondida com um plano."""

    CATALOG_MISS = "catalog_miss"
    OUT_OF_SCOPE = "out_of_scope"
    NOT_EXPRESSIBLE = "not_expressible"
    GOVERNANCE = "governance"
    UNAUTHORIZED = "unauthorized"
    OUT_OF_WINDOW = "out_of_window"
    INVALID_WINDOW = "invalid_window"
    INPUT_POLICY = "input_policy"

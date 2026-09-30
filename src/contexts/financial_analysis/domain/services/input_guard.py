"""Guardrail determinístico de entrada: roda ANTES de qualquer chamada ao LLM.

O modelo propõe; o código autoriza. Este serviço de domínio decide, sem modelo,
o que uma pergunta pode fazer: pedidos que referenciam campos físicos da base,
fragmentos de SQL/DDL ou marcadores de injeção de prompt são recusados com um
código tipificado; identificadores pessoais (CPF, CNPJ, e-mail, telefone) são
redigidos antes de o texto seguir. Só o que sobra chega ao planner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from shared.redaction import redact_personal_identifiers

PHYSICAL_FIELD = "physical_field"
SQL_FRAGMENT = "sql_fragment"
PROMPT_INJECTION = "prompt_injection"
TOO_LONG = "too_long"

# Teto da pergunta corrente: acima disso não é pergunta de negócio, é payload.
# A recusa acontece antes de qualquer regex e de qualquer modelo.
MAX_REQUEST_CHARS = 2000

_PHYSICAL_FIELD = re.compile(
    r"\b(?:ds|vl|id|tp|cd|dt|nr)_[a-z][a-z0-9_]*\s*"
    r"(?:=|:|<>|!=|<|>|in\b|not\s+in\b|like\b|between\b)",
    re.IGNORECASE,
)

# DML/DDL: `update`/`delete`/`alter` são palavras comuns em português de
# negócio ("último update da carteira"); exigem a forma da instrução SQL.
_SQL_FRAGMENTS = (
    re.compile(r"\bselect\b.*\bfrom\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bdrop\b", re.IGNORECASE),
    re.compile(r"\binsert\b", re.IGNORECASE),
    re.compile(r"\bunion\b", re.IGNORECASE),
    re.compile(r"\bdelete\s+from\b", re.IGNORECASE),
    re.compile(r"\bupdate\b.*\bset\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\btruncate\b", re.IGNORECASE),
    re.compile(r"\balter\s+(?:table|view|database)\b", re.IGNORECASE),
    re.compile(r";--"),
)

_INJECTION_MARKERS = (
    "system prompt",
    "revele o prompt",
    "mostre o catálogo completo",
    "escreva sql",
    "aja como",
    "act as",
    "developer mode",
    "jailbreak",
)

# Verbo de descarte ("ignore/desconsidere/esqueça/forget/disregard") seguido,
# com até quatro palavras de permeio, de "regras/instruções/instructions":
# cobre "ignore todas as regras anteriores" e "ignore all previous
# instructions" sem enumerar cada variante.
_DISCARD_VERBS = (
    "ignore",
    "ignora",
    "ignorar",
    "desconsidere",
    "desconsidera",
    "desconsiderar",
    "esqueça",
    "esqueca",
    "esquece",
    "esquecer",
    "forget",
    "disregard",
)
_RULE_NOUNS = (
    "regras",
    "rules",
    "instruções",
    "instrucoes",
    "instructions",
)

_PROMPT_INJECTION = re.compile(
    r"\b(?:" + "|".join(re.escape(marker) for marker in _INJECTION_MARKERS) + r")\b"
    r"|\b(?:" + "|".join(_DISCARD_VERBS) + r")\b(?:\W+\w+){0,4}?\W+"
    r"(?:" + "|".join(_RULE_NOUNS) + r")\b",
    re.IGNORECASE,
)


class GuardAction(StrEnum):
    """O que fazer com a pergunta antes do planner."""

    ALLOW = "allow"
    REDACT = "redact"
    REFUSE = "refuse"


@dataclass(frozen=True)
class GuardVerdict:
    """Decisão do guardrail: ação, motivo (só em recusa), texto e tipos redigidos."""

    action: GuardAction
    reason: str | None
    text: str
    kinds: frozenset[str]


def refusal_reason(text: str) -> str | None:
    """Código da recusa, ou None quando o texto não viola a política de entrada."""

    if len(text) > MAX_REQUEST_CHARS:
        return TOO_LONG

    if _PHYSICAL_FIELD.search(text):
        return PHYSICAL_FIELD

    if any(pattern.search(text) for pattern in _SQL_FRAGMENTS):
        return SQL_FRAGMENT

    if _PROMPT_INJECTION.search(text):
        return PROMPT_INJECTION

    return None


def guard_input(text: str) -> GuardVerdict:
    """Recusa, redige ou libera a pergunta; nunca chama modelo algum."""

    reason = refusal_reason(text)

    if reason is not None:
        return GuardVerdict(
            action=GuardAction.REFUSE,
            reason=reason,
            text=text,
            kinds=frozenset(),
        )

    redaction = redact_personal_identifiers(text)

    if redaction.kinds:
        return GuardVerdict(
            action=GuardAction.REDACT,
            reason=None,
            text=redaction.text,
            kinds=redaction.kinds,
        )

    return GuardVerdict(
        action=GuardAction.ALLOW,
        reason=None,
        text=text,
        kinds=frozenset(),
    )

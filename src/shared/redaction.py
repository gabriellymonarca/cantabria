"""Redação de identificadores pessoais em texto livre.

Antes de qualquer texto do usuário chegar a um trace, ao histórico da conversa
ou ao modelo, os identificadores pessoais são substituídos por marcadores
fixos. O módulo é puro e agnóstico de domínio: reconhece CPF e CNPJ (com
validação dos dígitos verificadores), e-mail e telefone no formato brasileiro.

Percentuais, valores monetários, datas, anos e números curtos não são tocados:
os padrões exigem a quantidade exata de dígitos e, no caso de CPF/CNPJ, os
dígitos verificadores corretos.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

CPF_PLACEHOLDER = "[CPF removido]"
CNPJ_PLACEHOLDER = "[CNPJ removido]"
EMAIL_PLACEHOLDER = "[e-mail removido]"
PHONE_PLACEHOLDER = "[telefone removido]"

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# CPF/CNPJ aceitam ponto OU espaço entre grupos e hífen OU espaço antes dos
# dígitos verificadores: trocar o ponto por espaço é a forma mais barata de
# contornar o filtro. A validação dos dígitos verificadores continua a proteger
# contra falso positivo (data, hora, valor).
_CNPJ = re.compile(r"(?<!\d)\d{2}[.\s]?\d{3}[.\s]?\d{3}[/\s]?\d{4}[-\s]?\d{2}(?!\d)")
_CPF = re.compile(r"(?<!\d)\d{3}[.\s]?\d{3}[.\s]?\d{3}[-\s]?\d{2}(?!\d)")

# Telefone BR: DDD com ou sem parênteses e número de 8 ou 9 dígitos. Exige ao
# menos um separador (parênteses, espaço ou hífen): uma sequência nua de 10 ou
# 11 dígitos é ambígua demais para ser tratada como telefone. O DDD não tem
# zero ("10" não é DDD), o que já afasta "top 10 2025-2026".
_PHONE = re.compile(
    r"(?<!\d)(?:"
    r"\([1-9][1-9]\)\s?\d{4,5}-?\d{4}"
    r"|[1-9][1-9]\s\d{4,5}-?\d{4}"
    r"|[1-9][1-9]\s?\d{4,5}-\d{4}"
    r")(?!\d)"
)

# "11 2025-2026" tem a forma de telefone, mas dois blocos de ano seguidos são
# um intervalo de anos, não um número.
_YEAR_RANGE = re.compile(r"(?:19|20)\d{2}\s*-\s*(?:19|20)\d{2}\Z")

_CNPJ_WEIGHTS_FIRST = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_CNPJ_WEIGHTS_SECOND = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


@dataclass(frozen=True)
class Redaction:
    """O texto redigido e os tipos de identificador encontrados."""

    text: str
    kinds: frozenset[str]


def _digits(text: str) -> str:

    return "".join(character for character in text if character.isdigit())


def is_valid_cpf(candidate: str) -> bool:
    """Valida os dois dígitos verificadores de um CPF (com ou sem máscara)."""

    digits = _digits(candidate)

    if len(digits) != 11 or len(set(digits)) == 1:
        return False

    for size in (9, 10):
        weights = range(size + 1, 1, -1)
        total = sum(
            int(digit) * weight
            for digit, weight in zip(digits[:size], weights, strict=True)
        )
        check = (total * 10) % 11
        check = 0 if check == 10 else check

        if check != int(digits[size]):
            return False

    return True


def is_valid_cnpj(candidate: str) -> bool:
    """Valida os dois dígitos verificadores de um CNPJ (com ou sem máscara)."""

    digits = _digits(candidate)

    if len(digits) != 14 or len(set(digits)) == 1:
        return False

    for weights, size in ((_CNPJ_WEIGHTS_FIRST, 12), (_CNPJ_WEIGHTS_SECOND, 13)):
        total = sum(
            int(digit) * weight
            for digit, weight in zip(digits[:size], weights, strict=True)
        )
        remainder = total % 11
        check = 0 if remainder < 2 else 11 - remainder

        if check != int(digits[size]):
            return False

    return True


def _always(_: str) -> bool:

    return True


def _is_phone(candidate: str) -> bool:

    return _YEAR_RANGE.search(candidate) is None


@dataclass(frozen=True)
class _Rule:
    kind: str
    pattern: re.Pattern[str]
    placeholder: str
    accepts: Callable[[str], bool]


# Ordem importa: e-mail primeiro (pode conter dígitos que os outros padrões
# comeriam), depois o documento mais longo (CNPJ), o CPF e por fim o telefone.
_RULES: tuple[_Rule, ...] = (
    _Rule("email", _EMAIL, EMAIL_PLACEHOLDER, _always),
    _Rule("cnpj", _CNPJ, CNPJ_PLACEHOLDER, is_valid_cnpj),
    _Rule("cpf", _CPF, CPF_PLACEHOLDER, is_valid_cpf),
    _Rule("phone", _PHONE, PHONE_PLACEHOLDER, _is_phone),
)


def _apply(rule: _Rule, text: str, kinds: set[str]) -> str:

    def _replace(match: re.Match[str]) -> str:

        candidate = match.group(0)

        if not rule.accepts(candidate):
            return candidate

        kinds.add(rule.kind)

        return rule.placeholder

    return rule.pattern.sub(_replace, text)


def redact_personal_identifiers(text: str) -> Redaction:
    """Substitui CPF, CNPJ, e-mail e telefone por marcadores fixos."""

    kinds: set[str] = set()
    redacted = text

    for rule in _RULES:
        redacted = _apply(rule, redacted, kinds)

    return Redaction(text=redacted, kinds=frozenset(kinds))

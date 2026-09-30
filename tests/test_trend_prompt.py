"""Contrato da recusa de previsão: oferecer a tendência governada.

Previsão continua fora de escopo (governança). O texto de recusa precisa
oferecer o substituto que existe no catálogo — `trend`, a inclinação de uma
regressão linear sobre a série observada — sem prometer o futuro nem citar
números. O teste lê o arquivo do disco, como os demais contratos de prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

_MESSAGES = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "prompts"
    / "interpretation"
    / "v1"
    / "messages.pt-BR.md"
)


def _section(text: str, title: str) -> str:

    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)

    assert match is not None, f"seção '{title}' ausente"

    return match.group(1).strip()


def _out_of_scope_bullet(text: str) -> str:
    """O bullet de `out_of_scope`, com a instrução de previsão aninhada."""

    refuse = _section(text, "Recusar (`refuse`)")
    match = re.search(r"^- `out_of_scope`.*?(?=^- `|\Z)", refuse, re.S | re.M)

    assert match is not None, "bullet de `out_of_scope` ausente"

    return match.group(0)


def test_recusa_de_previsao_oferece_trend_sobre_a_serie() -> None:

    bullet = _out_of_scope_bullet(_MESSAGES.read_text(encoding="utf-8"))

    assert "`trend`" in bullet
    assert "regressão" in bullet
    assert "tendência" in bullet
    assert "série observada" in bullet


def test_recusa_de_previsao_usa_o_vocabulario_e_pergunta() -> None:

    bullet = _out_of_scope_bullet(_MESSAGES.read_text(encoding="utf-8"))

    assert "vocabulário do usuário" in bullet
    assert "Quer?" in bullet


def test_recusa_de_previsao_nao_promete_o_futuro_nem_numero() -> None:

    bullet = _out_of_scope_bullet(_MESSAGES.read_text(encoding="utf-8")).lower()

    assert "não projeta o futuro" in bullet
    assert "sem citar nenhum número" in bullet
    for promessa in (
        "vou prever",
        "vou projetar",
        "irei projetar",
        "previsão para",
    ):
        assert promessa not in bullet


def test_instrucao_de_previsao_fica_no_bloco_certo() -> None:

    text = _MESSAGES.read_text(encoding="utf-8")

    assert "previsão/projeção/futuro" in _out_of_scope_bullet(text).lower()
    assert (
        "previsão/projeção/futuro"
        not in _section(text, "Esclarecer (`clarify`)").lower()
    )

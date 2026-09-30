"""Redação de identificadores pessoais: CPF, CNPJ, e-mail e
telefone saem do texto antes de trace, histórico e modelo; números de negócio
(percentual, moeda, data, ano) ficam intactos.

CPF e CNPJ só são redigidos quando os dígitos verificadores batem.
"""

from __future__ import annotations

import pytest

from shared.redaction import (
    CNPJ_PLACEHOLDER,
    CPF_PLACEHOLDER,
    EMAIL_PLACEHOLDER,
    PHONE_PLACEHOLDER,
    is_valid_cnpj,
    is_valid_cpf,
    redact_personal_identifiers,
)


def _cpf_from_base(base: str) -> str:
    """Gera um CPF válido a partir dos 9 primeiros dígitos (algoritmo oficial)."""

    digits = [int(character) for character in base]

    for size in (9, 10):
        weights = range(size + 1, 1, -1)
        total = sum(
            digit * weight for digit, weight in zip(digits, weights, strict=True)
        )
        check = (total * 10) % 11
        digits.append(0 if check == 10 else check)

    return "".join(str(digit) for digit in digits)


VALID_CPF = _cpf_from_base("529982247")
VALID_CPF_MASKED = f"{VALID_CPF[:3]}.{VALID_CPF[3:6]}.{VALID_CPF[6:9]}-{VALID_CPF[9:]}"
VALID_CNPJ = "11.222.333/0001-81"


def test_cpf_gerado_pelo_algoritmo_e_o_exemplo_conhecido() -> None:

    assert VALID_CPF == "52998224725"
    assert is_valid_cpf(VALID_CPF)
    assert is_valid_cpf(VALID_CPF_MASKED)


def test_cpf_com_digito_verificador_errado_e_invalido() -> None:

    assert not is_valid_cpf("52998224726")
    assert not is_valid_cpf("11111111111")
    assert not is_valid_cpf("1234567890")


def test_cnpj_conhecido_e_valido_e_variante_errada_nao() -> None:

    assert is_valid_cnpj(VALID_CNPJ)
    assert is_valid_cnpj("11222333000181")
    assert not is_valid_cnpj("11.222.333/0001-82")
    assert not is_valid_cnpj("00000000000000")


def test_cpf_valido_e_removido_com_o_tipo_registrado() -> None:

    redaction = redact_personal_identifiers(
        f"Qual a rentabilidade do cliente {VALID_CPF_MASKED} em agosto?"
    )

    assert redaction.text == (
        f"Qual a rentabilidade do cliente {CPF_PLACEHOLDER} em agosto?"
    )
    assert redaction.kinds == frozenset({"cpf"})


def test_cpf_sem_mascara_tambem_e_removido() -> None:

    redaction = redact_personal_identifiers(f"cliente {VALID_CPF} saldo")

    assert CPF_PLACEHOLDER in redaction.text
    assert VALID_CPF not in redaction.text


@pytest.mark.parametrize(
    "spaced",
    [
        "529 982 247 25",
        "529.982.247 25",
        "529 982 247-25",
    ],
)
def test_cpf_separado_por_espacos_tambem_e_removido(spaced: str) -> None:
    """Quem quer contornar o filtro troca o ponto por espaço; o dígito
    verificador continua a proteger contra falso positivo."""

    redaction = redact_personal_identifiers(f"cliente {spaced} saldo")

    assert redaction.text == f"cliente {CPF_PLACEHOLDER} saldo"
    assert redaction.kinds == frozenset({"cpf"})


def test_cnpj_separado_por_espacos_tambem_e_removido() -> None:

    redaction = redact_personal_identifiers("empresa 11 222 333 0001 81 hoje")

    assert redaction.text == f"empresa {CNPJ_PLACEHOLDER} hoje"
    assert redaction.kinds == frozenset({"cnpj"})


def test_data_e_hora_com_espacos_nao_e_cpf() -> None:

    text = "fechamento em 31 08 2026 15 horas"

    redaction = redact_personal_identifiers(text)

    assert redaction.text == text
    assert redaction.kinds == frozenset()


def test_numero_de_11_digitos_com_digito_invalido_permanece() -> None:

    text = "O contrato 52998224726 venceu."

    redaction = redact_personal_identifiers(text)

    assert redaction.text == text
    assert redaction.kinds == frozenset()


def test_cnpj_valido_e_removido() -> None:

    redaction = redact_personal_identifiers(f"saldo da empresa {VALID_CNPJ}")

    assert redaction.text == f"saldo da empresa {CNPJ_PLACEHOLDER}"
    assert redaction.kinds == frozenset({"cnpj"})


def test_email_e_removido() -> None:

    redaction = redact_personal_identifiers("fale com joao.silva@exemplo.com.br hoje")

    assert redaction.text == f"fale com {EMAIL_PLACEHOLDER} hoje"
    assert redaction.kinds == frozenset({"email"})


@pytest.mark.parametrize(
    "phone",
    [
        "(11) 98765-4321",
        "(11)98765-4321",
        "11 98765-4321",
        "11 3456-7890",
        "11 987654321",
    ],
)
def test_telefone_br_e_removido(phone: str) -> None:

    redaction = redact_personal_identifiers(f"ligue para {phone} amanhã")

    assert redaction.text == f"ligue para {PHONE_PLACEHOLDER} amanhã"
    assert redaction.kinds == frozenset({"phone"})


@pytest.mark.parametrize(
    "text",
    [
        "rentabilidade acima de 15%",
        "saldo em 31/08/2026",
        "saldo em 2026-08-31",
        "R$ 1.234.567,89 de margem",
        "R$ 12.345.678.901,00 de saldo",
        "top 5 produtos de 2025",
        "variação de 12,5% entre 2025 e 2026",
        "de 2025-09-01 a 2026-08-31, grão mensal",
        "top 10 2025-2026",
        "top 11 2025-2026 por segmento",
    ],
)
def test_numeros_de_negocio_nao_sao_tocados(text: str) -> None:

    redaction = redact_personal_identifiers(text)

    assert redaction.text == text
    assert redaction.kinds == frozenset()


def test_varios_tipos_no_mesmo_texto() -> None:

    redaction = redact_personal_identifiers(
        f"cliente {VALID_CPF_MASKED}, empresa {VALID_CNPJ}, contato a@b.com"
    )

    assert redaction.kinds == frozenset({"cpf", "cnpj", "email"})
    assert VALID_CPF_MASKED not in redaction.text
    assert VALID_CNPJ not in redaction.text
    assert "a@b.com" not in redaction.text


def test_redacao_e_idempotente() -> None:

    once = redact_personal_identifiers(f"cliente {VALID_CPF_MASKED}")
    twice = redact_personal_identifiers(once.text)

    assert twice.text == once.text
    assert twice.kinds == frozenset()

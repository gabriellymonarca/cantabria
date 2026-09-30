"""Versão do dataset por hash de conteúdo.

O retrato canônico por tabela vira um sha256 estável: o mesmo conteúdo gera o
mesmo digest em Python e no ClickHouse, e qualquer mudança (uma linha, um
centavo, um mês) muda o digest. A versão do snapshot carrega data + hash.
"""

from __future__ import annotations

from shared.dataset_version import (
    fingerprint_tables,
    format_snapshot_version,
    normalize_count,
    normalize_money,
)


def _retrato() -> dict[str, dict[str, str]]:

    return {
        "fato_cliente": {"count": "3"},
        "fato_rentabilidade_cliente": {
            "count": "8",
            "max_mes_ref": "2026-08-31",
            "sum_vl_margem": "390.00",
            "sum_vl_saldo": "2900.00",
        },
    }


def test_mesmo_conteudo_mesmo_digest() -> None:

    assert fingerprint_tables(_retrato()) == fingerprint_tables(_retrato())


def test_ordem_das_chaves_nao_muda_o_digest() -> None:

    embaralhado = {
        "fato_rentabilidade_cliente": {
            "sum_vl_saldo": "2900.00",
            "count": "8",
            "sum_vl_margem": "390.00",
            "max_mes_ref": "2026-08-31",
        },
        "fato_cliente": {"count": "3"},
    }

    assert fingerprint_tables(embaralhado) == fingerprint_tables(_retrato())


def test_qualquer_mudanca_muda_o_digest() -> None:

    base = fingerprint_tables(_retrato())

    um_centavo = {"count": "8", "sum_vl_saldo": "2900.01"}
    outra = {**_retrato(), "fato_rentabilidade_cliente": um_centavo}

    assert fingerprint_tables(outra) != base


def test_digest_tem_64_hex() -> None:

    digest = fingerprint_tables(_retrato())

    assert len(digest) == 64
    assert all(char in "0123456789abcdef" for char in digest)


def test_normalizacao_canonica() -> None:

    assert normalize_money("390") == "390.00"
    assert normalize_money(0) == "0.00"
    assert normalize_count("3") == "3"


def test_versao_formada_por_data_e_hash() -> None:

    digest = fingerprint_tables(_retrato())
    versao = format_snapshot_version("2026-08-31", digest)

    assert versao == f"2026-08-31#sha256:{digest}"
    assert format_snapshot_version(None, digest) == f"unknown#sha256:{digest}"

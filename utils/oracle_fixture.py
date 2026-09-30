#!/usr/bin/env python3
"""Fixture do oracle: o dataset mínimo e a agregação de referência.

Este módulo é DELIBERADAMENTE independente do motor (`src/`): ele não importa
nada do sistema sob teste. As linhas de fato são as mesmas do teste de
paridade, e a agregação é refeita aqui em Python puro sobre Decimal, com a
semântica governada (razão re-derivada no grão, estoque lido no fim do
período, ausência como None, contrato ativo por datas, faixa por score).

O `utils/build_oracle.py` usa este módulo para congelar o artefato
`data/oracle/oracle_v1.yaml`; o `utils/validate_oracle.py` usa para semear o
ClickHouse e comparar. O fingerprint canônico (`fixture_fingerprint`) usa só
`hashlib`/`json` da stdlib, nos mesmos campos que o adapter ClickHouse lê.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal

CLI_1 = "11111111-1111-4111-8111-111111111111"
CLI_2 = "22222222-2222-4222-8222-222222222222"
CLI_3 = "33333333-3333-4333-8333-333333333333"

CLIENTES = [
    (CLI_1, "Varejo PF", Decimal("30.00"), Decimal("30.00")),
    (CLI_2, "Varejo PF", Decimal("80.00"), Decimal("80.00")),
    (CLI_3, "Private", Decimal("80.00"), Decimal("50.00")),
]

PRODUTOS = {
    "PROD_1": ("Crédito Rotativo", "Cartão"),
    "PROD_2": ("Crédito Consignado", "Consignado"),
}

CONTRATOS = [
    ("CTR_1", CLI_1, dt.date(2024, 1, 1), None),
    ("CTR_2", CLI_2, dt.date(2024, 1, 1), None),
    ("CTR_3", CLI_3, dt.date(2024, 1, 1), dt.date(2026, 7, 15)),
]

ITENS_POR_CONTRATO = {
    "CTR_1": ["PROD_1"],
    "CTR_2": ["PROD_1"],
    "CTR_3": ["PROD_2"],
}

RENT_CLIENTE = [
    (CLI_1, dt.date(2026, 6, 30), Decimal("100.00"), Decimal("10.00")),
    (CLI_1, dt.date(2026, 7, 31), Decimal("100.00"), Decimal("10.00")),
    (CLI_1, dt.date(2026, 8, 31), Decimal("100.00"), Decimal("10.00")),
    (CLI_2, dt.date(2026, 6, 30), Decimal("300.00"), Decimal("30.00")),
    (CLI_2, dt.date(2026, 7, 31), Decimal("200.00"), Decimal("40.00")),
    (CLI_2, dt.date(2026, 8, 31), Decimal("100.00"), Decimal("50.00")),
    (CLI_3, dt.date(2026, 6, 30), Decimal("1000.00"), Decimal("100.00")),
    (CLI_3, dt.date(2026, 7, 31), Decimal("1000.00"), Decimal("100.00")),
]

RENT_ITEM = [
    ("CTR_1", "PROD_1", dt.date(2026, 6, 30), Decimal("100.00"), Decimal("10.00")),
    ("CTR_1", "PROD_1", dt.date(2026, 7, 31), Decimal("100.00"), Decimal("10.00")),
    ("CTR_1", "PROD_1", dt.date(2026, 8, 31), Decimal("100.00"), Decimal("10.00")),
    ("CTR_2", "PROD_1", dt.date(2026, 6, 30), Decimal("300.00"), Decimal("30.00")),
    ("CTR_2", "PROD_1", dt.date(2026, 7, 31), Decimal("200.00"), Decimal("40.00")),
    ("CTR_2", "PROD_1", dt.date(2026, 8, 31), Decimal("100.00"), Decimal("50.00")),
    ("CTR_3", "PROD_2", dt.date(2026, 6, 30), Decimal("1000.00"), Decimal("100.00")),
    ("CTR_3", "PROD_2", dt.date(2026, 7, 31), Decimal("1000.00"), Decimal("100.00")),
]

SEGMENT_VALUE_IDS = {
    "varejo_pf": "Varejo PF",
    "varejo_pj": "Varejo PJ",
    "varejo_rural": "Varejo Rural",
    "private": "Private",
    "corporate_middle": "Corporate Middle",
    "corporate_large": "Corporate Large",
    "cib": "CIB",
}

GROUP_VALUE_IDS = {
    "rotativo": "Crédito Rotativo",
    "parcelado": "Crédito Parcelado",
    "consignado": "Crédito Consignado",
    "com_garantia": "Crédito com Garantia",
    "especializado": "Crédito Especializado",
    "transacional": "Crédito Transacional",
    "renegociacao": "Renegociação de Dívidas",
}

REFERENCE_DATE = dt.date(2026, 8, 31)

SEGMENTO_POR_CLIENTE = {cliente: segmento for cliente, segmento, _, _ in CLIENTES}

CLIENTE_POR_CONTRATO = {contrato: cliente for contrato, cliente, _, _ in CONTRATOS}


def _faixa(score: Decimal) -> str:

    if score >= Decimal("70"):
        return "high"

    if score >= Decimal("40"):
        return "medium"

    return "low"


def _cliente_por_id() -> dict:

    return {
        cliente: {"segmento": segmento, "principalidade": princ, "vinculacao": vinc}
        for cliente, segmento, princ, vinc in CLIENTES
    }


def _ultimo_dia(ano: int, mes: int) -> int:

    if mes == 12:
        return 31

    return (dt.date(ano, mes + 1, 1) - dt.timedelta(days=1)).day


def _bucket_end(mes: dt.date, grain: str) -> dt.date:

    if grain == "month":
        return dt.date(mes.year, mes.month, _ultimo_dia(mes.year, mes.month))

    if grain == "quarter":
        fim = ((mes.month - 1) // 3 + 1) * 3

        return dt.date(mes.year, fim, _ultimo_dia(mes.year, fim))

    if grain == "year":
        return dt.date(mes.year, 12, 31)

    raise ValueError(f"grain '{grain}' sem fim de bucket.")


def buckets_for(period: dict) -> list[str]:

    if period["grain"] == "total" or period["type"] == "snapshot":
        return [period["end"]]

    inicio = dt.date.fromisoformat(period["start"])
    fim = dt.date.fromisoformat(period["end"])
    atual = inicio.replace(day=1)
    buckets: list[str] = []

    while atual <= fim:
        bucket = _bucket_end(atual, period["grain"]).isoformat()

        if bucket not in buckets:
            buckets.append(bucket)

        proximo_mes = atual.month % 12 + 1
        proximo_ano = atual.year + (atual.month // 12)
        atual = dt.date(proximo_ano, proximo_mes, 1)

    return buckets


def _ativo(inicio: dt.date, fim: dt.date | None, data: dt.date) -> bool:

    if inicio > data:
        return False

    return fim is None or data <= fim


def _grupos_segmento() -> list[str]:

    return sorted({segmento for _, segmento, _, _ in CLIENTES})


def _grupos_produto() -> list[str]:

    return sorted({produto for _, produto in PRODUTOS.values()})


def _grade_grupos(subjects: list[dict], rule_id: str) -> list[dict]:

    if not subjects or subjects == [{"type": "total", "level": "total"}]:
        return [{}]

    tipos = {s["type"] for s in subjects}

    if "product" in tipos and "customer_segmentation" in tipos:
        return _pares_observados(subjects)

    grade: list[dict] = [{}]

    for subject in subjects:
        if (subject["type"], subject["level"]) == ("customer_segmentation", "segment"):
            valores = _grupos_segmento()
        elif (subject["type"], subject["level"]) == ("product", "product"):
            valores = _grupos_produto()
        else:
            raise ValueError(
                f"eixo '{subject['type']}.{subject['level']}' fora do oracle."
            )

        chave = f"{subject['type']}.{subject['level']}"
        grade = [{**grupo, chave: valor} for grupo in grade for valor in valores]

    return grade


def _pares_observados(subjects: list[dict]) -> list[dict]:

    pares = sorted(
        {
            (
                SEGMENTO_POR_CLIENTE[CLIENTE_POR_CONTRATO[contrato]],
                PRODUTOS[item][1],
            )
            for contrato, itens in ITENS_POR_CONTRATO.items()
            for item in itens
        }
    )
    grade: list[dict] = []

    for segmento, produto in pares:
        grupo: dict = {}

        for subject in subjects:
            if (subject["type"], subject["level"]) == (
                "customer_segmentation",
                "segment",
            ):
                grupo[f"{subject['type']}.{subject['level']}"] = segmento
            elif (subject["type"], subject["level"]) == ("product", "product"):
                grupo[f"{subject['type']}.{subject['level']}"] = produto
            else:
                raise ValueError(
                    f"eixo '{subject['type']}.{subject['level']}' fora do oracle."
                )

        grade.append(grupo)

    return grade


def _cliente_passa(cliente: str, sample: list[dict]) -> bool:

    info = _cliente_por_id()[cliente]

    for condition in sample:
        if (condition["type"], condition["level"]) == (
            "customer_principality",
            "principality_depth",
        ):
            if _faixa(info["principalidade"]) != condition["value_id"]:
                return False
        elif (condition["type"], condition["level"]) == (
            "customer_relationship",
            "relationship_depth",
        ):
            if _faixa(info["vinculacao"]) != condition["value_id"]:
                return False
        elif (condition["type"], condition["level"]) == (
            "customer_segmentation",
            "segment",
        ):
            if info["segmento"] != SEGMENT_VALUE_IDS[condition["value_id"]]:
                return False

    return True


def _contrato_tem_grupo(contrato: str, grupo: str) -> bool:

    for item in ITENS_POR_CONTRATO[contrato]:
        if PRODUTOS[item][0] == grupo:
            return True

    return False


def _contrato_passa(contrato: str, sample: list[dict]) -> bool:

    cliente = CLIENTE_POR_CONTRATO[contrato]

    if not _cliente_passa(cliente, sample):
        return False

    for condition in sample:
        if (condition["type"], condition["level"]) == ("product", "product_group"):
            if not _contrato_tem_grupo(
                contrato, GROUP_VALUE_IDS[condition["value_id"]]
            ):
                return False

    return True


def _chave_grupo(subjects: list[dict], grupo: dict) -> tuple:

    return tuple(
        grupo.get(f"{s['type']}.{s['level']}") for s in subjects if s["type"] != "total"
    )


def _linhas_rentabilidade(
    subjects: list[dict], sample: list[dict], usa_item: bool
) -> list[tuple]:

    linhas: list[tuple] = []

    if usa_item:
        for contrato, id_produto, mes, saldo, margem in RENT_ITEM:
            if not _contrato_passa(contrato, sample):
                continue

            grupo = PRODUTOS[id_produto][1]
            segmento = SEGMENTO_POR_CLIENTE[CLIENTE_POR_CONTRATO[contrato]]
            linhas.append((mes, segmento, grupo, saldo, margem))
    else:
        for cliente, mes, saldo, margem in RENT_CLIENTE:
            if not _cliente_passa(cliente, sample):
                continue

            linhas.append((mes, SEGMENTO_POR_CLIENTE[cliente], None, saldo, margem))

    return linhas


def _posicao_no_grupo(subjects: list[dict], linha: tuple) -> tuple:

    _mes, segmento, produto, _saldo, _margem = linha
    valores: list = []

    for subject in subjects:
        if subject["type"] == "total":
            continue

        if (subject["type"], subject["level"]) == (
            "customer_segmentation",
            "segment",
        ):
            valores.append(segmento)
        elif (subject["type"], subject["level"]) == ("product", "product"):
            valores.append(produto)

    return tuple(valores)


def _soma(valores: list[Decimal]) -> Decimal:

    total = Decimal("0")

    for valor in valores:
        total += valor

    return total


def _razao(margens: list[Decimal], saldos: list[Decimal]) -> Decimal | None:

    if not saldos:
        return None

    denominador = _soma(saldos)

    if denominador == 0:
        return None

    return _soma(margens) / denominador


def compute_expected(
    rule_id: str,
    subjects: list[dict],
    sample: list[dict],
    period: dict,
) -> list[tuple]:

    buckets = buckets_for(period)
    grade = _grade_grupos(subjects, rule_id)
    usa_item = any(s["type"] == "product" for s in (*subjects, *sample))

    if rule_id in ("profitability", "outstanding_balance"):
        return _expected_valor(
            rule_id, subjects, sample, period, buckets, grade, usa_item
        )

    return _expected_contagem(rule_id, subjects, sample, buckets, grade)


def _expected_valor(
    rule_id: str,
    subjects: list[dict],
    sample: list[dict],
    period: dict,
    buckets: list[str],
    grade: list[dict],
    usa_item: bool,
) -> list[tuple]:

    inicio = dt.date.fromisoformat(period["start"])
    fim = dt.date.fromisoformat(period["end"])
    por_celula: dict[tuple, dict] = {}

    for mes, segmento, produto, saldo, margem in _linhas_rentabilidade(
        subjects, sample, usa_item
    ):
        if not inicio <= mes <= fim:
            continue

        linha = (mes, segmento, produto, saldo, margem)

        if period["grain"] == "total" or period["type"] == "snapshot":
            bucket = period["end"]
        else:
            bucket = _bucket_end(mes, period["grain"]).isoformat()

        chave = (bucket, _posicao_no_grupo(subjects, linha))
        celula = por_celula.setdefault(chave, {"meses": {}})

        if rule_id == "outstanding_balance":
            por_mes = celula["meses"].setdefault(mes.isoformat(), [])
            por_mes.append(saldo)
        else:
            celula.setdefault("margens", []).append(margem)
            celula.setdefault("saldos", []).append(saldo)

    saida: list[tuple] = []

    for bucket in buckets:
        for grupo in grade:
            chave = (bucket, _chave_grupo(subjects, grupo))
            celula = por_celula.get(chave)

            if celula is None:
                saida.append((bucket, grupo, None))
            elif rule_id == "outstanding_balance":
                meses = celula["meses"]

                if not meses:
                    saida.append((bucket, grupo, None))
                else:
                    saida.append((bucket, grupo, _soma(meses[max(meses)])))
            else:
                saida.append(
                    (bucket, grupo, _razao(celula["margens"], celula["saldos"]))
                )

    return saida


def _expected_contagem(
    rule_id: str,
    subjects: list[dict],
    sample: list[dict],
    buckets: list[str],
    grade: list[dict],
) -> list[tuple]:

    saida: list[tuple] = []

    for bucket in buckets:
        data = dt.date.fromisoformat(bucket)
        por_grupo: dict[tuple, set] = {}

        for contrato, cliente, inicio, fim in CONTRATOS:
            if not _ativo(inicio, fim, data):
                continue

            if not _contrato_passa(contrato, sample):
                continue

            if rule_id == "contract_count":
                chave_item = contrato
                grupos_contrato = _grupos_do_contrato(subjects, contrato, cliente)
            else:
                chave_item = cliente
                grupos_contrato = _grupos_do_cliente(subjects, contrato, cliente)

            for chave in grupos_contrato:
                por_grupo.setdefault(chave, set()).add(chave_item)

        for grupo in grade:
            chave = _chave_grupo(subjects, grupo)
            valores = por_grupo.get(chave)

            saida.append((bucket, grupo, len(valores) if valores else None))

    return saida


def _grupos_do_contrato(
    subjects: list[dict], contrato: str, cliente: str
) -> list[tuple]:

    usa_produto = any(s["type"] == "product" for s in subjects)

    if usa_produto:
        return [
            _posicao_contrato(subjects, contrato, cliente, PRODUTOS[item][1])
            for item in ITENS_POR_CONTRATO[contrato]
        ]

    return [_posicao_contrato(subjects, contrato, cliente, None)]


def _grupos_do_cliente(
    subjects: list[dict], contrato: str, cliente: str
) -> list[tuple]:

    return _grupos_do_contrato(subjects, contrato, cliente)


def _posicao_contrato(
    subjects: list[dict], contrato: str, cliente: str, produto: str | None
) -> tuple:

    segmento = SEGMENTO_POR_CLIENTE[cliente]
    valores: list = []

    for subject in subjects:
        if (subject["type"], subject["level"]) == (
            "customer_segmentation",
            "segment",
        ):
            valores.append(segmento)
        elif (subject["type"], subject["level"]) == ("product", "product"):
            valores.append(produto)

    return tuple(valores)


def table_summaries() -> dict[str, dict[str, str]]:

    rent_saldo = _soma([saldo for _, _, saldo, _ in RENT_CLIENTE])
    rent_margem = _soma([margem for _, _, _, margem in RENT_CLIENTE])
    item_saldo = _soma([saldo for _, _, _, saldo, _ in RENT_ITEM])
    item_margem = _soma([margem for _, _, _, _, margem in RENT_ITEM])

    return {
        "dim_produto": {"count": str(len(PRODUTOS))},
        "dim_segmento": {"count": "0"},
        "fato_cliente": {"count": str(len(CLIENTES))},
        "fato_contrato_produtos": {
            "count": str(sum(len(v) for v in ITENS_POR_CONTRATO.values()))
        },
        "fato_contratos": {"count": str(len(CONTRATOS))},
        "fato_rentabilidade_cliente": {
            "count": str(len(RENT_CLIENTE)),
            "max_mes_ref": max(mes for _, mes, _, _ in RENT_CLIENTE).isoformat(),
            "sum_vl_margem": f"{rent_margem:.2f}",
            "sum_vl_saldo": f"{rent_saldo:.2f}",
        },
        "fato_rentabilidade_contrato_produto": {
            "count": str(len(RENT_ITEM)),
            "max_mes_ref": max(mes for _, _, mes, _, _ in RENT_ITEM).isoformat(),
            "sum_vl_margem": f"{item_margem:.2f}",
            "sum_vl_saldo": f"{item_saldo:.2f}",
        },
    }


def fixture_fingerprint() -> str:

    payload = json.dumps(table_summaries(), sort_keys=True, separators=(",", ":"))

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def seed_rows() -> dict[str, list[tuple]]:

    clientes = [
        (
            cliente,
            "F" if segmento != "Private" else "J",
            segmento,
            segmento,
            segmento,
            segmento,
            princ,
            vinc,
        )
        for cliente, segmento, princ, vinc in CLIENTES
    ]

    produtos = [
        (id_produto, f"CRD{idx:04d}", grupo, produto, f"{produto} Sub")
        for idx, (id_produto, (grupo, produto)) in enumerate(PRODUTOS.items(), start=1)
    ]

    contratos = [
        (contrato, cliente, inicio, fim) for contrato, cliente, inicio, fim in CONTRATOS
    ]

    composicao = [
        (contrato, item)
        for contrato, itens in ITENS_POR_CONTRATO.items()
        for item in itens
    ]

    rent_cliente = [
        (cliente, mes, saldo, margem, mes + dt.timedelta(days=3))
        for cliente, mes, saldo, margem in RENT_CLIENTE
    ]

    rent_item = [
        (contrato, item, mes, saldo, margem, mes + dt.timedelta(days=3))
        for contrato, item, mes, saldo, margem in RENT_ITEM
    ]

    return {
        "fato_cliente": clientes,
        "dim_produto": produtos,
        "fato_contratos": contratos,
        "fato_contrato_produtos": composicao,
        "fato_rentabilidade_cliente": rent_cliente,
        "fato_rentabilidade_contrato_produto": rent_item,
    }


# ---------------------------------------------------------------------------
# Componentes para o repositório de fixture do harness de avaliação offline
# ---------------------------------------------------------------------------
#
# `compute_expected` é o gold (valor final); as funções abaixo devolvem as
# PARCELAS por (bucket, grupo) que o motor combina. Espelham a mesma semântica
# célula a célula — razão re-derivada, estoque lido no fim do bucket, ausência
# como célula vazia, contrato ativo por datas — mas por um caminho de código
# independente do gold, para que a comparação motor × oráculo no harness
# exercite a combinação do núcleo sem ClickHouse.


def aggregated_components(
    rule_id: str,
    subjects: list[dict],
    sample: list[dict],
    period: dict,
) -> list[tuple[str, dict, dict]]:
    """Parcelas por (bucket, grupo) para o repositório de fixture offline."""

    buckets = buckets_for(period)
    grade = _grade_grupos(subjects, rule_id)
    usa_item = any(s["type"] == "product" for s in (*subjects, *sample))

    if rule_id in ("profitability", "outstanding_balance"):
        return _componentes_valor(
            rule_id, subjects, sample, period, buckets, grade, usa_item
        )

    return _componentes_contagem(rule_id, subjects, sample, buckets, grade)


def _componentes_valor(
    rule_id: str,
    subjects: list[dict],
    sample: list[dict],
    period: dict,
    buckets: list[str],
    grade: list[dict],
    usa_item: bool,
) -> list[tuple[str, dict, dict]]:

    inicio = dt.date.fromisoformat(period["start"])
    fim = dt.date.fromisoformat(period["end"])
    por_celula: dict[tuple, dict] = {}

    for mes, segmento, produto, saldo, margem in _linhas_rentabilidade(
        subjects, sample, usa_item
    ):
        if not inicio <= mes <= fim:
            continue

        linha = (mes, segmento, produto, saldo, margem)

        if period["grain"] == "total" or period["type"] == "snapshot":
            bucket = period["end"]
        else:
            bucket = _bucket_end(mes, period["grain"]).isoformat()

        chave = (bucket, _posicao_no_grupo(subjects, linha))
        celula = por_celula.setdefault(chave, {"meses": {}})

        if rule_id == "outstanding_balance":
            celula["meses"].setdefault(mes.isoformat(), []).append(saldo)
        else:
            celula.setdefault("margens", []).append(margem)
            celula.setdefault("saldos", []).append(saldo)

    saida: list[tuple[str, dict, dict]] = []

    for bucket in buckets:
        for grupo in grade:
            chave = (bucket, _chave_grupo(subjects, grupo))
            celula = por_celula.get(chave)

            if celula is None:
                saida.append((bucket, grupo, {}))
                continue

            if rule_id == "outstanding_balance":
                meses = celula["meses"]

                if not meses:
                    saida.append((bucket, grupo, {}))
                else:
                    saida.append((bucket, grupo, {"value": _soma(meses[max(meses)])}))
            else:
                saida.append(
                    (
                        bucket,
                        grupo,
                        {
                            "numerator": _soma(celula["margens"]),
                            "denominator": _soma(celula["saldos"]),
                        },
                    )
                )

    return saida


def _componentes_contagem(
    rule_id: str,
    subjects: list[dict],
    sample: list[dict],
    buckets: list[str],
    grade: list[dict],
) -> list[tuple[str, dict, dict]]:

    saida: list[tuple[str, dict, dict]] = []

    for bucket in buckets:
        data = dt.date.fromisoformat(bucket)
        por_grupo: dict[tuple, set] = {}

        for contrato, cliente, inicio, fim in CONTRATOS:
            if not _ativo(inicio, fim, data):
                continue

            if not _contrato_passa(contrato, sample):
                continue

            if rule_id == "contract_count":
                chave_item = contrato
                grupos_contrato = _grupos_do_contrato(subjects, contrato, cliente)
            else:
                chave_item = cliente
                grupos_contrato = _grupos_do_cliente(subjects, contrato, cliente)

            for chave in grupos_contrato:
                por_grupo.setdefault(chave, set()).add(chave_item)

        for grupo in grade:
            chave = _chave_grupo(subjects, grupo)
            valores = por_grupo.get(chave)

            if valores:
                saida.append((bucket, grupo, {"value": len(valores)}))
            else:
                saida.append((bucket, grupo, {}))

    return saida

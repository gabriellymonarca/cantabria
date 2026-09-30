#!/usr/bin/env python3
"""Gerador de dados fictícios do Cantábria (determinístico).

Lê as hierarquias oficiais do `.xlsm` e produz as bases:

    fato_cliente, dim_segmento, dim_produto,
    fato_contratos, fato_contrato_produtos,
    fato_rentabilidade_cliente, fato_rentabilidade_contrato_produto.

Os números oficiais são apenas `vl_saldo` e `vl_margem` (R$). A taxa de
rentabilidade é LATENTE no gerador e nunca persistida — é derivada por
`Σ vl_margem ÷ Σ vl_saldo` no motor de cálculo.

Uso:
    python utils/generate_cantabria_data.py                 # resumo
    python utils/generate_cantabria_data.py --out data/dataset
    python utils/generate_cantabria_data.py --clientes 10000 --seed 42
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from faker import Faker

REPO_ROOT = Path(__file__).resolve().parent.parent
XLSM_DEFAULT = REPO_ROOT / "data" / "data-generation" / "produtos_segmentos.xlsm"

# --- Parâmetros de geração ---------------------------------------------------
DEFAULT_SEED = 42
DEFAULT_CLIENTES = 10_000
JANELA_INICIO = dt.date(2024, 9, 1)
JANELA_FIM = dt.date(2026, 8, 31)
LAG_MEDICAO_DIAS = 3


def _ultimo_dia(ano: int, mes: int) -> int:
    if mes == 12:
        return 31
    return (dt.date(ano, mes + 1, 1) - dt.timedelta(days=1)).day


MESES = [
    dt.date(y, m, _ultimo_dia(y, m))
    for (y, m) in [
        (
            (JANELA_INICIO.year + (JANELA_INICIO.month - 1 + i) // 12),
            (JANELA_INICIO.month - 1 + i) % 12 + 1,
        )
        for i in range(24)
    ]
]


# --- Faixa governada derivada do score cru ------------------------------------
# Default: alta >= 70, media 40-69, baixa < 40 (escala 0-100).
FAIXA_ALTA_MIN = Decimal("70")
FAIXA_MEDIA_MIN = Decimal("40")


# --- Magnitudes e tendências (defaults ajustáveis) ----------------------------
# Saldo-base por segmento (R$): (min, max, moda/típico).
SALDO_POR_SEGMENTO = {
    "Varejo PF": (1_000.0, 150_000.0, 15_000.0),
    "Varejo PJ": (10_000.0, 2_000_000.0, 180_000.0),
    "Varejo Rural": (5_000.0, 500_000.0, 70_000.0),
    "Corporate Middle": (500_000.0, 20_000_000.0, 3_000_000.0),
    "Corporate Large": (5_000_000.0, 100_000_000.0, 20_000_000.0),
    "Private": (500_000.0, 30_000_000.0, 4_000_000.0),
    "CIB": (10_000_000.0, 1_000_000_000.0, 120_000_000.0),
}

# Taxa-alvo anual por grupo de produto: (min, max).
TAXA_POR_GRUPO = {
    "Crédito Rotativo": (0.15, 0.35),
    "Crédito Parcelado": (0.08, 0.20),
    "Crédito Consignado": (0.05, 0.12),
    "Crédito com Garantia": (0.02, 0.08),
    "Crédito Especializado": (0.06, 0.18),
    "Crédito Transacional": (0.03, 0.10),
    "Renegociação de Dívidas": (0.10, 0.22),
}
TAXA_DEFAULT = (0.05, 0.15)

# Incremento na taxa-alvo (p.p.) por faixa da dimensão.
INC_PRINCIPALIDADE = {"baixa": 0.0, "media": 0.015, "alta": 0.030}
INC_VINCULACAO = {"baixa": 0.0, "media": 0.010, "alta": 0.020}

# Ajuste de taxa por segmento (p.p.): Varejo acima; Corporate/CIB/Private
# abaixo (saldos muito maiores).
INC_SEGMENTO = {
    "Varejo PF": 0.030,
    "Varejo PJ": 0.025,
    "Varejo Rural": 0.035,
    "Private": -0.015,
    "Corporate Middle": -0.020,
    "Corporate Large": -0.025,
    "CIB": -0.030,
}

# Distribuição de faixa (default) e viés premium.
DIST_DEPTH = [("baixa", 0.40), ("media", 0.40), ("alta", 0.20)]
DIST_DEPTH_PREMIUM = [("baixa", 0.25), ("media", 0.40), ("alta", 0.35)]
PREMIUM_SEGMENTOS = {"Private", "Corporate Middle", "Corporate Large", "CIB"}

# Nº de contratos por cliente/segmento: (min, max, típico).
CONTRATOS_POR_SEGMENTO = {
    "Varejo PF": (1, 3, 2.0),
    "Varejo PJ": (1, 5, 3.0),
    "Varejo Rural": (1, 3, 2.0),
    "Corporate Middle": (2, 7, 4.0),
    "Corporate Large": (2, 9, 5.0),
    "Private": (2, 7, 4.0),
    "CIB": (3, 10, 6.0),
}

# Nº de produtos por contrato: 1 ~70%, 2 ~22%, 3+ ~8%.
DIST_PRODUTOS_POR_CONTRATO = [(1, 0.70), (2, 0.22), (3, 0.08)]

# Distribuição de clientes por ds_segm: proporcional à base real.
DIST_SEGMENTO = [
    ("Varejo PF", 0.62),
    ("Varejo PJ", 0.21),
    ("Varejo Rural", 0.09),
    ("Corporate Middle", 0.04),
    ("Corporate Large", 0.01),
    ("Private", 0.02),
    ("CIB", 0.01),
]

# Ordem de grandeza do saldo-base por GRUPO de produto (multiplicador relativo).
FATOR_SALDO_GRUPO = {
    "Crédito Rotativo": 0.35,
    "Crédito Parcelado": 1.00,
    "Crédito Consignado": 0.60,
    "Crédito com Garantia": 1.80,
    "Crédito Especializado": 2.20,
    "Crédito Transacional": 0.25,
    "Renegociação de Dívidas": 0.90,
}


@dataclass(frozen=True)
class Segmento:
    id: str
    tp_pess: str
    ds_segm_agrup: str
    ds_segm: str
    ds_subsegm_agrup: str
    ds_subsegm: str


@dataclass(frozen=True)
class Produto:
    id: str
    cd: str
    ds_grupo_prod: str
    ds_produto: str
    ds_subproduto: str


def _nome_pf(fake: Faker) -> str:
    partes = []

    for _ in range(fake.random_int(min=1, max=2)):
        partes.append(fake.first_name())

    for _ in range(fake.random_int(min=1, max=2)):
        partes.append(fake.last_name())
    return " ".join(partes)


def _uuid4(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


def _faixa(score: Decimal) -> str:

    if score >= FAIXA_ALTA_MIN:
        return "alta"

    if score >= FAIXA_MEDIA_MIN:
        return "media"

    return "baixa"


def _score(rng: random.Random, faixa: str) -> Decimal:

    if faixa == "alta":
        return Decimal(f"{rng.uniform(70.0, 98.0):.2f}")

    if faixa == "media":
        return Decimal(f"{rng.uniform(40.0, 69.0):.2f}")

    return Decimal(f"{rng.uniform(5.0, 39.0):.2f}")


# --- Leitura do .xlsm ---------------------------------------------------------


def ler_segmentos(caminho: Path) -> list[Segmento]:
    import openpyxl

    ws = openpyxl.load_workbook(caminho, data_only=True, keep_vba=False)["segmentos"]
    linhas = [
        linha
        for linha in ws.iter_rows(min_row=2, values_only=True)
        if linha[0] is not None
    ]
    return [
        Segmento(
            id=f"SEG_{idx:02d}",
            tp_pess=linha[0],
            ds_segm_agrup=linha[1],
            ds_segm=linha[2],
            ds_subsegm_agrup=linha[3],
            ds_subsegm=linha[4],
        )
        for idx, linha in enumerate(linhas, start=1)
    ]


def ler_produtos(caminho: Path) -> list[Produto]:
    import openpyxl

    ws = openpyxl.load_workbook(caminho, data_only=True, keep_vba=False)["produtos"]
    linhas = [
        linha
        for linha in ws.iter_rows(min_row=2, values_only=True)
        if linha[0] is not None
    ]
    produtos = []
    vistos = set()

    for grupo, produto, subproduto in linhas:
        chave = (grupo, produto, subproduto)
        if chave in vistos:
            continue
        vistos.add(chave)
        idx = len(produtos) + 1
        produtos.append(
            Produto(
                id=f"PROD_{idx:03d}",
                cd=f"CRD{idx:04d}",
                ds_grupo_prod=grupo,
                ds_produto=produto,
                ds_subproduto=subproduto,
            )
        )
    return produtos


def ler_allowlist(caminho: Path) -> dict[tuple, list[tuple]]:
    """(tp_pess, ds_segm, ds_segm_agrup, ds_subsegm_agrup, ds_subsegm) -> produtos."""
    import openpyxl

    ws = openpyxl.load_workbook(caminho, data_only=True, keep_vba=False)[
        "matriz_seg_prod"
    ]
    linhas = [
        linha
        for linha in ws.iter_rows(min_row=2, values_only=True)
        if linha[0] is not None
    ]
    allow: dict[tuple, list[tuple]] = {}

    for r in linhas:
        seg_key = (
            r[0],
            r[2],
            r[1],
            r[3],
            r[4],
        )  # tp_pess, ds_segm, agrup, sub_agrup, sub
        prod_key = (r[5], r[6], r[7])
        allow.setdefault(seg_key, [])
        if prod_key not in allow[seg_key]:
            allow[seg_key].append(prod_key)
    return allow


# --- Amostragem ---------------------------------------------------------------


def _weighted_choice[T](rng: random.Random, opcoes: list[tuple[T, float]]) -> T:
    total = sum(peso for _, peso in opcoes)
    ponto = rng.random() * total
    acumulado = 0.0

    for valor, peso in opcoes:
        acumulado += peso
        if ponto <= acumulado:
            return valor

    return opcoes[-1][0]


def _triangular(rng: random.Random, faixa: tuple[float, float, float]) -> float:
    lo, hi, tipico = faixa
    return rng.triangular(lo, hi, min(max(tipico, lo), hi))


def _rand_contratos(rng: random.Random, faixa: tuple[int, int, float]) -> int:
    lo, hi, tipico = faixa
    valor = int(round(rng.triangular(lo, hi, tipico)))
    return max(lo, min(hi, valor))


def _escolher_indice(rng: random.Random, pesos: list[float]) -> int:
    total = sum(pesos)
    ponto = rng.random() * total
    acumulado = 0.0

    for j, peso in enumerate(pesos):
        acumulado += peso
        if ponto <= acumulado:
            return j

    return len(pesos) - 1


# --- Geração ------------------------------------------------------------------


def _segmentos_por_tp(segmentos: list[Segmento]) -> dict[str, list[Segmento]]:
    por_tp: dict[str, list[Segmento]] = {"F": [], "J": []}

    for seg in segmentos:
        por_tp[seg.tp_pess].append(seg)
    return por_tp


def _mapa_segm_agrup(segmentos: list[Segmento]) -> dict[str, str]:
    return {seg.ds_segm: seg.ds_segm_agrup for seg in segmentos}


def gerar_clientes(
    rng: random.Random,
    fake: Faker,
    segmentos: list[Segmento],
    n_clientes: int,
) -> list[dict]:
    por_tp = _segmentos_por_tp(segmentos)
    segm_agrup = _mapa_segm_agrup(segmentos)

    pesos_tp: list[tuple[str, float]] = [
        (
            "J",
            sum(
                p
                for s, p in DIST_SEGMENTO
                if s in ("Varejo PJ", "Corporate Middle", "Corporate Large", "CIB")
            ),
        ),
        (
            "F",
            sum(
                p
                for s, p in DIST_SEGMENTO
                if s in ("Varejo PF", "Varejo Rural", "Private")
            ),
        ),
    ]
    # Rural é o único segmento compartilhado entre F e J: resolve depois do tp_pess.
    dist_por_tp: dict[str, list[tuple[str, float]]] = {
        "F": [
            ("Varejo PF", sum(p for s, p in DIST_SEGMENTO if s == "Varejo PF")),
            ("Private", sum(p for s, p in DIST_SEGMENTO if s == "Private")),
            ("Varejo Rural", sum(p for s, p in DIST_SEGMENTO if s == "Varejo Rural")),
        ],
        "J": [
            ("Varejo PJ", sum(p for s, p in DIST_SEGMENTO if s == "Varejo PJ")),
            (
                "Corporate Middle",
                sum(p for s, p in DIST_SEGMENTO if s == "Corporate Middle"),
            ),
            (
                "Corporate Large",
                sum(p for s, p in DIST_SEGMENTO if s == "Corporate Large"),
            ),
            ("CIB", sum(p for s, p in DIST_SEGMENTO if s == "CIB")),
            ("Varejo Rural", sum(p for s, p in DIST_SEGMENTO if s == "Varejo Rural")),
        ],
    }

    clientes: list[dict] = []

    for _ in range(n_clientes):
        while True:
            tp_pess = _weighted_choice(rng, pesos_tp)
            candidatos = por_tp[tp_pess]
            ds_segm = _weighted_choice(rng, dist_por_tp[tp_pess])
            validos = [s for s in candidatos if s.ds_segm == ds_segm]
            if validos:
                break
        seg = rng.choice(validos)

        premium = seg.ds_segm in PREMIUM_SEGMENTOS
        dist_depth = DIST_DEPTH_PREMIUM if premium else DIST_DEPTH

        if tp_pess == "F":
            nm_cliente = _nome_pf(fake)
        else:
            nm_cliente = fake.company()

        principalidade_score = _score(rng, _weighted_choice(rng, dist_depth))
        vinculacao_score = _score(rng, _weighted_choice(rng, dist_depth))

        clientes.append(
            {
                "id_cliente": _uuid4(rng),
                "cpf_cnpj": fake.cpf() if tp_pess == "F" else fake.cnpj(),
                "nm_cliente": nm_cliente,
                "ds_email": fake.email(),
                "nr_telefone": fake.phone_number(),
                "tp_pess": tp_pess,
                "ds_segm_agrup": segm_agrup[seg.ds_segm],
                "ds_segm": seg.ds_segm,
                "ds_subsegm_agrup": seg.ds_subsegm_agrup,
                "ds_subsegm": seg.ds_subsegm,
                "principalidade_score": principalidade_score,
                "vinculacao_score": vinculacao_score,
                "_seg_key": (
                    tp_pess,
                    seg.ds_segm,
                    seg.ds_segm_agrup,
                    seg.ds_subsegm_agrup,
                    seg.ds_subsegm,
                ),
            }
        )
    return clientes


def gerar_contratos(
    rng: random.Random,
    clientes: list[dict],
    produtos: list[Produto],
    allowlist: dict[tuple, list[tuple]],
) -> list[dict]:
    idx = {(_p.ds_grupo_prod, _p.ds_produto, _p.ds_subproduto): _p for _p in produtos}
    contratos: list[dict] = []
    seq = 0
    n_meses_janela = len(MESES)

    for cli in clientes:
        permitidos = allowlist.get(cli["_seg_key"])
        if not permitidos:
            raise RuntimeError(f"segmento sem allowlist: {cli['_seg_key']}")

        n = _rand_contratos(rng, CONTRATOS_POR_SEGMENTO[cli["ds_segm"]])

        for _ in range(n):
            # Produtos amostrados sem repetição DENTRO do contrato; entre
            # contratos do mesmo cliente a repetição é permitida.
            pool = list(permitidos)
            pesos = [max(0.05, FATOR_SALDO_GRUPO.get(g, 0.8)) for g, _, _ in pool]

            n_itens = min(_weighted_choice(rng, DIST_PRODUTOS_POR_CONTRATO), len(pool))
            itens = []

            for _ in range(n_itens):
                escolhido = _escolher_indice(rng, pesos)
                itens.append(idx[pool.pop(escolhido)])
                pesos.pop(escolhido)

            seq += 1
            # dt_ini ao longo/antes da janela (até ~4 anos antes do fim)
            dt_ini = JANELA_FIM - dt.timedelta(
                days=rng.randint(0, 365 * 4 + n_meses_janela * 30)
            )
            dt_encerramento = None
            if rng.random() < 0.22:
                candidato = dt_ini + dt.timedelta(days=rng.randint(90, 365 * 4))
                if candidato < JANELA_FIM:
                    dt_encerramento = candidato

            contratos.append(
                {
                    "id_contrato": f"CTR_{seq:08d}",
                    "id_cliente": cli["id_cliente"],
                    "dt_ini_contrato": dt_ini,
                    "dt_encerramento": dt_encerramento,
                    "_seg_key": cli["_seg_key"],
                    "_itens": itens,
                }
            )
    return contratos


def _saldo_base(rng: random.Random, segmento: str, grupo_prod: str) -> float:
    base = _triangular(rng, SALDO_POR_SEGMENTO[segmento])
    return base * FATOR_SALDO_GRUPO.get(grupo_prod, 1.0)


def _taxa_alvo(rng: random.Random, grupo_prod: str) -> float:
    lo, hi = TAXA_POR_GRUPO.get(grupo_prod, TAXA_DEFAULT)
    return rng.uniform(lo, hi)


def _ativo(contrato: dict, mes: dt.date) -> bool:
    if contrato["dt_ini_contrato"] > mes:
        return False

    fim = contrato["dt_encerramento"]
    return fim is None or mes <= fim


def _data_medicao(mes_ref: dt.date) -> dt.date:
    return mes_ref + dt.timedelta(days=LAG_MEDICAO_DIAS)


def gerar_rentabilidade(
    rng: random.Random,
    contratos: list[dict],
    clientes_por_id: dict[uuid.UUID, dict],
) -> tuple[list[dict], list[dict]]:
    detalhe: list[dict] = []
    acumulado: dict[tuple, list[Decimal]] = {}

    for ctr in contratos:
        cli = clientes_por_id[ctr["id_cliente"]]
        faixa_principalidade = _faixa(cli["principalidade_score"])
        faixa_vinculacao = _faixa(cli["vinculacao_score"])

        for prod in ctr["_itens"]:
            grupo = prod.ds_grupo_prod
            saldo_base = _saldo_base(rng, cli["ds_segm"], grupo)
            saldo = saldo_base

            taxa = (
                _taxa_alvo(rng, grupo)
                + INC_PRINCIPALIDADE[faixa_principalidade]
                + INC_VINCULACAO[faixa_vinculacao]
                + INC_SEGMENTO.get(cli["ds_segm"], 0.0)
            )
            taxa = max(0.01, taxa)

            for mes in MESES:
                if not _ativo(ctr, mes):
                    continue

                # random walk suave e positivo (amortização/uso)
                saldo *= 1.0 + rng.gauss(0.0, 0.03)
                saldo = max(saldo_base * 0.15, saldo)

                # ruído gaussiano ~ ±15% relativo sobre a taxa-alvo
                taxa_mes = max(0.005, taxa * (1.0 + rng.gauss(0.0, 0.08)))
                margem = saldo * taxa_mes

                vl_saldo = Decimal(f"{saldo:.2f}")
                vl_margem = Decimal(f"{margem:.2f}")

                detalhe.append(
                    {
                        "id_contrato": ctr["id_contrato"],
                        "id_produto": prod.id,
                        "mes_ref": mes,
                        "vl_saldo": vl_saldo,
                        "vl_margem": vl_margem,
                        "data_medicao": _data_medicao(mes),
                    }
                )

                chave = (cli["id_cliente"], mes)
                linha = acumulado.setdefault(chave, [Decimal("0"), Decimal("0")])
                linha[0] += vl_saldo
                linha[1] += vl_margem

    cliente = [
        {
            "id_cliente": id_cliente,
            "mes_ref": mes,
            "vl_saldo": saldo,
            "vl_margem": margem,
            "data_medicao": _data_medicao(mes),
        }
        for (id_cliente, mes), (saldo, margem) in acumulado.items()
    ]
    return detalhe, cliente


@dataclass
class Dataset:
    clientes: list[dict]
    segmentos: list[Segmento]
    produtos: list[Produto]
    contratos: list[dict]
    contrato_produtos: list[dict]
    rentabilidade_cliente: list[dict]
    rentabilidade_contrato_produto: list[dict]


def gerar_dataset(
    n_clientes: int = DEFAULT_CLIENTES,
    seed: int = DEFAULT_SEED,
    xlsm: Path = XLSM_DEFAULT,
) -> Dataset:
    rng = random.Random(seed)
    fake = Faker("pt_BR")
    Faker.seed(seed)

    segmentos = ler_segmentos(xlsm)
    produtos = ler_produtos(xlsm)
    allowlist = ler_allowlist(xlsm)

    clientes = gerar_clientes(rng, fake, segmentos, n_clientes)
    clientes_por_id = {c["id_cliente"]: c for c in clientes}
    contratos = gerar_contratos(rng, clientes, produtos, allowlist)

    contrato_produtos = [
        {"id_contrato": c["id_contrato"], "id_produto": p.id}
        for c in contratos
        for p in c["_itens"]
    ]
    rent_detalhe, rent_cliente = gerar_rentabilidade(rng, contratos, clientes_por_id)

    return Dataset(
        clientes=clientes,
        segmentos=segmentos,
        produtos=produtos,
        contratos=contratos,
        contrato_produtos=contrato_produtos,
        rentabilidade_cliente=rent_cliente,
        rentabilidade_contrato_produto=rent_detalhe,
    )


# --- Export opcional ----------------------------------------------------------


def _sem_internos(linhas: list[dict]) -> list[dict]:
    return [
        {
            chave: (str(valor) if isinstance(valor, uuid.UUID) else valor)
            for chave, valor in linha.items()
            if not chave.startswith("_")
        }
        for linha in linhas
    ]


def exportar_parquet(dataset: Dataset, destino: Path) -> None:
    import pandas as pd

    destino.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(_sem_internos(dataset.clientes)).to_parquet(
        destino / "fato_cliente.parquet", index=False
    )
    pd.DataFrame([vars(s) for s in dataset.segmentos]).to_parquet(
        destino / "dim_segmento.parquet", index=False
    )
    pd.DataFrame([vars(p) for p in dataset.produtos]).rename(
        columns={"id": "id_produto", "cd": "cd_produto"}
    ).to_parquet(destino / "dim_produto.parquet", index=False)
    pd.DataFrame(_sem_internos(dataset.contratos)).to_parquet(
        destino / "fato_contratos.parquet", index=False
    )
    pd.DataFrame(dataset.contrato_produtos).to_parquet(
        destino / "fato_contrato_produtos.parquet", index=False
    )
    pd.DataFrame(_sem_internos(dataset.rentabilidade_cliente)).to_parquet(
        destino / "fato_rentabilidade_cliente.parquet", index=False
    )
    pd.DataFrame(_sem_internos(dataset.rentabilidade_contrato_produto)).to_parquet(
        destino / "fato_rentabilidade_contrato_produto.parquet", index=False
    )


def resumo(dataset: Dataset) -> str:
    n_ctr_ativos = sum(1 for c in dataset.contratos if _ativo(c, MESES[-1]))
    linhas = [
        f"clientes:          {len(dataset.clientes):,}",
        f"segmentos:         {len(dataset.segmentos):,}",
        f"produtos:          {len(dataset.produtos):,}",
        f"contratos:         {len(dataset.contratos):,}",
        f"  ativos em {MESES[-1]}: {n_ctr_ativos:,}",
        f"itens contrato x produto: {len(dataset.contrato_produtos):,}",
        f"rent. cliente:     {len(dataset.rentabilidade_cliente):,} linhas (cliente x mes)",
        f"rent. item:        {len(dataset.rentabilidade_contrato_produto):,} linhas (contrato x produto x mes)",
    ]
    return "\n".join(linhas)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clientes", type=int, default=DEFAULT_CLIENTES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--xlsm", type=Path, default=XLSM_DEFAULT)
    parser.add_argument(
        "--out", type=Path, default=None, help="Diretório p/ export Parquet opcional"
    )
    args = parser.parse_args()

    dataset = gerar_dataset(args.clientes, args.seed, args.xlsm)
    print(resumo(dataset))

    if args.out:
        exportar_parquet(dataset, args.out)
        print(f"Parquet exportado em {args.out}")


if __name__ == "__main__":
    main()

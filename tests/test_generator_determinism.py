"""O gerador da base fictícia é determinístico.

Mesma seed → dataset bit a bit idêntico; seed diferente → dataset diferente.
O motor determinístico consome esse dataset, então a reprodutibilidade do
sistema começa aqui.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from utils.generate_cantabria_data import Dataset, gerar_dataset


def _hash(dataset: Dataset) -> str:

    payload = {
        "clientes": dataset.clientes,
        "segmentos": [asdict(segment) for segment in dataset.segmentos],
        "produtos": [asdict(product) for product in dataset.produtos],
        "contratos": dataset.contratos,
        "contrato_produtos": dataset.contrato_produtos,
        "rentabilidade_cliente": dataset.rentabilidade_cliente,
        "rentabilidade_contrato_produto": dataset.rentabilidade_contrato_produto,
    }
    serialized = json.dumps(payload, sort_keys=True, default=str)

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def test_mesma_seed_gera_o_mesmo_dataset() -> None:

    first = _hash(gerar_dataset(n_clientes=40, seed=7))
    second = _hash(gerar_dataset(n_clientes=40, seed=7))

    assert first == second


def test_seed_diferente_muda_o_dataset() -> None:

    first = _hash(gerar_dataset(n_clientes=40, seed=7))
    second = _hash(gerar_dataset(n_clientes=40, seed=8))

    assert first != second

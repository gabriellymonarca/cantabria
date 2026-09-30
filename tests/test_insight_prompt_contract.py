"""Contrato do redator v3: Markdown na forma, regras invioláveis 2 a 6 intactas.

Mudar um prompt é criar um novo diretório (`data/prompts/insight/v3/`), não
editar o v2. O teste garante que o v3 pede Markdown (manchete, pontos, tabela,
ressalvas), que as regras de fronteira 2 a 6 e o idioma do v1 foram copiados
literalmente, que a regra 1 exige percentual rotulado, proíbe números derivados
e guia a leitura de `trend`, e que o adapter e o config apontam para o v3 por
padrão.
"""

from __future__ import annotations

import re
from pathlib import Path

from contexts.financial_analysis.adapters.outbound.langchain_insight import (
    _PROMPTS_SUBDIR,
)
from cross_cutting.config import DataConfig

_PROMPTS = Path(__file__).resolve().parents[1] / "data" / "prompts" / "insight"


def _section(text: str, title: str) -> str:

    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)

    assert match is not None, f"seção '{title}' ausente"

    return match.group(1).strip()


def _rules(section: str) -> dict[int, str]:

    parts = re.split(r"^(\d+)\. ", section, flags=re.M)

    return {int(parts[i]): parts[i + 1].strip() for i in range(1, len(parts), 2)}


def test_v3_existe_e_se_marca_como_v3() -> None:

    text = (_PROMPTS / "v3" / "base.md").read_text(encoding="utf-8")

    assert "version: v3" in text.splitlines()[0]


def test_v3_pede_markdown_com_manchete_pontos_tabela_e_ressalvas() -> None:

    text = (_PROMPTS / "v3" / "base.md").read_text(encoding="utf-8")
    forma = _section(text, "Forma")

    assert "Markdown" in forma
    assert "negrito" in forma
    assert "2 a 5 itens" in forma
    assert "| Entidade | Valor | Unidade |" in forma
    assert "Ressalvas:" in forma
    assert "RESULTADO VERIFICADO" in forma


def test_v3_mantem_as_regras_inviolaveis_2_a_6_do_v1_literalmente() -> None:

    v1 = (_PROMPTS / "v1" / "base.md").read_text(encoding="utf-8")
    v3 = (_PROMPTS / "v3" / "base.md").read_text(encoding="utf-8")
    rules_v1 = _rules(_section(v1, "Regras invioláveis"))
    rules_v3 = _rules(_section(v3, "Regras invioláveis"))

    assert set(rules_v3) == {1, 2, 3, 4, 5, 6}

    for number in (2, 3, 4, 5, 6):
        assert rules_v1[number] == rules_v3[number]


def test_v3_mantem_o_idioma_do_v1_literalmente() -> None:

    v1 = (_PROMPTS / "v1" / "base.md").read_text(encoding="utf-8")
    v3 = (_PROMPTS / "v3" / "base.md").read_text(encoding="utf-8")

    assert _section(v1, "Idioma") == _section(v3, "Idioma")


def test_v3_exige_percentual_rotulado_e_proibe_numeros_derivados() -> None:

    text = (_PROMPTS / "v3" / "base.md").read_text(encoding="utf-8")
    regras = _section(text, "Regras invioláveis")

    assert "Taxas saem em decimal" not in regras
    assert "sempre em percentual" in regras
    assert "16% dos clientes" in regras
    assert "15,46% ao ano" in regras
    assert "derivados" in regras
    assert "diferenças, amplitudes, somas, percentuais recalculados" in regras
    assert "contagens de entidades" in regras
    assert "literalmente" in regras


def test_v3_guia_tendencia_sem_citar_niveis_mensais_ausentes() -> None:

    text = (_PROMPTS / "v3" / "base.md").read_text(encoding="utf-8")
    forma = _section(text, "Forma")

    assert "trend" in forma
    assert "direção e a inclinação" in forma
    assert "níveis mensais" in forma


def test_insight_aponta_para_v3_por_padrao() -> None:

    insight = DataConfig().resolved_insight_prompts_dir()

    assert _PROMPTS_SUBDIR.name == "v3"
    assert (insight.parent.name, insight.name) == ("insight", "v3")
    assert (insight / "base.md").is_file()
    assert DataConfig().resolved_interpretation_prompts_dir().name == "v1"

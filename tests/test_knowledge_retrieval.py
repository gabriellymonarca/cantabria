"""Recuperação do acervo: perguntas típicas voltam do documento certo.

O acervo vive em `data/knowledge/*.md` e é indexado por seção `##` com BM25
lexical, offline. Este teste fixa o contrato de conteúdo da frente de
conhecimento: capacidades, métodos de cálculo, métodos estatísticos, glossário e
conceitos de negócio respondem às perguntas que o usuário realmente faz, e as
perguntas fora do escopo continuam se abstendo.
"""

from __future__ import annotations

import pytest

from contexts.financial_analysis.adapters.outbound.local_knowledge import (
    LocalKnowledgeAdapter,
)

_CASES = [
    ("o que é vinculação?", "Vinculacao e principalidade - diferencas"),
    (
        "qual a diferença entre vinculação e principalidade?",
        "Vinculacao e principalidade - diferencas",
    ),
    ("como se calcula rentabilidade?", "Como o banco calcula rentabilidade"),
    (
        "o que é tendência?",
        "O que é tendência (regressão linear) e o que não é previsão",
    ),
    (
        "você tem regressão?",
        "O que é tendência (regressão linear) e o que não é previsão",
    ),
    ("o que é participação?", "O que é participação (share) e como é calculada"),
    (
        "como é a participação acumulada?",
        "O que é participação (share) e como é calculada",
    ),
    ("o que é carteira e saldo?", "Como o banco calcula carteira e saldo"),
    ("como funciona a contagem de contratos?", "Como o banco conta contratos"),
    ("o que é a contagem de clientes?", "Como o banco conta clientes"),
    (
        "o que é variação entre períodos?",
        "O que é variação entre períodos e como é calculada",
    ),
    ("o que é dispersão?", "O que é dispersão, desvio-padrão e volatilidade"),
    ("o que é desvio-padrão?", "O que é dispersão, desvio-padrão e volatilidade"),
    ("o que é correlação?", "O que é correlação de Pearson entre duas métricas"),
    ("o que é outlier?", "O que é outlier (valor atípico) e como é detectado"),
    ("o que é um valor atípico?", "O que é outlier (valor atípico) e como é detectado"),
    (
        "quais métricas existem?",
        "O que o Cantábria faz - capacidades do copiloto",
    ),
    ("o que você faz?", "O que o Cantábria faz - capacidades do copiloto"),
    (
        "quais métodos estatísticos existem?",
        "O que o Cantábria faz - capacidades do copiloto",
    ),
    ("o que é CDI?", "CDI, SELIC e IPCA como referências de mercado"),
    ("o que é SELIC?", "CDI, SELIC e IPCA como referências de mercado"),
    ("o que é IPCA?", "CDI, SELIC e IPCA como referências de mercado"),
    (
        "como comparar a rentabilidade com o CDI?",
        "CDI, SELIC e IPCA como referências de mercado",
    ),
    ("o que é estoque e fluxo?", "Estoque versus fluxo"),
    ("o que é produção de crédito?", "Estoque versus fluxo"),
    ("como funciona a regra k igual a 10", "Politica de celula pequena (k igual a 10)"),
    (
        "como funciona a segmentação de clientes?",
        "Metodologia de segmentacao de clientes",
    ),
    (
        "quais produtos o segmento Private pode contratar?",
        "Produtos permitidos por segmento (matriz segmento x produto)",
    ),
]


@pytest.mark.parametrize(("question", "title"), _CASES)
def test_pergunta_tipica_recupera_o_documento_certo(question: str, title: str) -> None:

    excerpts = LocalKnowledgeAdapter().retrieve(question, locale="pt-BR")

    assert excerpts, f"sem trechos para {question!r}"
    assert excerpts[0].title == title
    assert all(excerpt.version == "v1" for excerpt in excerpts)


def test_tendencia_e_regressao_e_nunca_previsao() -> None:

    excerpts = LocalKnowledgeAdapter().retrieve("o que é tendência?", locale="pt-BR")

    assert excerpts[0].title == (
        "O que é tendência (regressão linear) e o que não é previsão"
    )

    texts = " ".join(excerpt.text for excerpt in excerpts)

    assert "mínimos quadrados" in texts
    assert "não projeta" in texts


def test_perguntas_fora_do_escopo_nao_vazam_documento() -> None:

    adapter = LocalKnowledgeAdapter()

    assert adapter.retrieve("Qual é a capital da França?", locale="pt-BR") == []
    assert (
        adapter.retrieve("Qual o CPF do titular João da Silva?", locale="pt-BR") == []
    )


def test_trechos_do_acervo_carregam_proveniencia() -> None:

    excerpts = LocalKnowledgeAdapter().retrieve(
        "quais métricas existem?", locale="pt-BR"
    )

    assert excerpts
    for excerpt in excerpts:
        assert excerpt.document_id
        assert excerpt.title
        assert excerpt.section
        assert excerpt.text

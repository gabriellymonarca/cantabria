---
document_id: doc-segmentacao
title: Metodologia de segmentacao de clientes
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## Hierarquia de segmentação e classificação do cliente

Todo cliente pertence a uma hierarquia de cinco niveis: tipo de pessoa (PF ou PJ), grupo de segmento, segmento, grupo de subsegmento e subsegmento. Os segmentos incluem Varejo PF, Varejo PJ, Varejo Rural, Corporate Middle, Corporate Large, Private e CIB.

## Combinações válidas de segmento e tipo de pessoa

Existem 13 combinacoes validas de segmento, listadas no catalogo dim_segmento. A combinacao precisa ser coerente com o tipo de pessoa. O gerador e o validador usam essa lista como referencia de conformidade.

## Como o cliente entra no cálculo de segmentos

O cliente e a unidade de juncao, nunca eixo de agrupamento: identificadores de cliente nao aparecem em resultado. As hierarquias de cliente saem da tabela de rentabilidade por cliente, agrupada pelo nivel pedido (por exemplo segmento ou subsegmento).

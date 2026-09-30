---
document_id: doc-clientes
title: Como o banco conta clientes
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que é a contagem da base ativa

A contagem da base ativa mede quantos relacionamentos têm contrato ativo: cada cliente com ao menos um contrato ativo conta uma vez. No catálogo, esse conceito é a métrica customer_count, com unidade de contagem.

## Como a contagem da base ativa é calculada

Cada cliente conta uma única vez, no ponto no tempo pedido, mesmo que tenha vários contratos. O cliente é a unidade de junção: identificadores não aparecem em resultados, apenas os recortes agregados por segmento, vínculo, principalidade ou produto.

## Quando a contagem da base ativa pode ser somada

Entre grupos, a contagem só é somável quando cada cliente pertence a exatamente um grupo. É somável entre segmentos, mas não entre produtos, porque um cliente pode ter mais de um produto. Entre períodos, nunca se soma: é leitura pontual no fim da janela.

## O que a contagem da base ativa não é

Não é uma lista individual de pessoas, não é a soma das contagens mensais e não mostra identificadores. Células com menos de 10 pessoas na base são suprimidas, junto com células companheiras, para impedir reidentificação; ausência é nulo com motivo, nunca zero.

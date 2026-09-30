---
document_id: doc-principalidade
title: Principalidade - o que e e como e apurada
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que é principalidade

Principalidade mede a profundidade da relacao principal do cliente com o banco: quanto da vida financeira central do cliente passa pela conta principal. E um eixo ordinal governado com tres niveis: baixa, media e alta.

## Como a principalidade é apurada

A area de negocio envia o escore cru principalidade_score em escala de 0 a 100. O adaptador deriva a faixa governada pela regra versionada no catalogo: alta a partir de 70, media de 40 a 69 e baixa abaixo de 40. O escore continuo nunca e eixo de agrupamento direto.

## Principalidade como eixo e como amostra

A principalidade serve tanto de eixo ("rentabilidade por principalidade", um valor por nivel) quanto de amostra ("produto mais rentavel entre clientes de alta principalidade", que filtra quem entra sem criar linhas). O catalogo de amostra e o mesmo catalogo de eixos.

---
document_id: doc-cdi-selic-ipca
title: CDI, SELIC e IPCA como referências de mercado
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que são CDI, SELIC e IPCA no Cantábria

CDI, SELIC e IPCA são séries macroeconômicas de referência publicadas pelo Banco Central. No Cantábria são métricas do catálogo (cdi_rate, selic_rate e inflation_ipca) lidas dos dados oficiais como qualquer outra métrica: o modelo nunca busca a taxa em fonte externa nem a recalcula.

## Taxa mensal e capitalização composta da janela

As séries chegam como taxa percentual de cada mês. Ao colapsar uma janela de vários meses no grão total, a taxa não é média nem soma: compõe-se o fator de cada mês (um mais a taxa) e subtrai-se um do produto. O resultado é a taxa efetiva acumulada da janela.

## Anualização para comparar com a rentabilidade

A taxa anualizada eleva o fator acumulado à potência de doze sobre o número de meses com dado. A rentabilidade também é anual, então essa é a base de comparação entre as duas: rentabilidade e CDI podem ser justapostos na mesma análise.

## Por que CDI, SELIC e IPCA só existem no total

São séries únicas para o país: não têm segmento, produto, cliente nem vínculo. Planos com recorte de negócio sobre essas métricas são recusados como não expressáveis, e o único grão válido é o total.

## O que CDI, SELIC e IPCA não são

Não são previsão nem projeção de taxa futura, e não substituem a rentabilidade: servem de referência externa. Mês sem dado na série vira valor ausente com motivo, nunca zero.

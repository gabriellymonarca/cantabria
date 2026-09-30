---
document_id: doc-variacao
title: O que é variação entre períodos e como é calculada
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que é variação entre períodos

Variação compara a mesma métrica, com o mesmo recorte, em dois períodos fechados distintos. O método variation devolve a diferença absoluta e a diferença percentual de cada entidade, e é assim que perguntas do tipo "melhorou ou piorou?" são respondidas.

## Como a variação absoluta e percentual é calculada

A variação absoluta é o valor do período atual menos o valor do período base; em taxas, a diferença já sai em pontos percentuais. A variação percentual é a absoluta dividida pelo valor base; sem base válida, o percentual volta nulo com motivo, nunca zero.

## Requisitos para comparar dois períodos

Os dois períodos precisam ser disjuntos, de duração igual, com o mesmo tipo e grão, e em ordem cronológica. Um intervalo entre as janelas é permitido: agosto de 2025 contra agosto de 2026 é uma comparação ano contra ano legítima.

## O que variação não é

Não compara métricas diferentes na mesma janela, não usa média de taxas mensais e não ordena nem escolhe o melhor resultado: isso é papel do ranking. Variação não é a taxa da janela, é a diferença entre duas leituras verificadas.

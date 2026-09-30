---
document_id: doc-outlier
title: O que é outlier (valor atípico) e como é detectado
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que é outlier (valor atípico)

Outlier é um ponto muito distante do comportamento do restante da série. Ele não é necessariamente erro de dado: pode ser um evento real que merece investigação do negócio.

## Como o outlier é detectado pela cerca IQR 1.5

O método outlier calcula o primeiro e o terceiro quartis da série e define cercas em quartil um menos 1,5 vezes o IQR e quartil três mais 1,5 vezes o IQR. Pontos fora dessas cercas são marcados; são necessários ao menos 4 pontos, e sem atípicos o resultado informa contagem zero.

## O que um outlier não é

Não é um valor descartado automaticamente, não prova erro nem causa, e não substitui a investigação do negócio. O resultado apenas sinaliza os pontos fora das cercas, com os limites usados, para leitura humana.

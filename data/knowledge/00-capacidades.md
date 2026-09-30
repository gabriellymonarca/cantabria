---
document_id: doc-capacidades
title: O que o Cantábria faz - capacidades do copiloto
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que o Cantábria faz

O Cantábria é um copiloto de análise financeira: o usuário pergunta em linguagem natural sobre rentabilidade, carteira, contratos e clientes, e o sistema responde com números calculados por motores determinísticos a partir dos dados oficiais. O modelo de linguagem interpreta a pergunta e redige a explicação; nunca calcula, estima nem arredonda valores.

## Métricas disponíveis: rentabilidade, carteira, contratos, clientes e referências de mercado

As métricas de negócio são rentabilidade, carteira (saldo), quantidade de contratos e tamanho da base ativa: cada plano carrega uma métrica, e análises que cruzam métricas leem resultados verificados de mais de um plano, sem que o modelo faça a conta. Há também as séries macroeconômicas de referência (CDI, SELIC e IPCA), que só existem no total — sem recorte de segmento, produto ou cliente — e servem para comparar a rentabilidade com o mercado.

## Dimensões de recorte: segmento, produto, vinculação e principalidade

As análises podem ser abertas pelos níveis da segmentação de clientes: tipo de pessoa, grupo de segmento, segmento, grupo de subsegmento e subsegmento; por vinculação e principalidade; e por grupo de produto, produto e subproduto. As mesmas dimensões podem filtrar a população que entra na conta sem criar linhas, e existe o recorte total.

## Janelas de tempo e período padrão

As janelas disponíveis incluem a posição atual (snapshot), o último mês fechado, os últimos 3, 6 e 12 meses, o ano corrente e o ano anterior. A janela de histórico cobre setembro de 2024 a agosto de 2026. Sem período na pergunta, aplica-se o padrão declarado do catálogo (últimos 12 meses para séries e posição atual para snapshot), sempre ecoado como ressalva.

## Métodos estatísticos e operações disponíveis

Os métodos incluem valores sem tratamento (null), média, mediana, moda, desvio-padrão, dispersão completa, variação entre períodos, tendência, participação, correlação e detecção de outliers. As operações incluem ranking, comparação, participação acumulada, seleção, pivot e decomposição.

## Perguntas que você pode fazer

Exemplos de perguntas que o Cantábria responde: qual o segmento mais rentável nos últimos 12 meses? Como a carteira evoluiu no último ano? Qual a participação de cada produto no saldo? Quantos clientes ativos por segmento? A rentabilidade subiu em relação ao ano passado? Existe tendência de queda na rentabilidade de algum segmento?

## O que está fora de escopo

Não há previsão ou projeção de valores futuros, análise individual de clientes, produção/originação e fluxo, nem eleição de causa. Perguntas causais recebem os números verificados e a ressalva; pedidos de fluxo são recusados por escopo.

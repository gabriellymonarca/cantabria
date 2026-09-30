---
document_id: doc-janela-referencia
title: Janela de dados e data de referencia
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## Qual é a janela de histórico disponível

A janela de historico disponivel tem 24 meses, de 2024-09-01 a 2026-08-31, com o mes de referencia sempre no ultimo dia do mes. Perguntas fora dessa janela sao recusadas com o motivo fora da janela.

## O que é a data de referência

A data de referencia e o mes de referencia mais recente carregado (em producao vem do ClickHouse; nos exemplos, 2026-08-31). Ela ancora os rotulos de periodo: "ultimo mes", "ultimos 12 meses", "este ano" e a foto atual (snapshot) derivam dela por regra deterministica.

## Série, snapshot e grão total

Serie acompanha a evolucao mes a mes; snapshot e a foto na data de referencia. O grao total colapsa a janela inteira em um valor por grupo, recalculado a partir dos fatos, nunca pela media de taxas. Quando a pergunta nao traz periodo, aplica-se o padrao declarado do catalogo e o default e ecoado como ressalva.

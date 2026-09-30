---
document_id: doc-contratos
title: Como o banco conta contratos
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que é a contagem de contratos

A contagem de contratos é o número de contratos distintos ativos na data de referência que entram na análise. No catálogo, é a métrica contract_count, com unidade de contagem.

## Como a contagem de contratos é calculada

Contratos distintos são contados uma única vez, no ponto no tempo pedido. Em janelas longas, o resultado é a leitura na data final do período: um contrato ativo o período inteiro conta uma vez, nunca uma vez por mês, porque contagem é estoque e não se soma entre períodos.

## Contrato ativo na data de referência

Um contrato está ativo quando começou em data igual ou anterior à data de referência e não tem encerramento ou encerra em data igual ou posterior. As datas de início e fim existem para apurar a vigência do estoque; não são usadas para medir produção ou encerramento no período.

## O que a contagem de contratos não é

Não é produção, originação nem desembolso (isso é fluxo, fora de escopo) e não mistura contratos encerrados no período. Entre grupos, a contagem só pode ser somada quando cada contrato pertence a exatamente um grupo; entre períodos, nunca se soma.

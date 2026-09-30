---
document_id: doc-estoque-fluxo
title: Estoque versus fluxo
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que é estoque e o que o MVP modela

O MVP modela estoque: carteira (saldo em aberto), margem acumulada e contagens de contratos e clientes ativos na data de referencia. "Carteira", "saldo" e "estoque" sao sinonimos do mesmo saldo oficial.

## Fluxo fora de escopo: produção e originação

Producao e originacao de credito no mes, desembolsos, contratos encerrados no periodo e projecoes futuras sao fluxo: tem grato de evento e nao tem familia de calculo no contrato. Pedidos de fluxo sao recusados por escopo, nao tratados como erro de dados.

## Vigência de contrato e estoque

Um contrato e ativo na data quando comecou em data igual ou anterior e nao tem encerramento ou encerra em data igual ou posterior. As datas existem para a vigencia do estoque; medir originacao ou encerramento no periodo seria fluxo.

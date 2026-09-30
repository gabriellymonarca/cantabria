---
document_id: doc-carteira-saldo
title: Como o banco calcula carteira e saldo
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que é carteira, saldo ou estoque

Carteira, saldo e estoque são sinônimos do mesmo conceito oficial: o saldo em aberto dos contratos ativos na data de referência. No catálogo, esse conceito é a métrica outstanding_balance, com unidade monetária.

## Como o saldo da carteira é calculado

O saldo é a soma do saldo em aberto dos contratos ativos que entram na análise, na data ou no período pedido. O valor é lido dos dados oficiais; o Cantábria apenas aplica a agregação determinística aprovada e nunca recria, estima ou arredonda o valor de fonte.

## Carteira como estoque que não soma entre períodos

A carteira é um estoque: três meses de saldo não viram o triplo. Ao colapsar uma janela com grão total, aplica-se a regra declarada — valor do fim do período (padrão) ou média dos períodos —, sempre recalculada a partir dos fatos, nunca somando leituras mensais.

## O que carteira não é

Carteira não é produção, originação nem desembolso do período (isso é fluxo, fora de escopo), não é a soma dos saldos mensais e não é a contagem de contratos nem a quantidade de clientes. Carteira mede valor, não quantidade, e não se soma entre períodos em nenhuma hipótese.

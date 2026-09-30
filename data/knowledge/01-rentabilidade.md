---
document_id: doc-rentabilidade
title: Como o banco calcula rentabilidade
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que é rentabilidade e como ela é definida

Rentabilidade e a taxa anual que mede o retorno da carteira. A definicao oficial e uma razao ponderada pelo saldo elegivel: soma da margem dividida pela soma do saldo em aberto.

## Fórmula de rentabilidade e anualização

A margem oficial ja e anualizada em reais por ano. A formula e a soma da margem dividida pela soma do saldo. Nao ha multiplicacao por 12. A taxa sai diretamente como taxa anual em formato decimal.

## Como a rentabilidade é agregada entre períodos

A taxa de uma janela com varios meses e sempre re-derivada no grao pedido: soma das margens dos meses dividida pela soma dos saldos dos meses. A media simples das taxas mensais esta proibida porque pondera errado quando o saldo varia dentro do periodo.

## O que rentabilidade não é

Rentabilidade nao e media de taxas, nao e soma de taxas e nao e recalculada por contrato com spread hipotetico. O Cantabria nunca recria valor oficial de fonte: aplica apenas a agregacao deterministica aprovada sobre margem e saldo oficiais.

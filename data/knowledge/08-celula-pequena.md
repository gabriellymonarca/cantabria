---
document_id: doc-celula-pequena
title: Politica de celula pequena (k igual a 10)
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que é a regra k igual a 10

Celulas com menos de 10 clientes sao suprimidas: o valor volta nulo com o motivo de celula pequena, nunca zero. O limiar k igual a 10 protege contra reidentificacao em grupos raros.

## O que é supressão companheira

Celulas companheiras sao suprimidas junto para que a celula protegida nao possa ser recuperada por subtracao a partir do total. A ressalva de celula pequena e ecoada no insight sempre que houver supressao no resultado.

## Valores indefinidos e nulos com motivo

Valores que nao podem ser calculados (amostra insuficiente, variancia nula, pontos abaixo do minimo) voltam nulos com motivo explicito. Nulo com motivo nunca e confundido com desempenho zero.

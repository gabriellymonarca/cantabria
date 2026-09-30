---
document_id: doc-correlacao
title: O que é correlação de Pearson entre duas métricas
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que é correlação

Correlação mede a associação linear entre duas séries verificadas sobre as mesmas entidades. O coeficiente varia de menos um a um: perto de um as duas crescem juntas, perto de menos um caminham em sentidos opostos e perto de zero não há associação linear.

## Como a correlação de Pearson é calculada

O método correlation calcula o coeficiente de Pearson entre dois resultados colapsados, pareando as entidades presentes nos dois lados. Exige ao menos 3 pares com variação; com pares insuficientes ou variância nula, volta nulo com motivo, nunca zero.

## Correlação não é causalidade

Associação entre duas métricas não permite eleger causa. O Cantábria mostra o coeficiente verificado e não afirma que uma variável explica a outra; perguntas causais recebem o número e a ressalva de que correlação não é causalidade.

## O que a correlação exige

Os dois lados precisam compartilhar as mesmas entidades (mesmo recorte) e vir de resultados verificados, cada um produzido por um método. Populações de clientes diferentes não formam pares, e a correlação não consulta o banco de dados.

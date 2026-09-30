---
document_id: doc-dispersao
title: O que é dispersão, desvio-padrão e volatilidade
version: v1
status: approved
locale: pt-BR
approved_by: area-negocios-financas (ficticio)
---

## O que é dispersão de uma série

Dispersão mede o espalhamento dos valores de uma série em torno do centro. O método dispersion devolve o pacote completo: média, mediana, desvio-padrão, variância, mínimo, máximo, primeiro e terceiro quartis e o intervalo interquartil.

## O que é desvio-padrão (volatilidade)

O desvio-padrão é a raiz da variância amostral (n menos 1) e mede o quanto os valores oscilam em relação à média. Quanto maior o desvio, mais volátil a série; "volatilidade" é o nome comum do método std do catálogo.

## Como quartis e intervalo interquartil são calculados

Os quartis usam interpolação linear sobre a série ordenada. O intervalo interquartil (IQR) é o terceiro quartil menos o primeiro e concentra a metade central dos valores; é a base da cerca usada na detecção de outliers.

## Onde dispersão e média não se aplicam

Em rentabilidade, média e dispersão são proibidas: a média de taxas mensais não é a taxa da janela. A taxa do período inteiro sai de grão total com método null (valores verificados sem tratamento), re-derivada de margem sobre saldo. Séries curtas ou sem variação voltam nulas com motivo.

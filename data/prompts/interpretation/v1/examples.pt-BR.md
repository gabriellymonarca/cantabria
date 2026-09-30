# Exemplos (pt-BR)

Casos resolvidos que mostram o roteamento e a montagem esperados. Os ids vêm do
catálogo; a linguagem do usuário é só a superfície.

## 1. Recorte + ranking (analytical)

Pergunta: *"Qual produto é mais rentável entre clientes de alta principalidade em agosto/2026?"*

```json
{"route":"analytical","analysis":{"id":"plan_prod_high","statistical_method":[{"id":"s1","method":"mean","calculation_plan_ids":["calc_prof_prod_high"]}],"operations":[{"id":"o1","type":"ranking","refs":["s1"],"params":{"order":"desc","top_n":1,"axis":"entity"}}],"presentation":{"type":"ranking_bar","axis":"entity","title":"Produtos mais rentáveis"}},"calculations":[{"calculation_plan_id":"calc_prof_prod_high","metric":{"id":"m_prof_prod_high","rule_id":"profitability","subjects":[{"type":"product","level":"product"}],"sample":[{"type":"customer_principality","level":"principality_depth","value_id":"high"}]},"period":{"start":"2026-08-31","end":"2026-08-31","type":"snapshot","grain":"month"}}],"clarification_question":null,"refusal_reason":null,"refusal_message":null,"assumptions":[],"resolved_terms":[{"term":"produto","canonical":"product.product"},{"term":"alta principalidade","canonical":"customer_principality.principality_depth=high"}]}
```

## 2. Distribuição conjunta — dois subjects (analytical)

Pergunta: *"Como os produtos se distribuem entre os segmentos em agosto/2026?"*

```json
{"route":"analytical","analysis":{"id":"plan_dist_seg_prod","statistical_method":[{"id":"s1","method":"share","calculation_plan_ids":["calc_cnt_seg_prod"]}],"operations":[],"presentation":{"type":"table","axis":"entity","title":"Distribuição conjunta de contratos"}},"calculations":[{"calculation_plan_id":"calc_cnt_seg_prod","metric":{"id":"m_cnt_seg_prod","rule_id":"contract_count","subjects":[{"type":"customer_segmentation","level":"segment"},{"type":"product","level":"product"}]},"period":{"start":"2026-08-31","end":"2026-08-31","type":"snapshot","grain":"month"}}],"clarification_question":null,"refusal_reason":null,"refusal_message":null,"assumptions":[],"resolved_terms":[{"term":"produto","canonical":"product.product"}]}
```

## 3. Duas janelas — variation (analytical)

Pergunta: *"A rentabilidade total foi melhor em agosto/2026 que em agosto/2025?"*

```json
{"route":"analytical","analysis":{"id":"plan_yoy","statistical_method":[{"id":"s1","method":"variation","calculation_plan_ids":["calc_prof_2025_08","calc_prof_2026_08"]}],"operations":[],"presentation":{"type":"table","axis":"entity","title":"Variação da rentabilidade"}},"calculations":[{"calculation_plan_id":"calc_prof_2025_08","metric":{"rule_id":"profitability","subjects":[{"type":"total","level":"total"}]},"period":{"start":"2025-08-31","end":"2025-08-31","type":"snapshot","grain":"month"}},{"calculation_plan_id":"calc_prof_2026_08","metric":{"rule_id":"profitability","subjects":[{"type":"total","level":"total"}]},"period":{"start":"2026-08-31","end":"2026-08-31","type":"snapshot","grain":"month"}}],"clarification_question":null,"refusal_reason":null,"refusal_message":null,"assumptions":[],"resolved_terms":[{"term":"rentabilidade","canonical":"profitability"},{"term":"agosto/2025","canonical":"2025-08-31"},{"term":"agosto/2026","canonical":"2026-08-31"}]}
```

## 4. Contribuição para a variação — decomposition (analytical)

Pergunta: *"Quanto cada segmento contribuiu para a variação da rentabilidade total entre os 12 meses até ago/2026 e os 12 meses anteriores?"*

```json
{"route":"analytical","analysis":{"id":"plan_decomp","statistical_method":[{"id":"s1","method":"variation","calculation_plan_ids":["calc_prof_base","calc_prof_curr"]},{"id":"s2","method":"share","calculation_plan_ids":["calc_bal_base"]}],"operations":[{"id":"o1","type":"decomposition","refs":["s1","s2"]}],"presentation":{"type":"bar","axis":"entity","title":"Contribuição para a variação"}},"calculations":[{"calculation_plan_id":"calc_prof_base","metric":{"rule_id":"profitability","subjects":[{"type":"customer_segmentation","level":"segment"}]},"period":{"start":"2024-09-01","end":"2025-08-31","type":"series","grain":"month"}},{"calculation_plan_id":"calc_prof_curr","metric":{"rule_id":"profitability","subjects":[{"type":"customer_segmentation","level":"segment"}]},"period":{"start":"2025-09-01","end":"2026-08-31","type":"series","grain":"month"}},{"calculation_plan_id":"calc_bal_base","metric":{"rule_id":"outstanding_balance","subjects":[{"type":"customer_segmentation","level":"segment"}]},"period":{"start":"2024-09-01","end":"2025-08-31","type":"series","grain":"month"}}],"clarification_question":null,"refusal_reason":null,"refusal_message":null,"assumptions":["A carteira que pondera a contribuição é a da janela base, conforme a regra do catálogo."],"resolved_terms":[{"term":"rentabilidade","canonical":"profitability"},{"term":"segmento","canonical":"customer_segmentation.segment"}]}
```

## 5. Documental — sem plano (documental)

Pergunta: *"Como o banco calcula rentabilidade?"*

```json
{"route":"documental","analysis":null,"calculations":[],"clarification_question":null,"refusal_reason":null,"refusal_message":null,"assumptions":[],"resolved_terms":[{"term":"rentabilidade","canonical":"profitability"}]}
```

## 6. Recusa por governança (refuse)

Pergunta: *"Qual a rentabilidade do cliente João da Silva?"*

```json
{"route":"refuse","analysis":null,"calculations":[],"clarification_question":null,"refusal_reason":"governance","refusal_message":"Não é possível analisar por cliente individual: o sistema trabalha somente com dados agregados por segmento, produto e período.","assumptions":[],"resolved_terms":[]}
```

## 7. Recusa por termo fora do catálogo (refuse)

Pergunta: *"Qual a rentabilidade por agência?"*

```json
{"route":"refuse","analysis":null,"calculations":[],"clarification_question":null,"refusal_reason":"catalog_miss","refusal_message":"Não existe a dimensão \"agência\" no catálogo. As dimensões disponíveis são segmento, subsegmento, tipo de pessoa, principalidade, vinculação, grupo de produto, produto e subproduto.","assumptions":[],"resolved_terms":[]}
```

## 8. Recusa fora da janela (refuse)

Pergunta: *"Qual a rentabilidade de setembro/2023?"*

```json
{"route":"refuse","analysis":null,"calculations":[],"clarification_question":null,"refusal_reason":"out_of_window","refusal_message":"O histórico disponível vai de setembro/2024 a agosto/2026; setembro/2023 está fora desse intervalo.","assumptions":[],"resolved_terms":[]}
```

## 9. Recusa por escopo de estoque vs. fluxo (refuse)

Pergunta: *"Qual a produção de crédito do mês?"*

```json
{"route":"refuse","analysis":null,"calculations":[],"clarification_question":null,"refusal_reason":"out_of_scope","refusal_message":"Produção/originação é um fluxo, e o modelo atual trabalha com estoque (carteira e contratos ativos em uma data).","assumptions":[],"resolved_terms":[]}
```

## 10. Período ausente — aplica o default de série (analytical)

Pergunta: *"Qual segmento é o mais rentável?"*

```json
{"route":"analytical","analysis":{"id":"plan_seg_rent","statistical_method":[{"id":"s1","method":"mean","calculation_plan_ids":["calc_prof_seg"]}],"operations":[{"id":"o1","type":"ranking","refs":["s1"],"params":{"order":"desc","top_n":1,"axis":"entity"}}],"presentation":{"type":"ranking_bar","axis":"entity","title":"Segmentos mais rentáveis"}},"calculations":[{"calculation_plan_id":"calc_prof_seg","metric":{"rule_id":"profitability","subjects":[{"type":"customer_segmentation","level":"segment"}]},"period":{"start":"2025-09-01","end":"2026-08-31","type":"series","grain":"month"}}],"clarification_question":null,"refusal_reason":null,"refusal_message":null,"assumptions":["Sem período informado, usei a janela padrão de série: últimos 12 meses (2025-09-01 a 2026-08-31)."],"resolved_terms":[{"term":"rentável","canonical":"profitability"},{"term":"segmento","canonical":"customer_segmentation.segment"}]}
```

## 11. Pergunta pontual sem período — default snapshot (analytical)

Pergunta: *"Como está a base de clientes?"*

```json
{"route":"analytical","analysis":{"id":"plan_cust","statistical_method":[{"id":"s1","method":"null","calculation_plan_ids":["calc_cust_total"]}],"operations":[],"presentation":{"type":"table","axis":"entity","title":"Base de clientes"}},"calculations":[{"calculation_plan_id":"calc_cust_total","metric":{"rule_id":"customer_count","subjects":[{"type":"total","level":"total"}]},"period":{"start":"2026-08-31","end":"2026-08-31","type":"snapshot","grain":"month"}}],"clarification_question":null,"refusal_reason":null,"refusal_message":null,"assumptions":["Sem período informado, usei a posição atual (2026-08-31)."],"resolved_terms":[{"term":"base de clientes","canonical":"customer_count"}]}
```

## 12. Período ambíguo (clarify)

Pergunta: *"Rentabilidade do último trimestre"*

```json
{"route":"clarify","analysis":null,"calculations":[],"clarification_question":"Você quer o trimestre civil (jul–set/2026) ou os últimos 3 meses móveis até 31/08/2026?","refusal_reason":null,"refusal_message":null,"assumptions":[],"resolved_terms":[{"term":"rentabilidade","canonical":"profitability"}]}
```

## 13. Um número por entidade na janela — grão total (analytical)

Pergunta: *"Qual o produto mais rentável?"* (sem período)

O pedido é **um número por produto na janela**: default de série ecoado +
`grain: total` + `method: null` (a taxa da janela é recalculada pelo motor,
nunca a média das taxas mensais).

```json
{"route":"analytical","analysis":{"id":"plan_prod_rank","statistical_method":[{"id":"s1","method":"null","calculation_plan_ids":["calc_prof_prod"]}],"operations":[{"id":"o1","type":"ranking","refs":["s1"],"params":{"order":"desc","top_n":1,"axis":"entity"}}],"presentation":{"type":"ranking_bar","axis":"entity","title":"Produto mais rentável na janela"}},"calculations":[{"calculation_plan_id":"calc_prof_prod","metric":{"rule_id":"profitability","subjects":[{"type":"product","level":"product"}]},"period":{"start":"2025-09-01","end":"2026-08-31","type":"series","grain":"total"}}],"clarification_question":null,"refusal_reason":null,"refusal_message":null,"assumptions":["Sem período informado, usei a janela padrão de série (2025-09-01 a 2026-08-31) com grão total."],"resolved_terms":[{"term":"produto","canonical":"product.product"},{"term":"rentável","canonical":"profitability"}]}
```

## 14. Escopo geral do sistema (capability)

Pergunta: *"O que você faz?"*

A pergunta é sobre o próprio sistema, não pede número nem conceito de negócio:
a resposta é a descrição de capacidades gerada do catálogo, sem plano.

```json
{"route":"capability","analysis":null,"calculations":[],"clarification_question":null,"refusal_reason":null,"refusal_message":null,"assumptions":[],"resolved_terms":[]}
```

## 15. Escopo de uma dimensão (capability)

Pergunta: *"Quais informações posso perguntar sobre clientes?"*

Pergunta meta sobre o que existe no catálogo, não um pedido de número: `capability`.

```json
{"route":"capability","analysis":null,"calculations":[],"clarification_question":null,"refusal_reason":null,"refusal_message":null,"assumptions":[],"resolved_terms":[{"term":"clientes","canonical":"customer_count"}]}
```

## 16. Método disponível (capability)

Pergunta: *"Você tem regressão?"*

Pergunta sobre o que o sistema oferece (o método de tendência), não um cálculo
nem um documento: `capability`.

```json
{"route":"capability","analysis":null,"calculations":[],"clarification_question":null,"refusal_reason":null,"refusal_message":null,"assumptions":[],"resolved_terms":[{"term":"regressão","canonical":"trend"}]}
```

## 17. Formatos de saída (capability)

Pergunta: *"Que gráficos você faz?"*

Formato de saída é escopo do sistema: `capability`, sem listar ids de apresentação.

```json
{"route":"capability","analysis":null,"calculations":[],"clarification_question":null,"refusal_reason":null,"refusal_message":null,"assumptions":[],"resolved_terms":[]}
```

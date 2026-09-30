# Dados fictícios do Cantábria — estrutura e geração

> **Documento superado.** O formato vigente das bases e o guia do gerador estão
> em `data/base-ficticia.md` (7 tabelas: `fato_cliente`, `dim_segmento`,
> `dim_produto`, `fato_contratos`, `fato_contrato_produtos`,
> `fato_rentabilidade_cliente`, `fato_rentabilidade_contrato_produto`). Este
> documento fica como histórico da definição anterior de 4 tabelas.

Este diretório armazena, temporariamente e como referência para o agente de código, **como é a estrutura dos dados fictícios do Cantábria** e **como os scripts de geração desses dados devem ser construídos** (o agente de código os implementa depois).

> Status: definição fechada. Estrutura e regras decididas (§12); os números de geração são defaults ajustáveis após o primeiro dataset (§13). Pronto para o agente de código implementar os scripts.

---

## 1. Princípio norteador

O Cantábria **recebe números oficiais** produzidos pelas áreas de negócio. Ele **não recalcula nenhum número oficial** — apenas executa operações/análises determinísticas sobre esses números para entregar um **"so what" analítico**.

Consequência direta para a rentabilidade:

- A fonte entrega números **monetários duros** por contrato e por mês: **quanto o contrato rendeu (`vl_margem`, em R$)** e **qual o seu tamanho (`vl_saldo`, em R$)**. São inequívocos e aditivos.
- A **taxa de rentabilidade (%) é derivada**, não armazenada. Ela é o resultado analítico do Cantábria: `Σ vl_margem ÷ Σ vl_saldo`, agregada por segmento / produto / vinculação.
- Motivo: rentabilidade não se agrega por média simples de taxas — precisa ser ponderada pelo saldo. Guardar dinheiro (aditivo) e derivar a taxa é matematicamente limpo e fiel à base real.

Este desenho é consistente com o `definitions.md` ("Cantábria never recreates a source-owned authoritative value... it may only apply the approved deterministic downstream aggregation") e com a base real (que guarda margem + saldo e deriva taxa).

### 1.1 Os 4 UCs são exemplos de aceite, não o limite do sistema

O Cantábria é de **orquestração genérica**. Como diz o `definitions.md`, os casos de aceite "are not hard-coded intents and they do not define the complete set of questions Cantábria may answer".

Portanto, os dados fictícios **não são desenhados para os 4 UCs**, e sim para suportar a **combinação livre** de:

- **métricas** (`profitability`, `outstanding_balance`, `contract_count`, `customer_count`);
- **dimensões** (hierarquia de segmento, hierarquia de produto, vinculação, principalidade);
- **tipos de análise** (`dispersion`, `distribution`, `group_comparison`, `ranking`);
- **períodos** (qualquer recorte dentro da janela de 24 meses; mês, trimestre, ano);
- **filtros** (qualquer dimensão acima usada como recorte em vez de eixo).

Os 4 UCs são apenas **testes de aceite** dessa capacidade genérica. A estrutura das tabelas (contrato×mês + dimensões de cliente e produto) já cobre qualquer recorte; a geração deve garantir **cobertura e variabilidade** suficientes para que qualquer combinação válida produza um resultado significativo (não vazio, não degenerado).

---

## 2. Onde os dados vivem

Conforme o `architecture/flow.md` (referência arquitetural vigente):

| Store | Tecnologia | Conteúdo |
|---|---|---|
| **Dados oficiais** | **ClickHouse** | **é aqui que os fatos fictícios deste documento vão** (clientes, produtos, contratos, rentabilidade) |
| Conversation / Analysis / Calculation Store | MongoDB | conversas, planos e resultados |
| Value Object Store | MinIO | documentos oficiais (RAG) |
| Vector DB | Qdrant | embeddings dos documentos |

Deploy do ClickHouse: **Docker (self-hosted)** — sem limite prático de volume. Como o ClickHouse é colunar e comprime fortemente dimensões de baixa cardinalidade, todo o dataset fictício ocupa poucos MB.

> Observação: o `architecture.md` ainda descreve uma stack antiga (Postgres + Mongo) e está **desatualizado**. Correção pendente (não fazer agora).

---

## 3. Fontes de referência usadas para modelar

1. **`produtos_segmentos.xlsm`** (neste diretório) — hierarquias oficiais de produto e segmento:
   - aba `segmentos`: **13 combinações válidas** de `tp_pess + ds_segm_agrup + ds_segm + ds_subsegm_agrup + ds_subsegm`.
   - aba `produtos`: **29 combinações válidas** de `ds_grupo_prod + ds_produto + ds_subproduto`.
   - aba `matriz_seg_prod`: **allowlist** de quais produtos são permitidos para cada segmento.
2. **EDA da base real** (`notebooks/eda.ipynb`, tabela `bgi_fato_resultado` no Databricks) — usada como referência de plausibilidade. Achado central: a base real de resultado é um **cubo contábil de P&L mensal** (grão cliente × centro de custo × linha de balanço × mês), **sem contrato, sem produto e sem taxa**, guardando margem/saldo em R$. Ver §11 (divergências conscientes).

---

## 4. Modelo de dados fictício

Quatro tabelas em ClickHouse. Duas dimensões e dois fatos. Nomes de colunas seguem o padrão da base real (`id_`, `ds_`, `vl_`, `dt_`, `nr_`, `tp_`, `cd_`).

### 4.1 `dim_cliente`

Cadastro de clientes. Grão: **um cliente**.

| Coluna | Tipo | Origem / regra |
|---|---|---|
| `id_cliente` | String | gerado — `CLI_000001` |
| `nr_cpf_cnpj` | String | fictício via **Faker** (locale `pt_BR`): CPF quando `F`, CNPJ quando `J` |
| `nm_cliente` | String | fictício via Faker (nome p/ `F`, razão social p/ `J`) — cosmético |
| `ds_email` | String | fictício via Faker — cosmético |
| `nr_telefone` | String | fictício via Faker (`pt_BR`) — cosmético |
| `vl_renda` | Decimal | renda (F) / faturamento (J) fictício via Faker (`pt_BR`) — cosmético |
| `tp_pess` | String | `F` ou `J` (da aba `segmentos`) |
| `ds_segm_agrup` | String | hierarquia de segmento (uma das 13 combos válidas) |
| `ds_segm` | String | idem |
| `ds_subsegm_agrup` | String | idem |
| `ds_subsegm` | String | idem |
| `vinculacao` | String | dimensão governada — `baixa`/`media`/`alta`, fixo por cliente (§6) |
| `principalidade` | String | dimensão governada — `baixa`/`media`/`alta`, fixo por cliente (§6) |

- Volume: **~10.000 clientes**.
- A combinação de segmento **deve** ser uma das 13 válidas e coerente com `tp_pess` (F → segmentos PF/Rural PF/Private; J → PJ/Corporate/CIB/Rural PJ).
- Distribuição de clientes por `ds_segm` proporcional à base real (Varejo PF ~62%, Varejo PJ ~21%, Rural ~9%, Corporate ~5%, Private ~2%, CIB ~1%).

### 4.2 `dim_produto`

Catálogo de produtos. Grão: **um produto** (subproduto). Estático (as 29 linhas da aba `produtos`).

| Coluna | Tipo | Origem / regra |
|---|---|---|
| `id_produto` | String | gerado — `PROD_001` |
| `cd_produto` | String | gerado — `CRD0001` |
| `ds_grupo_prod` | String | aba `produtos` |
| `ds_produto` | String | aba `produtos` |
| `ds_subproduto` | String | aba `produtos` |

- Volume: **29 produtos**.

### 4.3 `fato_contrato`

Registro de contratos (a existência do vínculo cliente↔produto). Grão: **um contrato**.

| Coluna | Tipo | Origem / regra |
|---|---|---|
| `id_contrato` | String | gerado — `CTR_00000001` |
| `id_cliente` | String | FK → `dim_cliente` |
| `id_produto` | String | FK → `dim_produto` |
| `dt_inicio` | Date | data de abertura |
| `dt_fim` | Nullable(Date) | data de encerramento; `NULL` = ativo |

- **Nº de contratos por cliente** (default, sempre >= 1, limitado aos produtos permitidos ao segmento):
  - Varejo PF ~2 (1-3); Varejo PJ ~3 (1-5); Varejo Rural ~2 (1-3);
  - Corporate Middle ~4 (2-7); Corporate Large ~5 (2-9); Private ~4 (2-7); CIB ~6 (3-10).
  - produtos escolhidos sem repetição na allowlist do segmento, com pesos (§8). Estimativa total: ~25-30 mil contratos.
- **Governança:** um contrato só pode existir para um par (segmento do cliente × produto) **permitido pela `matriz_seg_prod`**.
- "Contrato ativo em uma data de referência" = `dt_inicio ≤ ref` E (`dt_fim` é NULL OU `dt_fim ≥ ref`). É isso que alimenta `contract_count` / distribuição de produto (UC2).
- `dt_inicio` distribuída ao longo/antes da janela de 24 meses; uma fração dos contratos encerra dentro da janela (para dar variação de contratos ativos ao longo do tempo).

### 4.4 `fato_rentabilidade`

Medidas mensais oficiais por contrato. Grão: **contrato × mês**.

| Coluna | Tipo | Origem / regra |
|---|---|---|
| `id_contrato` | String | FK → `fato_contrato` |
| `mes_ref` | Date | último dia do mês |
| `vl_saldo` | Decimal | saldo médio do contrato no mês (R$) — **oficial** |
| `vl_margem` | Decimal | margem do contrato **já em base anual** (R$) — **oficial** |

- Uma linha por contrato **por mês em que ele está ativo**. Volume: ~450–720 mil linhas.
- **Não há coluna de taxa.** A rentabilidade é derivada (§5).
- **`vl_margem` é armazenada já anualizada** (o quanto o contrato rende em 12 meses no ritmo daquele mês). Assim `vl_margem ÷ vl_saldo` já sai como **taxa anual**, sem conversão. Simplificação consciente (ver §11).
- Geração: para cada contrato/mês gera-se `vl_saldo` (com evolução/amortização mês a mês) e `vl_margem = vl_saldo × taxa_alvo_anual + ruído`. **A `taxa_alvo_anual` é uma variável latente do gerador** (usada só para produzir a margem); **apenas `vl_saldo` e `vl_margem` são persistidos**.

---

## 5. Métricas derivadas e mapeamento para as calculation families

Há **uma family por métrica**, nunca por dimensão: o eixo vem dos `subjects` do plano.

| Métrica / family | Definição (derivada) | Colunas | `unit` |
|---|---|---|---|
| `profitability` | `Σ vl_margem ÷ Σ vl_saldo`, ponderada pelo saldo. Já **anual**, pois `vl_margem` é anualizada | `fato_rentabilidade` | `decimal_rate` |
| `outstanding_balance` | `Σ vl_saldo` — a carteira, o estoque vivo na data | `fato_rentabilidade` | `currency` |
| `contract_count` | `id_contrato` distintos ativos na data | `fato_contrato` | `count` |
| `customer_count` | `id_cliente` distintos com contrato ativo na data | `fato_contrato` | `count` |

- **Sem passo de anualização:** como `vl_margem` já é anual, a taxa (mensal ou agregada por período) sai direto de `Σ vl_margem ÷ Σ vl_saldo`. Não há `×12`.
- **A divisão é sempre a última operação.** Somar `vl_margem` e `vl_saldo` em todos os eixos — entre contratos **e** entre meses — e dividir uma vez só. Com grain trimestral/anual, re-derivar no grão: `Σmargem(n meses) ÷ Σsaldo(n meses)`, **nunca** a média das taxas mensais. Os dois só coincidem se o saldo for constante.
- **`outstanding_balance` não soma entre meses.** É estoque: R$ 200 de carteira parados por 3 meses continuam R$ 200, não viram R$ 600. As contagens também não somam no tempo — são foto numa data.
- **Fluxo está fora de escopo.** Produção/originação, produção líquida e encerramentos no período não têm family: o modelo é de estoque. `dt_fim` existe no dado, mas contar encerramentos seria fluxo.
- A distribuição de produto por segmento (UC2) é `contract_count` com **dois subjects** (segmento + produto), produzindo a distribuição conjunta — não uma family dedicada.

---

## 6. Vinculação e principalidade

- **Categórica ordinal** de 3 níveis para ambos: `baixa | media | alta` (value_ids canônicos `low | medium | high`). Sem score numérico — mantido simples de propósito.
- **Fixos por cliente** (colunas em `dim_cliente`). Simplificação consciente do MVP.
- São **dimensões governadas como qualquer outra** (`customer_relationship.relationship_depth` e `customer_principality.principality_depth`), e servem tanto de **eixo** ("rentabilidade por vinculação") quanto de **filtro** ("produto mais rentável entre alta principalidade"). O catálogo de filtros é o catálogo de eixos: não são uma categoria especial de campo.
- No mundo real essas classificações são "resolvidas historicamente por mês" (ver `definitions.md`). No MVP, a resolução histórica é um no-op (lê o valor fixo). Costura para o futuro: promover a uma tabela `cliente × mês` sem mudar os contratos das families.

---

## 7. Governança seg×produto

Todo contrato nasce apenas em combinações **segmento × produto** presentes na `matriz_seg_prod` do `.xlsm`. Isso reaproveita a allowlist oficial e evita produtos incompatíveis com um segmento.

---

## 8. Realismo e coerência interna (para qualquer análise ser significativa)

O objetivo **não** é "fazer os 4 UCs terem resposta", e sim gerar um dataset que **se comporte como um banco real**, de modo que **qualquer** recorte analítico válido (§1.1) produza um resultado explicável — não ruído puro nem células vazias. Para isso, a geração deve garantir **cobertura** (linhas suficientes por célula segmento × produto × mês × nível de relacionamento), **variabilidade** (dispersão dentro e entre grupos) e **ruído** (sem valores idênticos artificiais).

Tendências realistas a embutir (correlações plausíveis, **não** vieses para um UC específico):

- taxa-alvo maior em Varejo e menor em Corporate/CIB/Private (que têm saldos muito maiores);
- principalidade/vinculação mais altas somam um incremento na taxa-alvo (ver abaixo);
- mix de produto distinto por segmento (pesos de amostragem, respeitando a allowlist).

Ordens de grandeza (defaults):

- **Saldo por segmento (R$):** Varejo PF 1k-150k; Varejo PJ 10k-2M; Rural 5k-500k; Corporate Middle 500k-20M; Corporate Large 5M-100M; Private 500k-30M; CIB 10M-1B.
- **Taxa-alvo por grupo de produto:** Rotativo 15-35%; Parcelado 8-20%; Consignado 5-12%; com Garantia 2-8%; Especializado/Transacional/Renegociação intermediárias.
- **Incremento por vinculação/principalidade (p.p. na taxa-alvo):** principalidade baixa +0 / media +1,5 / alta +3; vinculação baixa +0 / media +1 / alta +2.
- **Distribuição de vinculação/principalidade por cliente:** default baixa 40% / media 40% / alta 20%, com leve viés dos segmentos premium (Private/Corporate/CIB) para media/alta.
- **Evolução do saldo:** cada contrato tem um saldo-base (faixa do segmento) que varia mês a mês por um random walk suave (amortização/uso), sempre positivo.
- **Ruído:** taxa-alvo recebe ruído gaussiano (~±15% relativo) por contrato/mês antes de virar `vl_margem = vl_saldo × taxa`.

---

## 9. Parâmetros de geração dos scripts

- **Seed fixa** (reprodutibilidade determinística).
- **Janela temporal:** 24 meses, de `2024-09-30` a `2026-08-31` (fins de mês), ancorada em `2026-08` para casar com os exemplos do `definitions.md`/`flow.md`.
- **Esquemas de id:** `CLI_000001`, `PROD_001`, `CRD0001`, `CTR_00000001`; `mes_ref` como `Date` (último dia do mês).
- **PII fictícia:** gerar `nr_cpf_cnpj`, `nm_cliente`, `ds_email`, `nr_telefone`, `vl_renda` com **Faker** (`pt_BR`). PF usa renda; PJ usa faturamento.
- **Nomenclatura:** manter o padrão da base real (`id_`, `ds_`, `vl_`, `dt_`, `nr_`, `tp_`, `cd_`).
- **Destino:** gravar **direto no ClickHouse** — o gerador aplica o **DDL** (`CREATE TABLE ... ENGINE = MergeTree`) e **insere** via client (ex.: `clickhouse-connect`), de forma **determinística e idempotente** (recria + insere). Exportar Parquet é **opcional** (inspeção/portabilidade).
- **Organização:** scripts de geração em **`utils/`** (raiz, fora de `src/`); export opcional em `data/`.

---

## 10. Rastreabilidade dos UCs → tabelas

| UC | Tabelas usadas | Como |
|---|---|---|
| UC1 dispersão de rentabilidade por segmento | `fato_rentabilidade` + `fato_contrato` + `dim_cliente` | soma margem/saldo por segmento do cliente → deriva taxa → dispersão |
| UC2 distribuição de produto por segmento | `fato_contrato` + `dim_cliente` (+ `dim_produto`) | conta contratos ativos por produto × segmento |
| UC3 rentabilidade por vinculação | `fato_rentabilidade` + `fato_contrato` + `dim_cliente` | agrupa pela vinculação (fixa) do cliente |
| UC4 rentabilidade de produto entre alta principalidade | `fato_rentabilidade` + `fato_contrato` + `dim_cliente` + `dim_produto` | filtra principalidade=alta → agrupa por produto |

---

## 11. Divergências conscientes vs. base real

| Aspecto | Base real (`bgi_fato_resultado`) | Modelo fictício | Justificativa |
|---|---|---|---|
| Grão | cliente × centro de custo × linha de balanço × mês | contrato × mês | UC4 exige rentabilidade por produto; `definitions.md` reconhece "contract-level Profitability" como source-owned |
| Contrato | não existe | existe (`fato_contrato`) | necessário p/ `contract_count` e distribuição de produto |
| Produto | não existe (linha de balanço é o mais próximo) | dimensão explícita | necessário p/ UC2/UC4 |
| Taxa | não existe (derivada) | não existe (derivada) | **igual** — fiel ao real |
| Medidas monetárias | margem + saldo (R$) | margem + saldo (R$) | **igual** — fiel ao real |
| Base da margem | margem mensal (R$ do mês) | margem **anualizada** (R$/ano) | simplificação: taxa sai anual sem `×12` |

---

## 12. Decisões travadas (resumo)

- Escopo: capacidade genérica (métricas × dimensões × análises × períodos × filtros); os 4 UCs são testes de aceite.
- Fatos moram no ClickHouse (Docker); volume irrelevante.
- 10.000 clientes; 24 meses de histórico (2024-09 a 2026-08).
- Fonte entrega `vl_margem` (anualizada) + `vl_saldo` por contrato×mês; taxa é derivada, já anual.
- Grão contrato × mês; duas tabelas (`fato_contrato` + `fato_rentabilidade`).
- Vinculação/principalidade **categóricas** (`baixa/media/alta`), fixas por cliente em `dim_cliente`.
- Contratos respeitam a allowlist `matriz_seg_prod`.
- **PII fictícia:** gerar `nr_cpf_cnpj`, `nm_cliente`, `ds_email`, `nr_telefone`, `vl_renda` com **Faker** (`pt_BR`). PF usa renda; PJ usa faturamento.
- Dados gravados **direto no ClickHouse** (DDL + insert idempotente); Parquet só como export opcional.
- Scripts de geração em `utils/` (fora de `src/`).

---

## 13. Itens de afinação (defaults adotados)

Sem mais decisões estruturais pendentes. Os números abaixo são **defaults** e podem ser recalibrados após inspecionar o primeiro dataset gerado:

1. Magnitudes da §8 (faixas de saldo por segmento, taxa-alvo por grupo de produto, incrementos de vinculação/principalidade).
2. Distribuição de nº de contratos por cliente/segmento (§4.3).
3. Distribuição dos valores de vinculação/principalidade por cliente (§8).

Calibração fina exigiria outra base de referência (a base real de resultado não tem produto nem contrato); por ora, seguimos com os defaults.

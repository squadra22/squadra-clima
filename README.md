# squadra-clima

Coleta diária automática (GitHub Actions) que alimenta o **Relatório Diário · Clima & Hidrologia** da Squadra Energia.

## O que é coletado (todo dia, ~06:40 BRT)

| Bloco | Fonte | Saída |
|---|---|---|
| Previsão de chuva por bacia (rodada 00z) | GFS 0,25° e GEFS média (NOAA/NOMADS), ECMWF IFS, ECMWF ENS (51 membros) e ECMWF AIFS (ECMWF Open Data) | `data/previsoes/<rodada>_<modelo>.json` |
| Chuva observada por bacia | MERGE/CPTEC (reserva: CPC Unified Gauge/NOAA) | `data/observado/<dia>.json` |
| Realizado D-1 x previsto | observado do último dia x rodada 00z do dia anterior (lead 12–36h) | `latest.json → verificacao_d1` |
| Acumulado do mês e % da climatologia | soma do observado + `data/climatologia_bacias.csv` | `latest.json → acumulado_mes` |
| EAR, ENA e carga | ONS – Dados Abertos | `latest.json → ear / ena / carga` |
| PLD horário (média diária) | CCEE – Dados Abertos | `latest.json → pld` |
| ENOS (Niño 1+2, 3, 3.4, 4) | NOAA CPC (semanal, base 1991-2020) | `latest.json → enso` |

Consolidado: `data/latest.json` (máquina) e `data/latest.md` (leitura rápida). Log da última execução: `data/ultimo_log.txt`.

## Convenções
- Janelas diárias 12Z→12Z, rotuladas pela data final (mesma convenção do MERGE).
- Semana 1 = dias 1–7; semana 2 = dias 8–14 a partir da rodada 00z.
- Bacias: contornos **aproximados** (`clima/bacias.py`). Para usar contornos oficiais, grave `data/bacias.geojson` (properties.nome igual aos nomes das bacias).
- Climatologia mensal: preencher `data/climatologia_bacias.csv` (out e nov já preenchidos).

## Rodar manualmente
GitHub → **Actions** → *Coleta diária de clima* → **Run workflow** (opcionalmente com uma data).

"""Monta o esqueleto do conteúdo do relatório a partir de data/latest.json.

Uso: python -m relatorio.base data/latest.json base.json

Todas as TABELAS e números vêm direto da coleta (sem transcrição manual). O texto
interpretativo — manchete, bullets marcados com [PREENCHER], leitura para o
trading, PLD da CCEE e fontes extras — é completado depois, pela pesquisa do dia.
"""
import datetime as dt
import json
import sys

import os

from clima.bacias import GRUPOS, REGIOES
from . import graficos

DIAS = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
MODS = [("gfs", "GFS"), ("gefs", "GEFS"), ("ecmwf", "ECMWF"), ("aifs", "AIFS")]


def n(v, casas=0, sinal=False):
    if v is None:
        return "n/d"
    if sinal and abs(v) < 0.5 * 10 ** -casas:
        v, sinal = 0.0, False
    s = f"{v:+.{casas}f}" if sinal else f"{v:.{casas}f}"
    return s.replace(".", ",")


def br(data_iso):
    return dt.date.fromisoformat(data_iso).strftime("%d/%m") if data_iso else "n/d"


def rodada_txt(r):
    return f"{r[6:8]}/{r[4:6]} {r[8:10]}z" if r else "n/d"


def sec_enos(L):
    e = L.get("enso")
    if not e:
        return {"titulo": "ENOS e grande escala", "bullets": ["[PREENCHER: estado do ENOS — CPC indisponível na coleta]"]}
    return {"titulo": "ENOS e grande escala", "bullets": [
        f"Anomalias semanais de TSM do CPC/NOAA (semana de {e['semana']}, base 1991-2020): "
        f"Niño 1+2 em **{n(e['nino12'], 1, True)} °C**, Niño 3 em **{n(e['nino3'], 1, True)} °C**, "
        f"Niño 3.4 em **{n(e['nino34'], 1, True)} °C** ({n(e['var_nino34'], 1, True)} na semana) e "
        f"Niño 4 em **{n(e['nino4'], 1, True)} °C**. São anomalias absolutas; o índice relativo (RONI) "
        "costuma ficar perto de 1 °C abaixo.",
        "[PREENCHER: projeções (C3S/CPC/BoM) e mudanças relevantes, 1–2 bullets]",
    ]}


def sec_verificacao(L):
    v = L.get("verificacao_d1")
    acum = (L.get("acumulado_mes") or {}).get("bacias", {})
    if not v:
        return {"titulo": "Chuva realizada D-1 x prevista",
                "paragrafos": ["Verificação indisponível nesta coleta."]}
    linhas = []
    for grupo, bacias in GRUPOS.items():
        linhas.append([grupo])
        for b in bacias:
            r = v["bacias"].get(b, {})
            a = acum.get(b, {})
            pct = a.get("pct_clima")
            linhas.append([b, n(r.get("obs"), 1)] + [n(r.get(k), 1) for k, _ in MODS] +
                          [n(r.get("desvio"), 1, True) if r.get("desvio") is not None else "n/d",
                           f"{n(pct)}%" if pct is not None else "n/d"])
    erro = v.get("erro_por_modelo", {})
    ranking = sorted(erro.items(), key=lambda kv: kv[1]["erro_abs_medio"])
    nota_erro = "; ".join(f"{dict(MODS).get(k, k)} {n(x['erro_abs_medio'], 1)} mm (viés {n(x['vies_medio'], 1, True)})"
                          for k, x in ranking)
    acum_ate = (L.get("acumulado_mes") or {}).get("ate")
    return {"titulo": "Chuva realizada D-1 x prevista", "tabela": {
        "colunas": ["Bacia", "Realizado", "GFS", "GEFS", "ECMWF", "AIFS", "Desvio", "Mês % clima"],
        "larguras": [2.3, 1, 0.9, 0.9, 0.9, 0.9, 0.9, 1.1],
        "linhas": linhas,
        "nota": (f"Chuva em mm, média na bacia, janela 12Z de {br((dt.date.fromisoformat(v['dia']) - dt.timedelta(days=1)).isoformat())} "
                 f"a 12Z de {br(v['dia'])}. Realizado: {v['fonte_obs']}. Previsto: rodada {rodada_txt(v['rodada_prevista'])} "
                 f"(antecedência de 12 a 36h). Desvio = realizado − média dos modelos. Mês % clima: acumulado até "
                 f"{br(acum_ate)} sobre a climatologia mensal. Erro absoluto médio por bacia: {nota_erro or 'n/d'}.")},
        "bullets": ["[PREENCHER: 1–2 bullets — qual modelo errou mais, onde e para que lado; o que isso sugere para a leitura dos modelos hoje]"]}


def _tab_semana(P, sem, titulo):
    cols = ["Região"]
    ordem = [k for k in ("gfs", "gefs", "ecmwf", "ecmwf_ens", "aifs") if k in P]
    nomes = {"gfs": "GFS", "gefs": "GEFS (média)", "ecmwf": "ECMWF IFS", "ecmwf_ens": "ECMWF ENS (p10–p90)", "aifs": "AIFS"}
    cols += [nomes[k] for k in ordem]
    linhas = []
    for reg in REGIOES:
        row = [reg]
        for k in ordem:
            v = P[k].get(sem, {}).get(reg)
            if k == "ecmwf_ens" and v is not None:
                lo, hi = P[k].get(sem + "_p10", {}).get(reg), P[k].get(sem + "_p90", {}).get(reg)
                row.append(f"{n(v)} ({n(lo)}–{n(hi)})")
            elif k == "ecmwf" and sem == "semana2" and v is None:
                row.append("—")
            else:
                row.append(n(v))
        linhas.append(row)
    larg = [2.6] + [1.6 if k == "ecmwf_ens" else 1 for k in ordem]
    return {"titulo": titulo, "colunas": cols, "linhas": linhas, "larguras": larg}


def sec_modelos(L):
    P = L.get("previsoes") or {}
    if not P:
        return {"titulo": "Comparação de modelos: próximos 15 dias", "paragrafos": ["Previsões indisponíveis nesta coleta."]}
    rod = "; ".join(f"{v['modelo']} {rodada_txt(v['rodada'])}" for v in P.values())
    membros = P.get("ecmwf_ens", {}).get("membros")
    t1 = _tab_semana(P, "semana1", "Semana 1 (dias 1–7), chuva acumulada em mm")
    t2 = _tab_semana(P, "semana2", "Semana 2 (dias 8–14), chuva acumulada em mm")
    t2["nota"] = (f"Rodadas: {rod}. Média areal por bacia e média simples das bacias de cada região. "
                  f"ECMWF ENS: média de {membros or 'n/d'} membros, entre parênteses o intervalo p10–p90. "
                  "O ECMWF IFS determinístico vai até 10 dias, então não tem semana 2.")
    return {"titulo": "Comparação de modelos: próximos 15 dias", "tabelas": [t1, t2],
            "bullets": ["[PREENCHER: onde os modelos convergem e divergem; dispersão do ENS; vieses conhecidos (marcar como interpretação)]"]}


def sec_curto_prazo():
    return {"titulo": "Previsão consolidada: curto prazo",
            "bullets": ["[PREENCHER: 3–5 bullets por janela — frentes, ZCAS, calor/frio, eólica NE e Sul — a partir dos boletins do dia]"]}


def sec_hidro(L):
    ena, ear = L.get("ena") or {}, L.get("ear") or {}
    linhas = []
    for s in ("SE/CO", "Sul", "Nordeste", "Norte"):
        e, a = ena.get(s, {}), ear.get(s, {})
        linhas.append([s, n(e.get("pct_mlt_mes")) + "%" if e else "n/d", n(e.get("pct_mlt")) + "%" if e else "n/d",
                       n(a.get("pct"), 1) + "%" if a else "n/d",
                       n(a.get("var_7d"), 1, True) if a.get("var_7d") is not None else "n/d"])
    d_ena = next(iter(ena.values()), {}).get("data")
    d_ear = next(iter(ear.values()), {}).get("data")
    return {"titulo": "Hidrologia e armazenamento", "tabela": {
        "colunas": ["Subsistema", "ENA no mês (% MLT)", "ENA do dia (% MLT)", "EAR (%)", "EAR 7 dias (p.p.)"],
        "larguras": [1.4, 1.3, 1.3, 1, 1.2], "linhas": linhas,
        "nota": f"Fonte: ONS, Dados Abertos (ENA bruta até {br(d_ena)}; EAR até {br(d_ear)})."},
        "bullets": ["[PREENCHER: leitura — chuva em cabeceiras com reservatório x fio d'água; tendência do EAR]"]}


def sec_preco(L):
    b = []
    cmo = L.get("cmo")
    if cmo:
        partes = ", ".join(f"{s} R$ {n(x['media'], 2)}" for s, x in cmo["submercados"].items())
        b.append(f"**CMO do ONS em {br(cmo['data'])}** (média do dia, R$/MWh): {partes}.")
    carga = L.get("carga")
    if carga:
        partes = ", ".join(f"{s} {n(x['mwmed'])}" for s, x in carga.items())
        d = next(iter(carga.values()))["data"]
        b.append(f"**Carga verificada em {br(d)}** (MWmed): {partes}.")
    b.append("[PREENCHER: PLD da CCEE por submercado e spreads SE x S, SE x NE, SE x N, pela pesquisa do dia; temperatura nos centros de carga]")
    return {"titulo": "Preço e carga", "bullets": b}


def sec_eolica(L, pasta):
    E = L.get("eolica") or {}
    imgs, linhas = [], []
    f1 = graficos.eolica_realizada(E, os.path.join(pasta, "eolica_realizada.png")) if E else None
    if f1:
        imgs.append({"caminho": f1, "legenda": f"Geração eólica verificada por hora, ONS (balanço de energia), até "
                     f"{E['ate'][8:10]}/{E['ate'][5:7]} {E['ate'][11:16]}. A linha tracejada é a média dos últimos 30 dias."})
    # tabela: geração média dos últimos 7 dias x média de 30 dias
    if E.get("diario"):
        todos = sorted(E["diario"])
        if E.get("ate", "")[11:13] not in ("23", "") and len(todos) > 1:
            todos = todos[:-1]  # último dia ainda incompleto
        dias = todos[-7:]
        for sub in ("Nordeste", "Sul"):
            vals = [E["diario"][d].get(sub) for d in dias if E["diario"][d].get(sub) is not None]
            m7 = sum(vals) / len(vals) if vals else None
            m30 = (E.get("media_30d") or {}).get(sub)
            ult = E["diario"][dias[-1]].get(sub) if dias else None
            var = (100 * (m7 / m30 - 1)) if (m7 and m30) else None
            linhas.append([sub, n(ult), n(m7), n(m30), n(var, 0, True) + "%" if var is not None else "n/d"])
    tabelas = []
    if linhas:
        tabelas.append({"titulo": "Geração eólica verificada (MWmed)",
                        "colunas": ["Subsistema", "Último dia completo", "Média 7 dias", "Média 30 dias", "7d x 30d"],
                        "larguras": [1.4, 1.3, 1.2, 1.2, 1], "linhas": linhas})
    if not imgs and not tabelas:
        return {"titulo": "Eólica: geração verificada", "paragrafos": ["Dados de eólica indisponíveis nesta coleta."]}
    return {"titulo": "Eólica: geração verificada", "imagens": imgs, "tabelas": tabelas,
            "bullets": ["[PREENCHER: leitura da eólica — desempenho recente x média de 30 dias no NE e no Sul, perspectiva dos boletins para os próximos dias e efeito no PLD/spreads]"]}


def kpis(L):
    e = L.get("enso") or {}
    ena = (L.get("ena") or {}).get("SE/CO", {})
    ear = (L.get("ear") or {}).get("SE/CO", {})
    cmo = (L.get("cmo") or {}).get("submercados", {})
    k = [
        {"rotulo": "Niño 3.4 (CPC, semana)", "valor": f"{n(e.get('nino34'), 1, True)} °C",
         "nota": f"{n(e.get('var_nino34'), 1, True)} na semana", "tom": "alerta"},
        {"rotulo": "ENA SE/CO no mês", "valor": f"{n(ena.get('pct_mlt_mes'))}% MLT",
         "nota": f"Dia {br(ena.get('data'))}: {n(ena.get('pct_mlt'))}% MLT", "tom": "positivo"},
        {"rotulo": "EAR SE/CO", "valor": f"{n(ear.get('pct'), 1)}%",
         "nota": f"{n(ear.get('var_7d'), 1, True)} p.p. em 7 dias", "tom": "neutro"},
        {"rotulo": "CMO SE/CO · Norte", "valor": f"R$ {n(cmo.get('SE/CO', {}).get('media'))}",
         "nota": f"Norte R$ {n(cmo.get('Norte', {}).get('media'))} · NE R$ {n(cmo.get('Nordeste', {}).get('media'))}",
         "tom": "neutro"},
    ]
    return k


def montar(L, pasta="."):
    hoje = dt.date.fromisoformat(L["data_ref"])
    return {
        "data": hoje.strftime("%d/%m/%Y"), "dia_semana": DIAS[hoje.weekday()], "edicao": "",
        "manchete": "[PREENCHER: 1–3 frases — o que mudou desde ontem e por que importa]",
        "kpis": kpis(L),
        "secoes": [sec_enos(L), sec_verificacao(L), sec_modelos(L), sec_curto_prazo(), sec_eolica(L, pasta), sec_hidro(L), sec_preco(L)],
        "leitura_trading": ["[PREENCHER: 3–5 itens por submercado; diferenciar fato de interpretação]"],
        "fontes": [
            {"titulo": "Coleta squadra-clima: GFS/GEFS (NOAA), ECMWF IFS/ENS/AIFS (ECMWF Open Data, CC BY 4.0), "
                       "MERGE/CPTEC, ONS Dados Abertos, NOAA CPC", "url": ""},
        ],
    }


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as fh:
        L = json.load(fh)
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(montar(L, os.path.dirname(os.path.abspath(sys.argv[2]))), fh, ensure_ascii=False, indent=1)
    print("ok:", sys.argv[2])

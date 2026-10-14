"""Coleta diária: modelos, chuva observada, verificação D-1, ONS, CCEE e ENOS.

Uso: python -m clima.run [--data AAAA-MM-DD] [--so modelos,observado,setor]
Saídas:
  data/previsoes/<rodada>_<modelo>.json   arquivo de cada rodada (para verificação futura)
  data/observado/<dia>.json               chuva observada por bacia (janela 12Z→12Z)
  data/latest.json                        consolidado consumido pelo relatório diário
  data/latest.md                          resumo legível
"""
import argparse
import csv
import datetime as dt
import json
import os
import tempfile
import traceback

from . import bacias as B
from .modelos import MODELOS
from .observado import observado, dias_para_coletar
from . import setor
from .vento import VENTO

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(RAIZ, "data")
P_PREV = os.path.join(DATA, "previsoes")
P_OBS = os.path.join(DATA, "observado")


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def _r(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def climatologia():
    """mm/mês por bacia (data/climatologia_bacias.csv: bacia;jan;...;dez)."""
    out = {}
    p = os.path.join(DATA, "climatologia_bacias.csv")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                out[row["bacia"]] = {k: float(v) for k, v in row.items() if k != "bacia" and v}
    return out


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def acumulado_mes(hoje):
    """Soma do observado no mês corrente (janelas que terminam entre dia 1 e hoje)."""
    soma, dias = {}, []
    for f in sorted(os.listdir(P_OBS)) if os.path.isdir(P_OBS) else []:
        d = dt.date.fromisoformat(f[:10])
        if d.year == hoje.year and d.month == hoje.month and d <= hoje:
            o = _r(os.path.join(P_OBS, f))
            dias.append(d.isoformat())
            for b, v in o["bacias"].items():
                if v is not None:
                    soma[b] = soma.get(b, 0) + v
    clim = climatologia()
    mes = MESES[hoje.month - 1]
    out = {}
    for b, v in soma.items():
        c = clim.get(b, {}).get(mes)
        out[b] = {"mm": round(v, 1), "clima_mes": c, "pct_clima": round(100 * v / c, 0) if c else None}
    return {"dias": len(dias), "ate": max(dias) if dias else None, "bacias": out}


def verificacao(dia_obs):
    """Compara o observado do dia com a previsão da rodada 00z do dia anterior (lead 12–36h)."""
    obs_f = os.path.join(P_OBS, f"{dia_obs.isoformat()}.json")
    if not os.path.exists(obs_f):
        return None
    obs = _r(obs_f)
    rodada = (dia_obs - dt.timedelta(days=1)).strftime("%Y%m%d") + "00"
    prev = {}
    for chave in ("gfs", "gefs", "ecmwf", "aifs"):
        f = os.path.join(P_PREV, f"{rodada}_{chave}.json")
        if os.path.exists(f):
            prev[chave] = _r(f).get("diario", {}).get(dia_obs.isoformat(), {})
    linhas = {}
    for b in B.ordem_bacias():
        o = obs["bacias"].get(b)
        p = {k: v.get(b) for k, v in prev.items()}
        vals = [x for x in p.values() if x is not None]
        media = round(sum(vals) / len(vals), 1) if vals else None
        linhas[b] = {"obs": o, **p, "media_modelos": media,
                     "desvio": round(o - media, 1) if (o is not None and media is not None) else None}
    erro = {}
    for k in prev:
        pares = [(linhas[b]["obs"], linhas[b][k]) for b in linhas
                 if linhas[b]["obs"] is not None and linhas[b].get(k) is not None]
        if pares:
            erro[k] = {"vies_medio": round(sum(p - o for o, p in pares) / len(pares), 1),
                       "erro_abs_medio": round(sum(abs(p - o) for o, p in pares) / len(pares), 1)}
    return {"dia": dia_obs.isoformat(), "fonte_obs": obs["fonte"], "rodada_prevista": rodada,
            "bacias": linhas, "erro_por_modelo": erro}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="data de referência (AAAA-MM-DD, padrão: hoje UTC)")
    ap.add_argument("--so", default="modelos,observado,setor")
    a = ap.parse_args()
    hoje = dt.date.fromisoformat(a.data) if a.data else dt.datetime.utcnow().date()
    etapas = set(a.so.split(","))
    masc = B.Mascaras(B.carregar_poligonos(RAIZ))
    status = {}
    latest_p = os.path.join(DATA, "latest.json")
    latest = _r(latest_p) if os.path.exists(latest_p) else {}
    latest.update({"gerado_em_utc": dt.datetime.utcnow().isoformat(timespec="minutes"),
                   "data_ref": hoje.isoformat()})

    with tempfile.TemporaryDirectory() as tmp:
        if "modelos" in etapas:
            prev = {}
            for chave, func in MODELOS.items():
                try:
                    res = func(tmp, masc, hoje)
                    _w(os.path.join(P_PREV, f"{res['rodada']}_{chave}.json"), res)
                    prev[chave] = res
                    status[chave] = f"ok (rodada {res['rodada']})"
                except Exception as e:  # noqa
                    status[chave] = f"erro: {e}"
                    traceback.print_exc()
            # garante o arquivo da rodada de ontem (necessário para a verificação D-1)
            for ontem in (hoje - dt.timedelta(days=1), hoje - dt.timedelta(days=2)):
              for chave in ("gfs", "gefs", "ecmwf", "aifs"):
                alvo = os.path.join(P_PREV, f"{ontem.strftime('%Y%m%d')}00_{chave}.json")
                if not os.path.exists(alvo):
                    try:
                        res = MODELOS[chave](tmp, masc, ontem)
                        if res["rodada"].startswith(ontem.strftime("%Y%m%d")):
                            _w(alvo, res)
                    except Exception:  # noqa
                        traceback.print_exc()
            latest["previsoes"] = {
                k: {"modelo": v["modelo"], "rodada": v["rodada"],
                    "semana1": B.agregar_regioes(v.get("semana1", {})),
                    "semana2": B.agregar_regioes(v.get("semana2", {})),
                    **({"semana1_p10": B.agregar_regioes(v["semana1_p10"]),
                        "semana1_p90": B.agregar_regioes(v["semana1_p90"]),
                        "semana2_p10": B.agregar_regioes(v["semana2_p10"]),
                        "semana2_p90": B.agregar_regioes(v["semana2_p90"]),
                        "membros": v.get("membros")} if "semana1_p10" in v else {}),
                    "semana1_bacias": v.get("semana1", {}), "semana2_bacias": v.get("semana2", {})}
                for k, v in prev.items()}

        if "vento" in etapas:
            vento = {}
            for chave, func in VENTO.items():
                try:
                    vento[chave] = func(tmp, hoje)
                    status[f"vento_{chave}"] = f"ok (rodada {vento[chave]['rodada']})"
                except Exception as e:  # noqa
                    status[f"vento_{chave}"] = f"erro: {e}"
                    traceback.print_exc()
            latest["vento_previsto"] = vento

        if "observado" in etapas:
            novos = 0
            for d in dias_para_coletar(hoje, P_OBS):
                try:
                    o = observado(d, tmp, masc)
                    if o:
                        _w(os.path.join(P_OBS, f"{d.isoformat()}.json"), o)
                        novos += 1
                except Exception:  # noqa
                    traceback.print_exc()
            status["observado"] = f"ok ({novos} dia(s) novo(s))"
            disp = sorted(f[:10] for f in os.listdir(P_OBS)) if os.path.isdir(P_OBS) else []
            if disp:
                ult = dt.date.fromisoformat(disp[-1])
                latest["observado_ultimo_dia"] = _r(os.path.join(P_OBS, f"{ult.isoformat()}.json"))
                latest["acumulado_mes"] = acumulado_mes(hoje)
                latest["verificacao_d1"] = verificacao(ult)
            else:
                status["observado"] = "erro: nenhum dia observado disponível"

    if "setor" in etapas:
        for nome, func in {"ear": setor.ons_ear, "ena": setor.ons_ena, "carga": setor.ons_carga,
                           "pld": setor.ccee_pld, "cmo": setor.ons_cmo,
                           "eolica": setor.ons_eolica, "eolica_prev_ons": setor.ons_previsao_eolica}.items():
            try:
                latest[nome] = func(hoje.year)
                status[nome] = "ok"
            except Exception as e:  # noqa
                status[nome] = f"erro: {e}"
                traceback.print_exc()
        try:
            latest["enso"] = setor.enso()
            status["enso"] = "ok"
        except Exception as e:  # noqa
            status["enso"] = f"erro: {e}"

    latest["status"] = {**latest.get("status", {}), **status}
    _w(latest_p, latest)
    with open(os.path.join(DATA, "latest.md"), "w", encoding="utf-8") as fh:
        fh.write(resumo_md(latest))
    print(json.dumps(latest["status"], ensure_ascii=False, indent=1))


def _f(v, suf=""):
    return "n/d" if v is None else f"{v:g}{suf}"


def resumo_md(L):
    out = [f"# Coleta squadra-clima — {L.get('data_ref')}", f"Gerado em {L.get('gerado_em_utc')} UTC", ""]
    out.append("## Status das fontes")
    out += [f"- **{k}**: {v}" for k, v in L.get("status", {}).items()]
    e = L.get("enso")
    if e:
        out += ["", f"## ENOS (CPC, semana {e['semana']})",
                f"Niño 1+2 {e['nino12']:+.1f} · Niño 3 {e['nino3']:+.1f} · Niño 3.4 {e['nino34']:+.1f} "
                f"({e['var_nino34']:+.1f} na semana) · Niño 4 {e['nino4']:+.1f} °C"]
    v = L.get("verificacao_d1")
    if v:
        out += ["", f"## Chuva observada {v['dia']} x prevista (rodada {v['rodada_prevista']}) — mm",
                "| Bacia | Obs | GFS | GEFS | ECMWF | AIFS | Desvio |", "|---|---|---|---|---|---|---|"]
        for b, r in v["bacias"].items():
            out.append(f"| {b} | {_f(r['obs'])} | {_f(r.get('gfs'))} | {_f(r.get('gefs'))} | "
                       f"{_f(r.get('ecmwf'))} | {_f(r.get('aifs'))} | {_f(r.get('desvio'))} |")
    p = L.get("previsoes")
    if p:
        out += ["", "## Previsão por região — semana 1 (dias 1–7) / semana 2 (dias 8–14), mm"]
        cols = list(p.keys())
        out += ["| Região | " + " | ".join(p[c]["modelo"] for c in cols) + " |",
                "|---|" + "---|" * len(cols)]
        for reg in B.REGIOES:
            out.append(f"| {reg} | " + " | ".join(
                f"{_f(p[c]['semana1'].get(reg))} / {_f(p[c]['semana2'].get(reg))}" for c in cols) + " |")
    for k, t in (("ear", "EAR (%)"), ("ena", "ENA (% MLT)")):
        if isinstance(L.get(k), dict):
            out += ["", f"## {t}"] + [f"- {s}: {json.dumps(x, ensure_ascii=False)}" for s, x in L[k].items()]
    if isinstance(L.get("pld"), dict):
        out += ["", f"## PLD ({L['pld'].get('referencia')})"] + [
            f"- {s}: média {x['media']} R$/MWh" for s, x in L["pld"].get("submercados", {}).items()]
    if isinstance(L.get("cmo"), dict):
        out += ["", f"## CMO ONS ({L['cmo'].get('data')})"] + [
            f"- {s}: média {x['media']} R$/MWh" for s, x in L["cmo"].get("submercados", {}).items()]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    main()

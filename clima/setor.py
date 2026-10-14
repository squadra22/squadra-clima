"""Dados do setor elétrico (ONS, CCEE) e índices ENOS (NOAA CPC)."""
import io
import re

import pandas as pd
import requests

UA = {"User-Agent": "squadra-clima/1.0 (github actions)"}
ONS = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset"
SUBS = {"SE": "SE/CO", "S": "Sul", "NE": "Nordeste", "N": "Norte"}


def _csv(url):
    r = requests.get(url, headers=UA, timeout=120)
    r.raise_for_status()
    return pd.read_csv(io.BytesIO(r.content), sep=";", decimal=".", encoding="utf-8")


def _col(df, *frags):
    for c in df.columns:
        if all(f in c.lower() for f in frags):
            return c
    raise KeyError(f"coluna com {frags} não encontrada em {list(df.columns)}")


def _sub(v):
    v = str(v).strip().upper()
    return SUBS.get(v, v)


def ons_ear(ano):
    df = _csv(f"{ONS}/ear_subsistema_di/EAR_DIARIO_SUBSISTEMA_{ano}.csv")
    cd, cs, cp = _col(df, "ear_data"), _col(df, "id_subsistema"), _col(df, "percentual")
    df[cd] = pd.to_datetime(df[cd])
    ult = df[cd].max()
    sem = ult - pd.Timedelta(days=7)
    out = {}
    for _, r in df[df[cd] == ult].iterrows():
        ant = df[(df[cs] == r[cs]) & (df[cd] == sem)]
        out[_sub(r[cs])] = {"data": ult.date().isoformat(), "pct": round(float(r[cp]), 1),
                            "var_7d": round(float(r[cp] - ant[cp].iloc[0]), 1) if len(ant) else None}
    return out


def ons_ena(ano):
    df = _csv(f"{ONS}/ena_subsistema_di/ENA_DIARIO_SUBSISTEMA_{ano}.csv")
    cd, cs = _col(df, "ena_data"), _col(df, "id_subsistema")
    cmw, cpct = _col(df, "bruta", "mwmed"), _col(df, "bruta", "percentualmlt")
    df[cd] = pd.to_datetime(df[cd])
    ult = df[cd].max()
    mes = df[(df[cd].dt.month == ult.month) & (df[cd].dt.year == ult.year)]
    out = {}
    for s, g in df[df[cd] == ult].groupby(cs):
        gm = mes[mes[cs] == s]
        out[_sub(s)] = {"data": ult.date().isoformat(), "mwmed": round(float(g[cmw].iloc[0]), 0),
                        "pct_mlt": round(float(g[cpct].iloc[0]), 1),
                        "pct_mlt_mes": round(float(gm[cpct].mean()), 1)}
    return out


def ons_carga(ano):
    df = _csv(f"{ONS}/carga_energia_di/CARGA_ENERGIA_{ano}.csv")
    cd, cs, cv = _col(df, "din_instante"), _col(df, "id_subsistema"), _col(df, "carga")
    df[cd] = pd.to_datetime(df[cd])
    ult = df[cd].max()
    out = {}
    for s, g in df[df[cd] == ult].groupby(cs):
        out[_sub(s)] = {"data": ult.date().isoformat(), "mwmed": round(float(g[cv].iloc[0]), 0)}
    return out


CCEE = "https://dadosabertos.ccee.org.br/api/3/action"


def _json(url, params):
    r = requests.get(url, params=params, headers={**UA, "Accept": "application/json"}, timeout=60)
    try:
        return r.json()
    except ValueError:
        raise RuntimeError(f"HTTP {r.status_code} sem JSON em {r.url}: {r.text[:200]!r}")


def ccee_pld(ano):
    """PLD horário mais recente (média diária por submercado) via API CKAN da CCEE."""
    pk = _json(f"{CCEE}/package_show", {"id": "pld_horario"})
    recursos = [r for r in pk["result"]["resources"] if str(ano) in (r.get("name", "") + r.get("url", ""))
                and r.get("datastore_active")]
    if not recursos:
        raise RuntimeError("recurso PLD horário do ano não encontrado")
    rid = recursos[-1]["id"]
    rows = _json(f"{CCEE}/datastore_search", {"resource_id": rid, "limit": 2000, "sort": "_id desc"})["result"]["records"]
    df = pd.DataFrame(rows)
    cs = next(c for c in df.columns if "SUBMERCADO" in c.upper())
    cv = next(c for c in df.columns if "PLD" in c.upper())
    cdia = next((c for c in df.columns if c.upper() == "DIA"), None)
    cmes = next((c for c in df.columns if "MES" in c.upper()), None)
    df[cv] = pd.to_numeric(df[cv], errors="coerce")
    if cdia and cmes:
        df["_k"] = df[cmes].astype(str) + "-" + df[cdia].astype(str).str.zfill(2)
        ult = df["_k"].max()
        df = df[df["_k"] == ult]
    else:
        ult = None
    out = {"referencia": ult, "submercados": {}}
    for s, g in df.groupby(cs):
        out["submercados"][str(s).title()] = {"media": round(float(g[cv].mean()), 2),
                                              "max": round(float(g[cv].max()), 2),
                                              "min": round(float(g[cv].min()), 2)}
    return out


def enso():
    """Último registro semanal do CPC (Niño 1+2, 3, 3.4, 4: TSM e anomalia, base 1991-2020)."""
    r = requests.get("https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for", headers=UA, timeout=60)
    r.raise_for_status()
    linhas = [l for l in r.text.splitlines() if re.match(r"^\s*\d{2}[A-Z]{3}\d{4}", l)]
    def parse(l):
        p = l.split()
        nums = [float(x) for x in re.findall(r"-?\d+\.\d", l[10:])]
        return {"semana": p[0], "nino12": nums[1], "nino3": nums[3], "nino34": nums[5], "nino4": nums[7]}
    ult, ant = parse(linhas[-1]), parse(linhas[-2])
    ult["var_nino34"] = round(ult["nino34"] - ant["nino34"], 1)
    return ult


def ons_cmo(ano):
    """CMO semi-horário do ONS (média do último dia por subsistema) — referência quando o PLD não vem."""
    erros = []
    for ds, arq in (("cmo_semihorario", f"CMO_SEMIHORARIO_{ano}.csv"), ("cmo_tm", f"CMO_SEMIHORARIO_{ano}.csv")):
        try:
            df = _csv(f"{ONS}/{ds}/{arq}")
            break
        except Exception as e:  # noqa
            erros.append(str(e))
    else:
        raise RuntimeError("; ".join(erros))
    cd, cs, cv = _col(df, "din_instante"), _col(df, "id_subsistema"), _col(df, "cmo")
    df[cd] = pd.to_datetime(df[cd])
    dia = df[cd].dt.date.max()
    d = df[df[cd].dt.date == dia]
    return {"data": dia.isoformat(), "submercados": {_sub(s): {"media": round(float(g[cv].mean()), 2),
                                                               "max": round(float(g[cv].max()), 2)}
                                                     for s, g in d.groupby(cs)}}


def ons_eolica(ano, dias=15):
    """Geração eólica verificada (ONS, balanço de energia horário por subsistema): NE e Sul.

    Retorna série horária dos últimos `dias` dias (MWmed) e médias diárias, mais a média dos 30 dias.
    """
    dfs = []
    hoje = pd.Timestamp.utcnow().tz_localize(None)
    anos = [ano] if hoje.dayofyear > dias + 31 else [ano - 1, ano]
    for a in anos:
        try:
            dfs.append(_csv(f"{ONS}/balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_{a}.csv"))
        except Exception:  # noqa
            if a == ano:
                raise
    df = pd.concat(dfs, ignore_index=True)
    cd, cs, cv = _col(df, "din_instante"), _col(df, "id_subsistema"), _col(df, "eolica")
    df[cd] = pd.to_datetime(df[cd])
    df[cv] = pd.to_numeric(df[cv], errors="coerce")
    df["_sub"] = df[cs].map(_sub)
    df = df[df["_sub"].isin(["Nordeste", "Sul"])]
    ult = df[cd].max()
    rec = df[df[cd] > ult - pd.Timedelta(days=dias)]
    piv = rec.pivot_table(index=cd, columns="_sub", values=cv, aggfunc="mean").sort_index()
    serie = [{"t": t.strftime("%Y-%m-%dT%H:%M"), **{k: (None if pd.isna(v) else round(float(v), 0)) for k, v in row.items()}}
             for t, row in piv.iterrows()]
    diario = (rec.assign(_d=rec[cd].dt.date).groupby(["_d", "_sub"])[cv].mean().unstack())
    m30 = df[df[cd] > ult - pd.Timedelta(days=30)].groupby("_sub")[cv].mean()
    return {"ate": ult.strftime("%Y-%m-%dT%H:%M"), "serie_horaria": serie,
            "diario": {d.isoformat(): {k: round(float(v), 0) for k, v in r.items() if not pd.isna(v)}
                       for d, r in diario.iterrows()},
            "media_30d": {k: round(float(v), 0) for k, v in m30.items()}}


def _prog_eolica_dia(dia):
    """Programação diária do ONS (previsão eólica usada na programação), somada por subsistema.

    Retorna None se o arquivo do dia ainda não foi publicado.
    """
    url = f"{ONS}/programacao_diaria/PROGRAMACAO_DIARIA_{dia:%Y_%m_%d}.csv"
    try:
        df = _csv(url)
    except Exception:  # noqa
        return None
    ct, cs, cp, cv = (_col(df, "tip_geracao"), _col(df, "id_subsistema"), _col(df, "num_patamar"),
                      _col(df, "geracaoprogramada"))
    df = df[df[ct].astype(str).str.upper().str.contains("EOL|EÓL")]
    df[cv] = pd.to_numeric(df[cv], errors="coerce")
    g = df.groupby([cs, cp])[cv].sum().reset_index()
    out = {}
    for s, gs in g.groupby(cs):
        gs = gs.sort_values(cp)
        mw = [round(float(v), 0) for v in gs[cv]]
        passo_h = 24 / len(mw) if len(mw) else 0.5
        out[_sub(s)] = {"curva_mw": mw, "passo_h": passo_h,
                        "gwh": round(sum(mw) * passo_h / 1000, 1), "mwmed": round(sum(mw) / len(mw), 0)}
    return {"dia": dia.isoformat(), "subsistemas": out}


def ons_previsao_eolica(ano):
    """Previsão eólica do ONS para o próximo dia publicado (D+1, senão D) e verificação de D-1."""
    hoje = pd.Timestamp.utcnow().tz_localize(None).date()
    prev = None
    for d in (hoje + pd.Timedelta(days=1), hoje):
        prev = _prog_eolica_dia(d)
        if prev:
            break
    if not prev:
        raise RuntimeError("programação diária do ONS indisponível para D e D+1")
    # verificação: programado x verificado do último dia completo do balanço horário
    verif = None
    try:
        dfb = _csv(f"{ONS}/balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_{ano}.csv")
        cd, cs, cv = _col(dfb, "din_instante"), _col(dfb, "id_subsistema"), _col(dfb, "eolica")
        dfb[cd] = pd.to_datetime(dfb[cd])
        dfb[cv] = pd.to_numeric(dfb[cv], errors="coerce")
        cont = dfb.groupby(dfb[cd].dt.date)[cd].nunique()
        dias_completos = [d for d, k in cont.items() if k >= 24]
        if dias_completos:
            dv = max(dias_completos)
            p = _prog_eolica_dia(dv)
            real = dfb[dfb[cd].dt.date == dv].groupby(cs)[cv].sum() / 1000  # MWh -> GWh (dados horários)
            if p:
                verif = {"dia": dv.isoformat(), "subsistemas": {}}
                for s, x in p["subsistemas"].items():
                    rv = next((float(v) for k, v in real.items() if _sub(k) == s), None)
                    verif["subsistemas"][s] = {"previsto_gwh": x["gwh"], "verificado_gwh": round(rv, 1) if rv else None,
                                               "erro_pct": round(100 * (x["gwh"] / rv - 1), 1) if rv else None}
    except Exception:  # noqa
        pass
    return {"previsao": prev, "verificacao": verif}

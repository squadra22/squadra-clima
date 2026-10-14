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


def ccee_pld(ano):
    """PLD horário mais recente (média diária por submercado) via API CKAN da CCEE."""
    pk = requests.get(f"{CCEE}/package_show", params={"id": "pld_horario"}, headers=UA, timeout=60).json()
    recursos = [r for r in pk["result"]["resources"] if str(ano) in (r.get("name", "") + r.get("url", ""))
                and r.get("datastore_active")]
    if not recursos:
        raise RuntimeError("recurso PLD horário do ano não encontrado")
    rid = recursos[-1]["id"]
    rows = requests.get(f"{CCEE}/datastore_search", params={"resource_id": rid, "limit": 2000, "sort": "_id desc"},
                        headers=UA, timeout=60).json()["result"]["records"]
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

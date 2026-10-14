"""Chuva observada diária por bacia.

Fonte principal: MERGE/CPTEC (satélite GPM + pluviômetros, 0,1°), dia rotulado
pela data final da janela 12Z→12Z. Reserva: CPC Unified Gauge (NOAA, 0,5°).
"""
import datetime as dt
import os

import numpy as np
import requests

from .grib import ler_mensagens

UA = {"User-Agent": "squadra-clima/1.0 (github actions)"}
MERGE_URLS = [
    "https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/{y}/{m}/MERGE_CPTEC_{ymd}.grib2",
    "http://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/{y}/{m}/MERGE_CPTEC_{ymd}.grib2",
]
CPC_URL = ("https://ftp.cpc.ncep.noaa.gov/precip/CPC_UNI_PRCP/GAUGE_GLB/RT/{y}/"
           "PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.{ymd}.RT")


def _get(url):
    try:
        r = requests.get(url, headers=UA, timeout=90)
        if r.status_code == 200 and len(r.content) > 1000:
            return r.content
    except requests.RequestException:
        pass
    return None


def merge(dia, tmp, masc):
    ymd = dia.strftime("%Y%m%d")
    for u in MERGE_URLS:
        conteudo = _get(u.format(y=dia.year, m=f"{dia.month:02d}", ymd=ymd))
        if conteudo and conteudo[:4] == b"GRIB":
            f = os.path.join(tmp, f"merge_{ymd}.grib2")
            with open(f, "wb") as fh:
                fh.write(conteudo)
            msgs = ler_mensagens(f)
            if not msgs:  # MERGE às vezes vem com shortName genérico: lê a 1ª mensagem
                msgs = _primeira_mensagem(f)
            m = msgs[0]
            v = np.where(m["valores"] < 0, np.nan, m["valores"])
            return {"fonte": "MERGE/CPTEC", "dia": dia.isoformat(), "bacias": masc.medias(v, m["lats"], m["lons"])}
    return None


def _primeira_mensagem(f):
    import eccodes
    with open(f, "rb") as fh:
        gid = eccodes.codes_grib_new_from_file(fh)
        vals = eccodes.codes_get_values(gid).astype("float64")
        lats = eccodes.codes_get_array(gid, "latitudes")
        lons = eccodes.codes_get_array(gid, "longitudes")
        eccodes.codes_release(gid)
    return [{"valores": vals, "lats": lats, "lons": lons}]


def cpc(dia, masc):
    ymd = dia.strftime("%Y%m%d")
    conteudo = _get(CPC_URL.format(y=dia.year, ymd=ymd))
    if not conteudo:
        return None
    arr = np.frombuffer(conteudo, dtype="<f4")
    if arr.size < 720 * 360:
        return None
    campo = arr[: 720 * 360].reshape(360, 720) / 10.0  # 0,1 mm -> mm
    campo = np.where(campo < 0, np.nan, campo)
    lat = -89.75 + 0.5 * np.arange(360)
    lon = 0.25 + 0.5 * np.arange(720)
    LON, LAT = np.meshgrid(lon, lat)
    return {"fonte": "CPC Unified Gauge (NOAA)", "dia": dia.isoformat(),
            "bacias": masc.medias(campo.ravel(), LAT.ravel(), LON.ravel())}


def observado(dia, tmp, masc):
    return merge(dia, tmp, masc) or cpc(dia, masc)


def dias_para_coletar(hoje, pasta_obs, max_dias=40):
    """Dias (data final da janela 12Z→12Z) ainda sem arquivo, do dia 1 do mês até ontem."""
    inicio = hoje.replace(day=1) - dt.timedelta(days=1)  # inclui o último dia do mês anterior
    out = []
    d = hoje
    while d > inicio and len(out) < max_dias:
        if not os.path.exists(os.path.join(pasta_obs, f"{d.isoformat()}.json")):
            out.append(d)
        d -= dt.timedelta(days=1)
    return out

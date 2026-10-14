"""Download das rodadas 00z e cálculo de chuva por bacia.

Janelas diárias: 12Z→12Z (mesma convenção do MERGE/CPTEC). Para a rodada 00z do
dia R, o "dia k" vai do passo 12+24(k-1) ao passo 12+24k e é rotulado com a data R+k.
Semana 1 = dias 1–7 (passos 12→180); semana 2 = dias 8–14 (passos 180→348).
"""
import datetime as dt
import os
import time

import numpy as np
import requests

from .bacias import Mascaras
from .grib import ler_mensagens, acumulado_ate

UA = {"User-Agent": "squadra-clima/1.0 (github actions)"}
PASSOS_DIA = [12 + 24 * k for k in range(0, 15)]  # 12, 36, ..., 348


def _janelas(passos_disp, rodada):
    """Lista (rotulo_data, a, b) das janelas diárias cobertas pelos passos disponíveis."""
    r = dt.datetime.strptime(rodada[:8], "%Y%m%d")
    out = []
    for k in range(1, 15):
        a, b = 12 + 24 * (k - 1), 12 + 24 * k
        if a in passos_disp and b in passos_disp:
            out.append(((r + dt.timedelta(days=k)).date().isoformat(), a, b))
    return out


def _resumo_det(msgs, rodada, masc, nome):
    """Para modelos determinísticos: diário por bacia + semanas."""
    lats, lons = msgs[0]["lats"], msgs[0]["lons"]
    passos = sorted({m["end"] for m in msgs} | {0})
    tot = {t: acumulado_ate(msgs, t) for t in passos}
    tot[0] = np.zeros_like(lats)
    diario = {}
    for data, a, b in _janelas(passos, rodada):
        if tot.get(a) is None or tot.get(b) is None:
            continue
        diario[data] = masc.medias(np.maximum(tot[b] - tot[a], 0), lats, lons)
    semanas = {}
    for rot, (a, b) in {"semana1": (12, 180), "semana2": (180, 348)}.items():
        if tot.get(a) is not None and tot.get(b) is not None:
            semanas[rot] = masc.medias(np.maximum(tot[b] - tot[a], 0), lats, lons)
    return {"modelo": nome, "rodada": rodada, "diario": diario, **semanas}


# ---------------------------------------------------------------- ECMWF
def _ecmwf_retrieve(model, tipo, passos, destino, data):
    from ecmwf.opendata import Client
    c = Client(source="ecmwf", model=model, resol="0p25")
    c.retrieve(date=data, time=0, type=tipo, step=passos, param="tp", target=destino)


def _datas_tentativa(hoje):
    return [hoje.strftime("%Y%m%d"), (hoje - dt.timedelta(days=1)).strftime("%Y%m%d")]


def ecmwf_ifs(tmp, masc, hoje):
    passos = [p for p in PASSOS_DIA if p <= 228] + [0]
    for d in _datas_tentativa(hoje):
        try:
            f = os.path.join(tmp, f"ifs_{d}.grib2")
            _ecmwf_retrieve("ifs", "fc", sorted(set(passos) - {0}), f, int(d))
            msgs = ler_mensagens(f)
            return _resumo_det(msgs, d + "00", masc, "ECMWF IFS")
        except Exception as e:  # noqa
            erro = e
    raise RuntimeError(f"ECMWF IFS indisponível: {erro}")


def ecmwf_aifs(tmp, masc, hoje):
    for d in _datas_tentativa(hoje):
        try:
            f = os.path.join(tmp, f"aifs_{d}.grib2")
            _ecmwf_retrieve("aifs-single", "fc", PASSOS_DIA, f, int(d))
            msgs = ler_mensagens(f)
            return _resumo_det(msgs, d + "00", masc, "ECMWF AIFS")
        except Exception as e:  # noqa
            erro = e
    raise RuntimeError(f"ECMWF AIFS indisponível: {erro}")


def _resumo_ens(msgs, rodada, masc, nome):
    lats, lons = msgs[0]["lats"], msgs[0]["lons"]
    por_membro = {}
    for m in msgs:
        por_membro.setdefault(m["numero"] or 0, []).append(m)
    res = {}
    for rot, (a, b) in {"semana1": (12, 180), "semana2": (180, 348)}.items():
        valores = {}
        for num, ms in por_membro.items():
            ta, tb = acumulado_ate(ms, a), acumulado_ate(ms, b)
            if ta is None or tb is None:
                continue
            for bacia, v in masc.medias(np.maximum(tb - ta, 0), lats, lons).items():
                valores.setdefault(bacia, []).append(v)
        res[rot] = {k: round(float(np.mean(v)), 1) for k, v in valores.items()}
        res[rot + "_p10"] = {k: round(float(np.percentile(v, 10)), 1) for k, v in valores.items()}
        res[rot + "_p90"] = {k: round(float(np.percentile(v, 90)), 1) for k, v in valores.items()}
        res["membros"] = len(por_membro)
    return {"modelo": nome, "rodada": rodada, **res}


def ecmwf_ens(tmp, masc, hoje):
    for d in _datas_tentativa(hoje):
        try:
            f = os.path.join(tmp, f"ens_{d}.grib2")
            _ecmwf_retrieve("ifs", "pf", [12, 180, 348], f, int(d))
            return _resumo_ens(ler_mensagens(f), d + "00", masc, "ECMWF ENS")
        except Exception as e:  # noqa
            erro = e
    raise RuntimeError(f"ECMWF ENS indisponível: {erro}")


# ---------------------------------------------------------------- NOAA (NOMADS)
NOMADS = "https://nomads.ncep.noaa.gov/cgi-bin"
SUB = "&subregion=&toplat=2&leftlon=286&rightlon=328&bottomlat=-34"


def _baixar(url, destino, tentativas=3):
    for i in range(tentativas):
        try:
            r = requests.get(url, headers=UA, timeout=90)
            if r.status_code == 200 and r.content[:4] == b"GRIB":
                with open(destino, "wb") as fh:
                    fh.write(r.content)
                return True
            if r.status_code == 404:
                return False
        except requests.RequestException:
            pass
        time.sleep(3 * (i + 1))
    return False


def _noaa(tmp, masc, hoje, nome, script, dir_fmt, arq_fmt, passo_max):
    erro = None
    for d in _datas_tentativa(hoje):
        msgs = []
        ok = True
        for fh in range(6, passo_max + 1, 6):
            url = (f"{NOMADS}/{script}?dir={dir_fmt.format(d=d)}&file={arq_fmt.format(f=fh)}"
                   f"&var_APCP=on&lev_surface=on{SUB}")
            dest = os.path.join(tmp, f"{nome.replace(' ', '_')}_{d}_{fh:03d}.grib2")
            if not _baixar(url, dest):
                if fh <= 36:  # rodada ainda não saiu
                    ok = False
                    erro = f"arquivo f{fh:03d} da rodada {d} indisponível"
                break
            msgs += ler_mensagens(dest)
            time.sleep(0.4)
        if ok and msgs:
            return _resumo_det(msgs, d + "00", masc, nome)
    raise RuntimeError(f"{nome} indisponível: {erro}")


def gfs(tmp, masc, hoje):
    return _noaa(tmp, masc, hoje, "GFS", "filter_gfs_0p25.pl", "%2Fgfs.{d}%2F00%2Fatmos",
                 "gfs.t00z.pgrb2.0p25.f{f:03d}", 348)


def gefs(tmp, masc, hoje):
    """Média do ensemble GEFS (arquivo geavg)."""
    return _noaa(tmp, masc, hoje, "GEFS (média)", "filter_gefs_atmos_0p50a.pl",
                 "%2Fgefs.{d}%2F00%2Fatmos%2Fpgrb2ap5", "geavg.t00z.pgrb2a.0p50.f{f:03d}", 348)


MODELOS = {
    "gfs": gfs,
    "gefs": gefs,
    "ecmwf": ecmwf_ifs,
    "ecmwf_ens": ecmwf_ens,
    "aifs": ecmwf_aifs,
}

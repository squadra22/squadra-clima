"""Vento a 100 m previsto (GFS e ECMWF IFS/AIFS) nas regiões dos parques eólicos.

Saída: série 6-horária e médias diárias da velocidade (m/s) por região, por modelo.
Regiões aproximadas (lon, lat) cobrindo os principais polos eólicos.
"""
import datetime as dt
import os
import time

import eccodes
import numpy as np

from .bacias import Mascaras
from .modelos import _baixar, _datas_tentativa, NOMADS, SUB

REGIOES_EOLICAS = {
    "NE interior (BA/PI)": [(-43.8, -15.0), (-40.0, -15.0), (-40.0, -8.8), (-42.5, -7.5), (-43.8, -9.5)],
    "NE litoral norte (CE/RN)": [(-41.5, -2.6), (-37.0, -4.4), (-35.0, -5.0), (-35.2, -6.6), (-37.5, -6.2),
                                 (-40.5, -4.2), (-41.6, -3.2)],
    "Sul (RS)": [(-54.0, -33.6), (-52.0, -33.0), (-50.2, -30.5), (-51.0, -29.5), (-53.5, -30.0), (-55.5, -31.5)],
}


def _ler_vento(caminho):
    """{passo: {"u": vals, "v": vals}}, lats, lons, data da rodada."""
    campos, lats, lons, rodada = {}, None, None, None
    with open(caminho, "rb") as fh:
        while True:
            gid = eccodes.codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                sn = eccodes.codes_get(gid, "shortName")
                comp = {"100u": "u", "100v": "v", "u100": "u", "v100": "v"}.get(sn)
                if comp is None and sn in ("u", "v") and eccodes.codes_get(gid, "level") == 100:
                    comp = sn
                if comp is None:
                    continue
                passo = int(str(eccodes.codes_get(gid, "stepRange")).split("-")[-1])
                campos.setdefault(passo, {})[comp] = eccodes.codes_get_values(gid).astype("float64")
                if lats is None:
                    lats = eccodes.codes_get_array(gid, "latitudes")
                    lons = eccodes.codes_get_array(gid, "longitudes")
                    rodada = str(eccodes.codes_get(gid, "dataDate")) + f"{eccodes.codes_get(gid, 'dataTime') // 100:02d}"
            finally:
                eccodes.codes_release(gid)
    return campos, lats, lons, rodada


def _resumir(campos, lats, lons, rodada, nome):
    masc = Mascaras(REGIOES_EOLICAS)
    r0 = dt.datetime.strptime(rodada, "%Y%m%d%H")
    serie = []
    for passo in sorted(campos):
        c = campos[passo]
        if "u" not in c or "v" not in c:
            continue
        vel = np.hypot(c["u"], c["v"])
        serie.append({"t": (r0 + dt.timedelta(hours=passo)).strftime("%Y-%m-%dT%H"),
                      **masc.medias(vel, lats, lons)})
    diario = {}
    for p in serie:
        d = p["t"][:10]
        for reg in REGIOES_EOLICAS:
            if p.get(reg) is not None:
                diario.setdefault(d, {}).setdefault(reg, []).append(p[reg])
    diario = {d: {r: round(float(np.mean(v)), 2) for r, v in regs.items()} for d, regs in diario.items()}
    return {"modelo": nome, "rodada": rodada, "serie_6h": serie, "diario": diario}


def vento_ecmwf(tmp, hoje, model="ifs", nome="ECMWF IFS"):
    from ecmwf.opendata import Client
    passos = list(range(0, 241, 6)) if model == "ifs" else list(range(0, 361, 6))
    erro = None
    for d in _datas_tentativa(hoje):
        try:
            f = os.path.join(tmp, f"vento_{model}_{d}.grib2")
            Client(source="ecmwf", model=model, resol="0p25").retrieve(
                date=int(d), time=0, type="fc", step=passos, param=["100u", "100v"], target=f)
            campos, lats, lons, rod = _ler_vento(f)
            if campos:
                return _resumir(campos, lats, lons, rod, nome)
        except Exception as e:  # noqa
            erro = e
    raise RuntimeError(f"vento {nome} indisponível: {erro}")


def vento_gfs(tmp, hoje):
    erro = None
    for d in _datas_tentativa(hoje):
        campos, lats, lons, rod = {}, None, None, None
        for fh_ in range(0, 361, 6):
            url = (f"{NOMADS}/filter_gfs_0p25.pl?dir=%2Fgfs.{d}%2F00%2Fatmos&file=gfs.t00z.pgrb2.0p25.f{fh_:03d}"
                   f"&var_UGRD=on&var_VGRD=on&lev_100_m_above_ground=on{SUB}")
            dest = os.path.join(tmp, f"vento_gfs_{d}_{fh_:03d}.grib2")
            if not _baixar(url, dest):
                if fh_ <= 24:
                    erro = f"f{fh_:03d} da rodada {d} indisponível"
                    campos = {}
                break
            c, la, lo, r = _ler_vento(dest)
            campos.update(c)
            if lats is None:
                lats, lons, rod = la, lo, r
            time.sleep(0.4)
        if campos:
            return _resumir(campos, lats, lons, rod, "GFS")
    raise RuntimeError(f"vento GFS indisponível: {erro}")


VENTO = {
    "gfs": vento_gfs,
    "ecmwf": lambda tmp, hoje: vento_ecmwf(tmp, hoje, "ifs", "ECMWF IFS"),
    "aifs": lambda tmp, hoje: vento_ecmwf(tmp, hoje, "aifs-single", "ECMWF AIFS"),
}

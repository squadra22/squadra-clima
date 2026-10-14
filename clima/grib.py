"""Leitura genérica de precipitação acumulada em GRIB (via eccodes)."""
import numpy as np
import eccodes


def ler_mensagens(caminho, short_names=("tp", "prate", "APCP", "unknown")):
    """Lê todas as mensagens de precipitação de um arquivo GRIB.

    Retorna lista de dicts com: start, end (horas desde a rodada), valores (mm, 1D),
    lats, lons (1D), numero (membro do ensemble ou None), data_rodada (YYYYMMDD), hora_rodada.
    """
    out = []
    with open(caminho, "rb") as fh:
        while True:
            gid = eccodes.codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                sn = eccodes.codes_get(gid, "shortName")
                name = eccodes.codes_get(gid, "name") if eccodes.codes_is_defined(gid, "name") else ""
                eh_tp_grib2 = (eccodes.codes_is_defined(gid, "parameterCategory")
                               and eccodes.codes_get(gid, "discipline") == 0
                               and eccodes.codes_get(gid, "parameterCategory") == 1
                               and eccodes.codes_get(gid, "parameterNumber") in (8, 52, 193))
                if sn not in ("tp", "APCP") and "total precipitation" not in name.lower() and not eh_tp_grib2:
                    continue
                rng = str(eccodes.codes_get(gid, "stepRange"))
                if "-" in rng:
                    a, b = rng.split("-")
                else:
                    a, b = 0, rng
                start, end = int(a), int(b)
                vals = eccodes.codes_get_values(gid).astype("float64")
                miss = eccodes.codes_get(gid, "missingValue") if eccodes.codes_is_defined(gid, "missingValue") else 9999
                vals[vals == miss] = np.nan
                units = eccodes.codes_get(gid, "units") if eccodes.codes_is_defined(gid, "units") else ""
                if sn == "tp" and units == "m":
                    vals = vals * 1000.0  # ECMWF: metros -> mm
                lats = eccodes.codes_get_array(gid, "latitudes")
                lons = eccodes.codes_get_array(gid, "longitudes")
                num = eccodes.codes_get(gid, "number") if eccodes.codes_is_defined(gid, "number") else None
                out.append({
                    "start": start, "end": end, "valores": vals, "lats": lats, "lons": lons,
                    "numero": num,
                    "data_rodada": str(eccodes.codes_get(gid, "dataDate")),
                    "hora_rodada": int(eccodes.codes_get(gid, "dataTime")) // 100,
                })
            finally:
                eccodes.codes_release(gid)
    return out


def acumulado_ate(msgs, t):
    """Total 0→t a partir de mensagens com intervalos (start,end) quaisquer.

    Usa o total corrido (0,t) se existir; senão encadeia baldes (a,t) recursivamente.
    """
    idx = {(m["start"], m["end"]): m for m in msgs}
    memo = {0: None}

    def rec(tt):
        if tt in memo:
            return memo[tt]
        if (0, tt) in idx:
            memo[tt] = idx[(0, tt)]["valores"]
            return memo[tt]
        cands = sorted([k for k in idx if k[1] == tt and k[0] > 0], key=lambda k: k[0])
        for a, _ in cands:
            base = rec(a)
            if base is not None or a == 0:
                v = idx[(a, tt)]["valores"] + (base if base is not None else 0)
                memo[tt] = v
                return v
        memo[tt] = None
        return None

    return rec(t)

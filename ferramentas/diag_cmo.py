import json, os, traceback, datetime as dt, requests
from clima import monitor_cmo as M
out = {}
url = M.URL.format(ano=2026)
try:
    h = requests.head(url, headers=M.UA, timeout=60)
    out["head_status"] = h.status_code; out["head_headers"] = dict(h.headers)
except Exception as e:
    out["head_erro"] = repr(e)
try:
    r = requests.get(url, headers=M.UA, timeout=180)
    out["get_status"] = r.status_code; out["get_bytes"] = len(r.content); out["primeiras_linhas"] = r.content[:400].decode("utf-8", "replace")
    out["ultimas_linhas"] = r.content[-600:].decode("utf-8", "replace")
    for d in (dt.date(2026, 10, 16), dt.date(2026, 10, 17)):
        try:
            md, cont, comp, res, cur = M.analisar(r.content, d)
            out[f"analisar_{d}"] = {"max_dia": str(md), "cont": cont, "completo": comp}
        except Exception:
            out[f"analisar_{d}_erro"] = traceback.format_exc()[-1500:]
except Exception as e:
    out["get_erro"] = repr(e)
os.makedirs("data/descoberta", exist_ok=True)
json.dump(out, open("data/descoberta/diag_cmo.json", "w"), ensure_ascii=False, indent=1, default=str)

# rerun

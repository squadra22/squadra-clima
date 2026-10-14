"""Reconhecimento dos datasets de programação/previsão do ONS (CKAN)."""
import io, json, os, requests, pandas as pd
API = "https://dados.ons.org.br/api/3/action/package_show"
OUT = "data/descoberta"; os.makedirs(OUT, exist_ok=True)
rel = {}
for ds in ("programacao_x_previsao", "programacao_diaria"):
    try:
        r = requests.get(API, params={"id": ds}, timeout=60)
        pk = r.json()["result"]
        res = pk["resources"]
        rel[ds] = {"notes": pk.get("notes", "")[:2000], "n_recursos": len(res),
                   "ultimos": [{"name": x.get("name"), "url": x.get("url"), "format": x.get("format")} for x in res[-6:]],
                   "dicionario": [x.get("url") for x in res if "dicion" in (x.get("name", "") + x.get("url", "")).lower()][:3]}
        csvs = [x for x in res if x.get("url", "").lower().endswith(".csv")]
        if csvs:
            u = csvs[-1]["url"]
            c = requests.get(u, timeout=120).content
            df = pd.read_csv(io.BytesIO(c), sep=";", nrows=4000)
            rel[ds]["csv_url"] = u
            rel[ds]["colunas"] = list(df.columns)
            rel[ds]["amostra"] = df.head(15).astype(str).to_dict("records")
            for col in df.columns:
                if df[col].dtype == object and df[col].nunique() < 40:
                    rel[ds].setdefault("valores_distintos", {})[col] = sorted(df[col].dropna().unique().tolist())[:40]
            rel[ds]["linhas_lidas"] = len(df)
    except Exception as e:
        rel[ds] = {"erro": repr(e)}
json.dump(rel, open(f"{OUT}/ons_previsao.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(rel, ensure_ascii=False, default=str)[:3000])

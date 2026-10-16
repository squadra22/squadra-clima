"""Monitora a publicação do CMO semi-horário do ONS para D+1.

Uso: python -m clima.monitor_cmo [--intervalo 300] [--ate 19:15]

A cada `intervalo` segundos consulta o arquivo CMO_SEMIHORARIO_<ano>.csv (HEAD + ETag;
só baixa quando muda). Quando aparece o dia seguinte com as 48 meias-horas nos 4
subsistemas, registra o horário, grava a curva e termina. Se o arquivo chegar
incompleto, registra e continua até completar (ou até o horário-limite).

Saídas (data/cmo_publicacao/):
  historico.csv   uma linha por dia de CMO: quando foi detectado, Last-Modified, médias/máximos
  log.csv         toda consulta em que o arquivo mudou
  curvas/<dia>.json  curva semi-horária por subsistema
  ultimo.json     resumo da última publicação detectada (usado no aviso)
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import subprocess
import sys
import time
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

BRT = ZoneInfo("America/Sao_Paulo")
URL = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/cmo_tm/CMO_SEMIHORARIO_{ano}.csv"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA = os.path.join(RAIZ, "data", "cmo_publicacao")
SUBS = {"SE": "SE/CO", "S": "Sul", "NE": "Nordeste", "N": "Norte"}
UA = {"User-Agent": "squadra-clima/1.0 (github actions)"}


def agora():
    return dt.datetime.now(BRT)


def _brt(http_date):
    try:
        return parsedate_to_datetime(http_date).astimezone(BRT)
    except Exception:  # noqa
        return None


def _append_csv(nome, linha, cab):
    p = os.path.join(PASTA, nome)
    novo = not os.path.exists(p)
    with open(p, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cab, delimiter=";")
        if novo:
            w.writeheader()
        w.writerow(linha)


def ja_registrado(dia):
    p = os.path.join(PASTA, "historico.csv")
    if not os.path.exists(p):
        return False
    with open(p, encoding="utf-8") as fh:
        return any(r["dia_cmo"] == dia.isoformat() and r["completo"] == "sim"
                   for r in csv.DictReader(fh, delimiter=";"))


def analisar(conteudo, dia):
    df = pd.read_csv(io.BytesIO(conteudo), sep=";")
    cd = next(c for c in df.columns if "din_instante" in c.lower())
    cs = next(c for c in df.columns if "id_subsistema" in c.lower())
    cv = next(c for c in df.columns if c.lower().startswith("val_cmo") or c.lower() == "cmo")
    df[cd] = pd.to_datetime(df[cd])
    df[cv] = pd.to_numeric(df[cv], errors="coerce")
    max_dia = df[cd].dt.date.max()
    d = df[df[cd].dt.date == dia]
    contagem = {SUBS.get(str(s).strip(), s): int(g[cd].nunique()) for s, g in d.groupby(cs)}
    completo = len(contagem) >= 4 and all(v >= 48 for v in contagem.values())
    resumo, curvas = {}, {}
    for s, g in d.groupby(cs):
        nome = SUBS.get(str(s).strip(), str(s))
        g = g.sort_values(cd)
        resumo[nome] = {"media": round(float(g[cv].mean()), 2), "max": round(float(g[cv].max()), 2),
                        "min": round(float(g[cv].min()), 2),
                        "hora_max": g.loc[g[cv].idxmax(), cd].strftime("%H:%M")}
        curvas[nome] = [{"t": t.strftime("%H:%M"), "cmo": round(float(v), 2)} for t, v in zip(g[cd], g[cv])]
        hor = g.groupby(g[cd].dt.hour)[cv].mean()
        curvas.setdefault("_horario", {})[nome] = {int(h): round(float(v), 2) for h, v in hor.items()}
    return max_dia, contagem, completo, resumo, curvas


ORDEM = ("SE/CO", "Sul", "Nordeste", "Norte")
CORES = {"SE/CO": "#2a78d6", "Sul": "#eb6834", "Nordeste": "#1baf7a", "Norte": "#eda100"}


def grafico(dia, horario, destino):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.5, 3.0), dpi=160)
    for s in ORDEM:
        h = horario.get(s)
        if not h:
            continue
        xs = sorted(h)
        ax.plot(xs, [h[x] for x in xs], color=CORES[s], linewidth=1.8, marker="o", markersize=2.5, label=s)
    ax.set_title(f"CMO horário ONS — {dia:%d/%m/%Y} (R$/MWh)", fontsize=10, loc="left", fontweight="bold", color="#1F2933")
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}h" for h in range(0, 24, 2)])
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#D9DEE4")
    ax.tick_params(colors="#52514E", labelsize=8, length=0)
    ax.grid(axis="y", color="#E3E6EA", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(fontsize=8, frameon=False, ncol=4, loc="upper left", bbox_to_anchor=(0, -0.12))
    fig.tight_layout()
    fig.savefig(destino, facecolor="white")
    plt.close(fig)


def git_salvar(msg):
    cmds = [["git", "add", "data/cmo_publicacao"], ["git", "commit", "-q", "-m", msg]]
    for c in cmds:
        subprocess.run(c, cwd=RAIZ, check=False)
    for _ in range(4):
        subprocess.run(["git", "pull", "-q", "--rebase"], cwd=RAIZ, check=False)
        if subprocess.run(["git", "push", "-q"], cwd=RAIZ).returncode == 0:
            return
        time.sleep(5)


def br(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def avisar(dia, det, lm, resumo, completo, horario=None):
    """Abre (e fecha) uma issue no repositório: o GitHub envia o aviso por e-mail ao dono."""
    if not os.environ.get("GH_TOKEN"):
        return
    linhas = "\n".join(f"| {s} | {br(resumo[s]['media'])} | {br(resumo[s]['max'])} ({resumo[s]['hora_max']}) | "
                       f"{br(resumo[s]['min'])} |" for s in ORDEM if s in resumo)
    corpo = (f"CMO semi-horário do ONS para **{dia:%d/%m/%Y}** detectado às **{det:%H:%M}** (Brasília)."
             f"\nÚltima modificação do arquivo no ONS: {lm:%d/%m %H:%M}." if lm else "") + \
            ("" if completo else "\n\n⚠️ Dia ainda incompleto no momento da detecção.") + \
            f"\n\n**Resumo do dia** (R$/MWh)\n\n| Subsistema | Média | Máx (hora) | Mín |\n|---|---|---|---|\n{linhas}\n"
    horario = horario or {}
    if horario:
        cab = "| Hora | " + " | ".join(ORDEM) + " |\n|---|" + "---|" * len(ORDEM)
        lin = "\n".join(f"| {h:02d}h | " + " | ".join(
            (br(horario[s_][h]) if h in horario.get(s_, {}) else "—") for s_ in ORDEM) + " |" for h in range(24))
        corpo += f"\n**Curva horária** (R$/MWh, média das duas meias-horas)\n\n{cab}\n{lin}\n"
        repo = os.environ.get("GITHUB_REPOSITORY", "squadra22/squadra-clima")
        corpo += (f"\n![Curva horária](https://github.com/{repo}/blob/main/data/cmo_publicacao/curvas/{dia.isoformat()}.png?raw=true)"
                  f"\n\nArquivos: `data/cmo_publicacao/curvas/{dia.isoformat()}.json` (horário e semi-horário).")
    corpo += "\n\nFonte: ONS Dados Abertos (CMO semi-horário)."
    titulo = f"CMO {dia:%d/%m} publicado {det:%H:%M} — SE/CO R$ {br(resumo.get('SE/CO', {}).get('media', 0))}" + ("" if completo else " (parcial)")
    r = subprocess.run(["gh", "issue", "create", "--title", titulo, "--body", corpo],
                       cwd=RAIZ, capture_output=True, text=True)
    url = r.stdout.strip()
    print("aviso:", url or r.stderr)
    _append_csv("avisos.csv", {"dia_cmo": dia.isoformat(), "enviado_brt": agora().strftime("%Y-%m-%d %H:%M"),
                               "issue": url, "erro": "" if url else r.stderr.strip()[:300]},
                ["dia_cmo", "enviado_brt", "issue", "erro"])
    if url:
        subprocess.run(["gh", "issue", "close", url], cwd=RAIZ, check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intervalo", type=int, default=300)
    ap.add_argument("--ate", default="19:15", help="horário-limite (Brasília), HH:MM")
    a = ap.parse_args()
    os.makedirs(os.path.join(PASTA, "curvas"), exist_ok=True)
    inicio = agora()
    alvo = inicio.date() + dt.timedelta(days=1)
    hh, mm = map(int, a.ate.split(":"))
    limite = inicio.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if ja_registrado(alvo):
        print(f"CMO de {alvo} já registrado completo; nada a fazer.")
        return
    url = URL.format(ano=alvo.year)
    etag_ant, parcial_registrado, erros_seguidos = None, False, 0
    print(f"monitorando CMO de {alvo} até {limite:%H:%M} BRT, a cada {a.intervalo}s")
    while True:
        t = agora()
        try:
            h = requests.head(url, headers=UA, timeout=60)
            h.raise_for_status()
            etag, lm = h.headers.get("ETag"), _brt(h.headers.get("Last-Modified", ""))
            if etag and etag != etag_ant:
                r = requests.get(url, headers=UA, timeout=180)
                r.raise_for_status()
                max_dia, cont, completo, resumo, curvas = analisar(r.content, alvo)
                _append_csv("log.csv", {"consulta_brt": t.strftime("%Y-%m-%d %H:%M:%S"),
                                        "last_modified_brt": lm.strftime("%Y-%m-%d %H:%M:%S") if lm else "",
                                        "etag": etag.strip('"'), "ultimo_dia_no_arquivo": max_dia.isoformat(),
                                        "meias_horas_d1": json.dumps(cont, ensure_ascii=False)},
                            ["consulta_brt", "last_modified_brt", "etag", "ultimo_dia_no_arquivo", "meias_horas_d1"])
                print(t.strftime("%H:%M"), "arquivo mudou; último dia:", max_dia, cont)
                etag_ant = etag
                if resumo and (completo or not parcial_registrado):
                    linha = {"dia_cmo": alvo.isoformat(), "detectado_brt": t.strftime("%Y-%m-%d %H:%M"),
                             "last_modified_brt": lm.strftime("%Y-%m-%d %H:%M") if lm else "",
                             "completo": "sim" if completo else "não",
                             "meias_horas": json.dumps(cont, ensure_ascii=False)}
                    for s in ("SE/CO", "Sul", "Nordeste", "Norte"):
                        x = resumo.get(s, {})
                        linha[f"media_{s}"] = x.get("media", "")
                        linha[f"max_{s}"] = x.get("max", "")
                    _append_csv("historico.csv", linha, list(linha.keys()))
                    horario = curvas.pop("_horario", {})
                    with open(os.path.join(PASTA, "curvas", f"{alvo.isoformat()}.json"), "w", encoding="utf-8") as fh:
                        json.dump({"dia": alvo.isoformat(), "detectado_brt": linha["detectado_brt"],
                                   "resumo": resumo, "horario": horario, "semi_horario": curvas},
                                  fh, ensure_ascii=False, indent=1)
                    try:
                        grafico(alvo, horario, os.path.join(PASTA, "curvas", f"{alvo.isoformat()}.png"))
                    except Exception as e:  # noqa
                        print("gráfico:", e, file=sys.stderr)
                    for hh_ in range(24):
                        _append_csv("horario.csv", {"dia": alvo.isoformat(), "hora": f"{hh_:02d}",
                                                    **{s_: horario.get(s_, {}).get(hh_, "") for s_ in ORDEM}},
                                    ["dia", "hora", *ORDEM]) if completo else None
                    with open(os.path.join(PASTA, "ultimo.json"), "w", encoding="utf-8") as fh:
                        json.dump({"dia": alvo.isoformat(), **linha, "resumo": resumo}, fh, ensure_ascii=False, indent=1)
                    git_salvar(f"CMO {alvo:%d/%m} detectado {t:%H:%M}" + ("" if completo else " (parcial)"))
                    if not parcial_registrado or completo:
                        avisar(alvo, t, lm, resumo, completo, horario)
                    parcial_registrado = True
                    if completo:
                        print("CMO de D+1 completo — fim.")
                        return
        except Exception as e:  # noqa
            print(t.strftime("%H:%M"), "erro:", e, file=sys.stderr)
            erros_seguidos += 1
            if erros_seguidos in (1, 3, 10):
                _append_csv("log.csv", {"consulta_brt": t.strftime("%Y-%m-%d %H:%M:%S"), "last_modified_brt": "",
                                        "etag": "", "ultimo_dia_no_arquivo": "ERRO",
                                        "meias_horas_d1": repr(e)[:300]},
                            ["consulta_brt", "last_modified_brt", "etag", "ultimo_dia_no_arquivo", "meias_horas_d1"])
                git_salvar(f"Monitor CMO: erro na consulta ({erros_seguidos}x)")
        else:
            erros_seguidos = 0
        if agora() + dt.timedelta(seconds=a.intervalo) > limite:
            _append_csv("historico.csv" if not parcial_registrado else "log.csv",
                        {"dia_cmo": alvo.isoformat(), "detectado_brt": "", "last_modified_brt": "",
                         "completo": "não publicado até " + a.ate, "meias_horas": ""} if not parcial_registrado else
                        {"consulta_brt": agora().strftime("%Y-%m-%d %H:%M:%S"), "last_modified_brt": "", "etag": "",
                         "ultimo_dia_no_arquivo": "", "meias_horas_d1": "limite atingido sem dia completo"},
                        ["dia_cmo", "detectado_brt", "last_modified_brt", "completo", "meias_horas"] if not parcial_registrado
                        else ["consulta_brt", "last_modified_brt", "etag", "ultimo_dia_no_arquivo", "meias_horas_d1"])
            git_salvar(f"CMO {alvo:%d/%m}: limite {a.ate} atingido")
            print("limite atingido.")
            return
        time.sleep(a.intervalo)


if __name__ == "__main__":
    main()

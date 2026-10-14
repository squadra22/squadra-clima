"""Gráficos estáticos (PNG) para o PDF: geração eólica verificada e vento previsto."""
import datetime as dt

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from clima.vento import REGIOES_EOLICAS  # noqa: E402

TXT, TXT2, GRID, SURF = "#1F2933", "#52514E", "#E3E6EA", "#FFFFFF"
SERIES = {"gfs": ("#2a78d6", "GFS"), "ecmwf": ("#eb6834", "ECMWF IFS"), "aifs": ("#1baf7a", "AIFS")}
COR_SUB = "#2a78d6"


def _estilo(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=TXT2, labelsize=7.5, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def eolica_realizada(E, destino):
    serie = E.get("serie_horaria") or []
    if not serie:
        return None
    ts = [dt.datetime.strptime(p["t"], "%Y-%m-%dT%H:%M") for p in serie]
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.3), dpi=200)
    for ax, sub in zip(axs, ("Nordeste", "Sul")):
        _estilo(ax)
        y = [p.get(sub) for p in serie]
        y = [v / 1000 if v is not None else None for v in y]  # MWmed -> GWmed
        ax.plot(ts, y, color=COR_SUB, linewidth=1.2)
        m30 = (E.get("media_30d") or {}).get(sub)
        if m30:
            ax.axhline(m30 / 1000, color=TXT2, linewidth=0.9, linestyle=(0, (3, 2)))
            ax.annotate((f"média 30 dias: {m30 / 1000:.2f}" if m30 < 1000 else f"média 30 dias: {m30 / 1000:.1f}").replace(".", ","), xy=(1.0, m30 / 1000),
                        xycoords=("axes fraction", "data"), xytext=(0, 4), textcoords="offset points",
                        ha="right", fontsize=7, color=TXT2,
                        bbox=dict(boxstyle="round,pad=0.2", fc=SURF, ec="none", alpha=0.9))
        ax.set_title(f"{sub} · GWmed", fontsize=8.5, color=TXT, loc="left", fontweight="bold")
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
        ax.set_ylim(bottom=0)
    fig.tight_layout(w_pad=2)
    fig.savefig(destino, facecolor=SURF)
    plt.close(fig)
    return destino


def vento_previsto(V, destino):
    if not V:
        return None
    fig, axs = plt.subplots(1, 3, figsize=(7.2, 2.4), dpi=200, sharey=True)
    linhas_leg = []
    for ax, reg in zip(axs, REGIOES_EOLICAS):
        _estilo(ax)
        for chave, (cor, nome) in SERIES.items():
            m = V.get(chave)
            if not m:
                continue
            dias = sorted(d for d in m["diario"] if reg in m["diario"][d])
            # descarta o dia da rodada (incompleto) e dias parciais no fim
            dias = dias[1:-1] if len(dias) > 2 else dias
            xs = [dt.date.fromisoformat(d) for d in dias]
            ys = [m["diario"][d][reg] for d in dias]
            ln, = ax.plot(xs, ys, color=cor, linewidth=1.4, marker="o", markersize=2.2, label=nome)
            if ax is axs[0]:
                linhas_leg.append(ln)
        ax.set_title(reg, fontsize=8, color=TXT, loc="left", fontweight="bold")
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    axs[0].set_ylabel("m/s", fontsize=7.5, color=TXT2)
    fig.legend(handles=linhas_leg, loc="upper right", ncol=3, fontsize=7.5, frameon=False,
               labelcolor=TXT, bbox_to_anchor=(0.995, 1.02))
    fig.tight_layout(rect=(0, 0, 1, 0.92), w_pad=1.2)
    fig.savefig(destino, facecolor=SURF)
    plt.close(fig)
    return destino

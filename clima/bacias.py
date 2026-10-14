"""Bacias hidrográficas do SIN usadas nas médias de chuva.

Contornos APROXIMADOS (v1), em (lon, lat), desenhados para médias areais em
grades de 0,25°–0,5°. Servem para comparar modelos e observação de forma
consistente entre si; não reproduzem exatamente as bacias oficiais do ONS.
Para trocar por contornos oficiais, basta gravar data/bacias.geojson
(FeatureCollection com properties.nome) — ele tem prioridade sobre esta tabela.
"""
import json
import os

import numpy as np
from matplotlib.path import Path

# ordem e agrupamento usados no relatório
GRUPOS = {
    "SUL": ["Jacuí", "Uruguai", "Iguaçu"],
    "SUDESTE / CENTRO-OESTE": ["Baixo Paraná", "Alto Paraná", "Paranapanema", "Tietê",
                               "Baixo Grande", "Alto Grande", "Baixo Paranaíba", "Alto Paranaíba",
                               "Alto São Francisco", "Alto Tocantins", "Madeira"],
    "NORDESTE": ["Médio São Francisco", "Baixo São Francisco"],
    "NORTE": ["Baixo Tocantins", "Araguaia", "Xingu"],
}

# regiões agregadas para a comparação de modelos
REGIOES = {
    "Sul (Iguaçu/Uruguai/Jacuí)": ["Iguaçu", "Uruguai", "Jacuí"],
    "SE fio d'água (Paraná/Paranapanema/Tietê)": ["Baixo Paraná", "Alto Paraná", "Paranapanema", "Tietê"],
    "SE cabeceiras (Grande/Paranaíba/Alto SF)": ["Alto Grande", "Baixo Grande", "Alto Paranaíba",
                                                 "Baixo Paranaíba", "Alto São Francisco"],
    "Alto Tocantins": ["Alto Tocantins"],
    "Madeira": ["Madeira"],
    "Norte (Tocantins/Xingu)": ["Baixo Tocantins", "Araguaia", "Xingu"],
    "Nordeste (São Francisco)": ["Médio São Francisco", "Baixo São Francisco"],
}

POLIGONOS = {
    "Jacuí": [(-54.5, -28.5), (-51.5, -28.5), (-51.0, -29.5), (-51.5, -30.2), (-54.0, -30.5), (-55.0, -29.5)],
    "Uruguai": [(-50.0, -27.0), (-51.5, -26.5), (-53.7, -26.3), (-55.8, -27.5), (-56.0, -28.8),
                (-54.0, -28.6), (-51.5, -28.6), (-50.0, -28.3)],
    "Iguaçu": [(-49.3, -25.3), (-51.0, -25.3), (-52.5, -25.0), (-54.5, -25.4), (-54.0, -26.3),
               (-51.5, -26.6), (-49.5, -26.3)],
    "Baixo Paraná": [(-55.0, -23.5), (-56.5, -23.5), (-56.5, -26.5), (-54.5, -26.8), (-54.2, -24.5)],
    "Alto Paraná": [(-51.0, -20.0), (-53.0, -18.5), (-55.0, -20.5), (-55.0, -23.5), (-54.2, -24.5),
                    (-53.0, -22.6), (-51.2, -21.0)],
    "Paranapanema": [(-48.0, -23.3), (-49.5, -22.5), (-51.5, -22.4), (-53.0, -22.6), (-51.5, -23.6),
                     (-50.0, -24.5), (-48.5, -24.4)],
    "Tietê": [(-46.2, -23.4), (-47.5, -22.6), (-49.0, -21.8), (-51.0, -20.9), (-51.2, -21.6),
              (-49.5, -22.6), (-47.5, -23.6)],
    "Alto Grande": [(-44.0, -22.2), (-46.5, -22.3), (-46.8, -21.2), (-45.6, -20.2), (-44.2, -20.6)],
    "Baixo Grande": [(-46.8, -21.2), (-48.5, -21.4), (-50.9, -20.2), (-49.5, -19.6), (-47.5, -19.6),
                     (-45.6, -20.2)],
    "Alto Paranaíba": [(-46.0, -19.5), (-47.5, -17.0), (-48.5, -15.6), (-49.5, -16.5), (-48.8, -18.6),
                       (-47.5, -19.6)],
    "Baixo Paranaíba": [(-48.8, -18.6), (-49.5, -16.5), (-51.5, -17.3), (-53.0, -18.5), (-51.0, -20.0),
                        (-49.5, -19.6)],
    "Alto São Francisco": [(-43.6, -21.0), (-45.5, -20.3), (-46.3, -19.2), (-45.8, -18.0), (-44.5, -18.0),
                           (-43.6, -19.2)],
    "Médio São Francisco": [(-44.5, -18.0), (-46.5, -16.0), (-46.5, -12.0), (-44.0, -10.0), (-41.5, -10.0),
                            (-42.0, -13.0), (-43.5, -16.0)],
    "Baixo São Francisco": [(-41.5, -10.0), (-38.5, -8.5), (-36.4, -10.4), (-38.0, -10.5), (-40.0, -10.5)],
    "Alto Tocantins": [(-49.5, -16.0), (-47.0, -15.5), (-46.3, -13.0), (-47.0, -10.0), (-48.5, -10.0),
                       (-49.5, -13.0)],
    "Araguaia": [(-53.5, -18.0), (-51.0, -16.5), (-49.5, -13.0), (-48.5, -8.0), (-48.5, -5.5),
                 (-50.5, -6.0), (-51.5, -10.0), (-53.0, -14.0)],
    "Baixo Tocantins": [(-48.5, -10.0), (-46.3, -10.0), (-46.5, -6.0), (-48.0, -3.8), (-49.5, -4.0),
                        (-48.5, -5.5)],
    "Xingu": [(-54.5, -14.5), (-52.0, -13.0), (-51.5, -9.0), (-51.8, -3.5), (-53.0, -3.0), (-54.5, -6.0),
              (-55.0, -10.0)],
    "Madeira": [(-68.0, -17.0), (-63.0, -17.5), (-60.0, -14.0), (-60.5, -9.0), (-63.0, -8.0), (-66.0, -9.0),
                (-69.5, -11.0), (-69.5, -15.0)],
}

# caixa que cobre todas as bacias (usada para recortar downloads)
BBOX = {"norte": 0.0, "sul": -32.0, "oeste": -72.0, "leste": -34.0}


def carregar_poligonos(raiz="."):
    gj = os.path.join(raiz, "data", "bacias.geojson")
    if os.path.exists(gj):
        with open(gj, encoding="utf-8") as fh:
            fc = json.load(fh)
        out = {}
        for f in fc["features"]:
            geom = f["geometry"]
            coords = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0]
            out[f["properties"]["nome"]] = [tuple(c[:2]) for c in coords]
        return out
    return POLIGONOS


def ordem_bacias():
    return [b for g in GRUPOS.values() for b in g]


class Mascaras:
    """Calcula (e guarda em cache) os índices de cada bacia numa grade lat/lon."""

    def __init__(self, poligonos=None):
        self.poligonos = poligonos or carregar_poligonos()
        self._cache = {}

    def _chave(self, lats, lons):
        return (lats.shape, float(lats.flat[0]), float(lats.flat[-1]), float(lons.flat[0]), float(lons.flat[-1]))

    def pesos(self, lats, lons):
        """lats/lons: arrays 1D (um valor por ponto da grade). Retorna {bacia: (idx, w)}."""
        k = self._chave(lats, lons)
        if k in self._cache:
            return self._cache[k]
        lon180 = np.where(lons > 180, lons - 360, lons)
        sel = ((lats <= BBOX["norte"] + 1) & (lats >= BBOX["sul"] - 1) &
               (lon180 >= BBOX["oeste"] - 1) & (lon180 <= BBOX["leste"] + 1))
        base = np.nonzero(sel)[0]
        pts = np.column_stack([lon180[base], lats[base]])
        res = {}
        for nome, poly in self.poligonos.items():
            dentro = Path(poly).contains_points(pts)
            idx = base[dentro]
            if idx.size == 0:  # grade grossa: usa o ponto mais próximo do centróide
                cx, cy = np.mean([p[0] for p in poly]), np.mean([p[1] for p in poly])
                d = (pts[:, 0] - cx) ** 2 + (pts[:, 1] - cy) ** 2
                idx = base[[int(np.argmin(d))]]
            w = np.cos(np.deg2rad(lats[idx]))
            res[nome] = (idx, w / w.sum())
        self._cache[k] = res
        return res

    def medias(self, valores, lats, lons):
        """valores: array 1D alinhado com lats/lons. NaN é ignorado."""
        out = {}
        for nome, (idx, w) in self.pesos(lats, lons).items():
            v = valores[idx]
            ok = np.isfinite(v)
            out[nome] = round(float(np.sum(v[ok] * w[ok]) / np.sum(w[ok])), 1) if ok.any() else None
        return out


def agregar_regioes(por_bacia):
    """Média simples das bacias de cada região (ignora None)."""
    out = {}
    for reg, bacias in REGIOES.items():
        vals = [por_bacia.get(b) for b in bacias if por_bacia.get(b) is not None]
        out[reg] = round(sum(vals) / len(vals), 1) if vals else None
    return out

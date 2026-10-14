#!/usr/bin/env python3
"""Gerador do Relatório Diário de Clima & Hidrologia — Squadra Energia.

Uso:  python3 gerar_relatorio.py conteudo.json saida.pdf

O JSON segue o esquema abaixo (todas as chaves de seção são opcionais; seções
vazias aparecem com o aviso "Sem atualização disponível nesta edição"):
{
  "data": "14/10/2026", "dia_semana": "Quarta-feira", "edicao": "nº 001",
  "manchete": "texto",
  "kpis": [{"rotulo": "Niño 3.4", "valor": "+2,3 °C", "nota": "El Niño muito forte", "tom": "alerta|positivo|negativo|neutro"}],
  "secoes": [
     {"id": "enos", "titulo": "...", "paragrafos": ["..."], "bullets": ["..."],
      "tabela": {...} ou "tabelas": [{"titulo": "...", "colunas": [...], "linhas": [[...]], "larguras": [..], "nota": "..."}]}
  ],
  "leitura_trading": ["..."],
  "fontes": [{"titulo": "...", "url": "..."}]
}
Células com as palavras Acima / M. acima / Ext. pos / Abaixo / M. abaixo / Média
recebem cor automática. Valores de desvio iniciados por "+" ou "-" (ou "−") também.
"""
import json, os, sys, re
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, KeepTogether)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---------- identidade visual ----------
NAVY = colors.HexColor("#0B2545")
NAVY_2 = colors.HexColor("#13315C")
ACCENT = colors.HexColor("#1B9AAA")
INK = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#6B7785")
RULE = colors.HexColor("#D9DEE4")
ZEBRA = colors.HexColor("#F4F6F8")
TONS = {
    "alerta": colors.HexColor("#C2410C"),
    "negativo": colors.HexColor("#B91C1C"),
    "positivo": colors.HexColor("#1D4ED8"),
    "neutro": NAVY,
}
CAT = [  # (regex, fundo, texto)
    (r"ext\.?\s*pos|extremo positivo", "#EDE4FB", "#6B21A8"),
    (r"m\.?\s*acima|muito acima", "#DCE8FB", "#1E3A8A"),
    (r"\bacima\b", "#E6F0FD", "#1D4ED8"),
    (r"m\.?\s*abaixo|muito abaixo|ext\.?\s*neg", "#FBE2E2", "#991B1B"),
    (r"\babaixo\b", "#FDEBDD", "#C2410C"),
    (r"\bm[ée]dia\b", "#EEF0F2", "#374151"),
]

def _fontes():
    base = "/usr/share/fonts/truetype/crosextra/"
    f = {"r": base + "Carlito-Regular.ttf", "b": base + "Carlito-Bold.ttf",
         "i": base + "Carlito-Italic.ttf"}
    if all(os.path.exists(p) for p in f.values()):
        pdfmetrics.registerFont(TTFont("Sq", f["r"]))
        pdfmetrics.registerFont(TTFont("Sq-B", f["b"]))
        pdfmetrics.registerFont(TTFont("Sq-I", f["i"]))
        pdfmetrics.registerFontFamily("Sq", normal="Sq", bold="Sq-B", italic="Sq-I", boldItalic="Sq-B")
        return "Sq", "Sq-B", "Sq-I"
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"

F, FB, FI = _fontes()

S = {
    "manchete": ParagraphStyle("m", fontName=FB, fontSize=12.5, leading=16, textColor=NAVY),
    "h2": ParagraphStyle("h2", fontName=FB, fontSize=12, leading=15, textColor=NAVY, spaceBefore=4),
    "p": ParagraphStyle("p", fontName=F, fontSize=9.6, leading=13, textColor=INK),
    "bul": ParagraphStyle("b", fontName=F, fontSize=9.6, leading=13, textColor=INK, leftIndent=10, bulletIndent=0),
    "cel": ParagraphStyle("c", fontName=F, fontSize=8.6, leading=10.5, textColor=INK),
    "celc": ParagraphStyle("cc", fontName=F, fontSize=8.6, leading=10.5, textColor=INK, alignment=TA_CENTER),
    "head": ParagraphStyle("h", fontName=FB, fontSize=8.4, leading=10, textColor=colors.white, alignment=TA_CENTER),
    "headl": ParagraphStyle("hl", fontName=FB, fontSize=8.4, leading=10, textColor=colors.white),
    "nota": ParagraphStyle("n", fontName=FI, fontSize=8, leading=10, textColor=MUTED),
    "kv": ParagraphStyle("kv", fontName=FB, fontSize=15, leading=18, alignment=TA_LEFT),
    "kl": ParagraphStyle("kl", fontName=FB, fontSize=7.6, leading=9, textColor=MUTED),
    "kn": ParagraphStyle("kn", fontName=F, fontSize=8, leading=10, textColor=INK),
    "fonte": ParagraphStyle("f", fontName=F, fontSize=8, leading=10.5, textColor=INK, leftIndent=10, bulletIndent=0),
}

def esc(t):
    t = str(t)
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def md(t):
    """**negrito** e *itálico* simples."""
    t = esc(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"<i>\1</i>", t)
    return t

# ---------- página ----------
class Doc(BaseDocTemplate):
    def __init__(self, path, meta):
        super().__init__(path, pagesize=A4, leftMargin=16*mm, rightMargin=16*mm,
                         topMargin=36*mm, bottomMargin=16*mm,
                         title=f"Squadra Energia — Clima & Hidrologia {meta.get('data','')}",
                         author="Squadra Energia")
        self.meta = meta
        w, h = A4
        first = Frame(16*mm, 16*mm, w-32*mm, h-16*mm-44*mm, id="f1")
        later = Frame(16*mm, 16*mm, w-32*mm, h-16*mm-24*mm, id="f2")
        self.addPageTemplates([PageTemplate("capa", [first], onPage=self._capa),
                               PageTemplate("int", [later], onPage=self._interna)])

    def _rodape(self, c):
        w, _ = A4
        c.setStrokeColor(RULE); c.setLineWidth(0.6)
        c.line(16*mm, 11.5*mm, w-16*mm, 11.5*mm)
        c.setFont(F, 7.5); c.setFillColor(MUTED)
        c.drawString(16*mm, 7.5*mm, "Squadra Energia · Mesa de Trading · Uso interno")
        c.drawRightString(w-16*mm, 7.5*mm, f"Página {c.getPageNumber()}")
        c.drawCentredString(w/2, 7.5*mm, "Não constitui recomendação de compra ou venda")

    def _capa(self, c, d):
        w, h = A4
        c.saveState()
        c.setFillColor(NAVY); c.rect(0, h-40*mm, w, 40*mm, stroke=0, fill=1)
        c.setFillColor(ACCENT); c.rect(0, h-41.2*mm, w, 1.2*mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FB, 11); c.drawString(16*mm, h-13*mm, "SQUADRA")
        c.setFont(F, 11); c.setFillColor(colors.HexColor("#9FD8DF"))
        c.drawString(16*mm + pdfmetrics.stringWidth("SQUADRA ", FB, 11), h-13*mm, "ENERGIA")
        c.setFillColor(colors.white); c.setFont(FB, 20)
        c.drawString(16*mm, h-25*mm, "Relatório Diário · Clima & Hidrologia")
        c.setFont(F, 10); c.setFillColor(colors.HexColor("#C9D6E3"))
        sub = " · ".join(x for x in [self.meta.get("dia_semana"), self.meta.get("data"),
                                     ("Edição " + self.meta["edicao"]) if self.meta.get("edicao") else None] if x)
        c.drawString(16*mm, h-32.5*mm, sub)
        c.setFont(F, 8); c.drawRightString(w-16*mm, h-13*mm, "Mesa de Trading de Energia")
        c.restoreState(); self._rodape(c)

    def _interna(self, c, d):
        w, h = A4
        c.saveState()
        c.setFillColor(NAVY); c.rect(0, h-14*mm, w, 14*mm, stroke=0, fill=1)
        c.setFillColor(ACCENT); c.rect(0, h-14.8*mm, w, 0.8*mm, stroke=0, fill=1)
        c.setFillColor(colors.white); c.setFont(FB, 9)
        c.drawString(16*mm, h-8.8*mm, "SQUADRA ENERGIA")
        c.setFont(F, 9)
        c.drawRightString(w-16*mm, h-8.8*mm, f"Clima & Hidrologia · {self.meta.get('data','')}")
        c.restoreState(); self._rodape(c)

# ---------- blocos ----------
def cor_celula(txt):
    t = str(txt).strip().lower()
    for rx, bg, fg in CAT:
        if re.search(rx, t):
            return colors.HexColor(bg), colors.HexColor(fg)
    return None, None

def cor_desvio(txt):
    t = str(txt).strip()
    if re.match(r"^\+\s*\d", t):
        return colors.HexColor("#1D4ED8")
    if re.match(r"^[-−–]\s*\d", t):
        return colors.HexColor("#C2410C")
    return None

def tabela(spec, largura):
    cols = spec.get("colunas", [])
    linhas = spec.get("linhas", [])
    n = len(cols)
    if spec.get("larguras"):
        tot = sum(spec["larguras"]); ws = [largura * x / tot for x in spec["larguras"]]
    else:
        ws = [largura * 0.26] + [largura * 0.74 / max(n-1, 1)] * (n-1) if n > 1 else [largura]
    data = [[Paragraph(esc(c), S["headl"] if i == 0 else S["head"]) for i, c in enumerate(cols)]]
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY_2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for r, linha in enumerate(linhas, start=1):
        row = []
        grupo = len(linha) == 1  # linha de agrupamento (ex.: "SUDESTE")
        if grupo:
            row = [Paragraph(f"<b>{esc(linha[0])}</b>", S["cel"])] + [""] * (n-1)
            estilo += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), colors.HexColor("#E3EAF2"))]
            data.append(row); continue
        if r % 2 == 0:
            estilo.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
        for c_i, val in enumerate(linha):
            bg, fg = cor_celula(val) if c_i > 0 else (None, None)
            dc = cor_desvio(val) if c_i > 0 else None
            st = S["cel"] if c_i == 0 else S["celc"]
            txt = md(val)
            if fg is not None:
                txt = f'<font color="#{fg.hexval()[2:]}"><b>{txt}</b></font>'
                estilo.append(("BACKGROUND", (c_i, r), (c_i, r), bg))
            elif dc is not None:
                txt = f'<font color="#{dc.hexval()[2:]}"><b>{txt}</b></font>'
            row.append(Paragraph(txt, st))
        row += [""] * (n - len(row))
        data.append(row)
    t = Table(data, colWidths=ws, repeatRows=1)
    t.setStyle(TableStyle(estilo))
    out = [t]
    if spec.get("nota"):
        out += [Spacer(1, 2.5), Paragraph(md(spec["nota"]), S["nota"])]
    return out

def kpis(lista, largura):
    if not lista:
        return []
    n = min(len(lista), 4)
    w = largura / n
    cells = []
    for k in lista[:4]:
        tom = TONS.get(k.get("tom", "neutro"), NAVY)
        st = ParagraphStyle("kvx", parent=S["kv"], textColor=tom)
        cells.append([Paragraph(esc(k.get("rotulo", "")).upper(), S["kl"]),
                      Paragraph(esc(k.get("valor", "")), st),
                      Paragraph(md(k.get("nota", "")), S["kn"])])
    t = Table([cells], colWidths=[w]*n)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("BACKGROUND", (0, 0), (-1, -1), ZEBRA),
          ("LINEBEFORE", (0, 0), (0, 0), 2.2, ACCENT),
          ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
          ("LEFTPADDING", (0, 0), (-1, -1), 8)]
    for i in range(1, n):
        st.append(("LINEBEFORE", (i, 0), (i, 0), 2.2, ACCENT))
    t.setStyle(TableStyle(st))
    return [t]

def titulo_secao(num, txt):
    t = Table([[Paragraph(f'<font color="#{ACCENT.hexval()[2:]}">{num:02d}</font>&nbsp;&nbsp;{esc(txt)}', S["h2"])]],
              colWidths=["100%"])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.8, NAVY),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t

def montar(conteudo, saida):
    doc = Doc(saida, conteudo)
    larg = doc.width
    story = []
    from reportlab.platypus import NextPageTemplate
    story.append(NextPageTemplate("int"))
    if conteudo.get("manchete"):
        box = Table([[Paragraph(md(conteudo["manchete"]), S["manchete"])]], colWidths=[larg])
        box.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, 0), 3, ACCENT),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                 ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story += [box, Spacer(1, 8)]
    story += kpis(conteudo.get("kpis", []), larg)
    story.append(Spacer(1, 6))

    num = 0
    for sec in conteudo.get("secoes", []):
        num += 1
        bloco = [Spacer(1, 8), titulo_secao(num, sec.get("titulo", "")), Spacer(1, 5)]
        vazio = True
        for p in sec.get("paragrafos", []):
            bloco += [Paragraph(md(p), S["p"]), Spacer(1, 4)]; vazio = False
        tabs = sec.get("tabelas") or ([sec["tabela"]] if sec.get("tabela") else [])
        for tb in tabs:
            if tb.get("titulo"):
                bloco += [Spacer(1, 3), Paragraph(f"<b>{esc(tb['titulo'])}</b>", S["p"])]
            bloco += [Spacer(1, 3)] + tabela(tb, larg) + [Spacer(1, 4)]; vazio = False
        for im in sec.get("imagens", []):
            if os.path.exists(im.get("caminho", "")):
                from reportlab.platypus import Image as RLImage
                from reportlab.lib.utils import ImageReader
                iw, ih = ImageReader(im["caminho"]).getSize()
                bloco += [Spacer(1, 3), RLImage(im["caminho"], width=larg, height=larg * ih / iw)]
                if im.get("legenda"):
                    bloco += [Spacer(1, 2), Paragraph(md(im["legenda"]), S["nota"])]
                bloco.append(Spacer(1, 4)); vazio = False
        for b in sec.get("bullets", []):
            bloco += [Paragraph(md(b), S["bul"], bulletText="•"), Spacer(1, 2)]; vazio = False
        if vazio:
            bloco.append(Paragraph("Sem atualização disponível nesta edição.", S["nota"]))
        story.append(KeepTogether(bloco[:5]))
        story += bloco[5:]

    if conteudo.get("leitura_trading"):
        num += 1
        bloco = [Spacer(1, 8), titulo_secao(num, "Leitura para o trading"), Spacer(1, 5)]
        itens = [[Paragraph(md(x), S["bul"], bulletText="•")] for x in conteudo["leitura_trading"]]
        t = Table(itens, colWidths=[larg])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF6F7")),
                               ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT),
                               ("LEFTPADDING", (0, 0), (-1, -1), 10),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        bloco += [t, Spacer(1, 3),
                  Paragraph("Interpretação da mesa a partir das fontes citadas; não constitui recomendação de compra ou venda.", S["nota"])]
        story.append(KeepTogether(bloco))

    if conteudo.get("fontes"):
        num += 1
        bloco = [Spacer(1, 8), titulo_secao(num, "Fontes"), Spacer(1, 4)]
        for f in conteudo["fontes"]:
            url = f.get("url", "")
            txt = f'{esc(f.get("titulo",""))}' + (f' — <link href="{esc(url)}" color="#1B9AAA">{esc(url)}</link>' if url else "")
            bloco.append(Paragraph(txt, S["fonte"], bulletText="–"))
        story += bloco
    doc.build(story)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("uso: gerar_relatorio.py conteudo.json saida.pdf")
    with open(sys.argv[1], encoding="utf-8") as fh:
        montar(json.load(fh), sys.argv[2])
    print("ok:", sys.argv[2])

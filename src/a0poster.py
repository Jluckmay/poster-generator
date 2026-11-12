"""Renderização para template baseado em `a0poster` (UZH - Universidade de Zurique / LiRI)."""

from __future__ import annotations

from typing import Any, Dict, List

from .config import POSTER_SIZES
from .i18n import labels_for
from .templates import TEMPLATES

_UNNUMBERED = {"references", "acknowledgments"}


def _pt(v: float) -> str:
    return f"{v:.2f}"


def build_a0poster_tex(poster: Dict[str, Any], images: Dict[str, str]) -> str:
    from .latex import (
        _QR_OK, _hex_to_latex, _images_to_latex, _inline, escape_latex,
        references_to_latex, text_to_latex,
    )

    labels = labels_for(poster["language"])
    tpl = TEMPLATES[poster["template"]]
    c1, c2, c3 = tpl["colors"]
    bg_color = tpl.get("bg", "FFFFFF")
    if poster.get("colors"):
        colors = poster["colors"]
        if colors.get("accent"):
            c1 = colors["accent"]
        if colors.get("subtitle"):
            c2 = colors["subtitle"]
        if colors.get("title"):
            c3 = colors["title"]
        if colors.get("bg"):
            bg_color = colors["bg"]
    elif poster.get("accent"):
        c1 = c2 = poster["accent"]

    has_custom_bg = bool(poster.get("colors") and poster["colors"].get("bg"))
    page_bg_tex = f"\n{_hex_to_latex('uzhBg', bg_color)}\n\\pagecolor{{uzhBg}}" if has_custom_bg else ""

    paper_key = poster.get("paper", "a0")
    orient = poster.get("orientation", "portrait")
    cols = max(1, poster.get("columns", 2))
    w, h = POSTER_SIZES.get(paper_key, POSTER_SIZES["a0"])["cm"]
    if orient == "landscape":
        w, h = h, w
    a0_paper_opt = paper_key if paper_key in ("a0", "a1", "a2") else "a0"

    sections = [
        {**sec, "images": [{"file": images[i["path"]], "caption": i["caption"]} for i in sec["images"] if i["path"] in images]}
        for sec in poster["sections"]
    ]

    body: List[str] = []
    counter, fig = 0, [0]
    for idx, sec in enumerate(sections):
        title = _inline(sec["title"])
        if sec["id"] not in _UNNUMBERED:
            counter += 1
            title = f"{counter}. {title}"
        text = references_to_latex(sec["content"], small=True) if sec["id"] == "references" else text_to_latex(sec["content"])
        img_tex = _images_to_latex(sec["images"], labels["figure"], fig, r"\large")
        body.append(
            f"\\section{{{title}}}\n"
            f"{text}\n"
            f"{img_tex}\n"
        )

    qr = ""
    if _QR_OK.match(poster.get("url", "")):
        qr = f"\\begin{{center}}\\qrcode[height=3.5cm]{{{poster['url']}}}\\end{{center}}"


    authors = escape_latex(poster.get("authors", "")).replace("\n", ", ")
    affil_bits = [escape_latex(ln.strip()) for ln in poster.get("affiliations", "").split("\n") if ln.strip()]
    if poster.get("email"):
        affil_bits.insert(0, escape_latex(poster["email"]))
    affil = "\\\\".join(affil_bits)

    header_logos = [images[p] for p in poster.get("logos_header", []) if p in images]
    logo_boxes = ""
    if header_logos:
        cells = [f"\\includegraphics[height=5cm,keepaspectratio]{{{f}}}" for f in header_logos]
        logo_boxes = "\\hfill " + " \\qquad ".join(cells)

    title_text = _inline(poster.get('title', '')) or '~'

    return f"""\\documentclass[{a0_paper_opt},{orient}]{{a0poster}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[T1]{{fontenc}}
\\usepackage[{labels['babel']}]{{babel}}
\\usepackage{{geometry}}
\\geometry{{paperwidth={w:.1f}cm, paperheight={h:.1f}cm, left=4cm, top=4cm, right=4cm, bottom=4cm}}
\\usepackage{{multicol}}
\\usepackage{{amsmath,amssymb}}
\\usepackage{{graphicx}}
\\usepackage{{qrcode}}
\\usepackage{{xcolor}}
\\usepackage{{titlesec}}
\\usepackage{{booktabs,array,tikz}}
\\usetikzlibrary{{arrows.meta,positioning,shapes.geometric,fit}}

{_hex_to_latex('uzhAccent', c1)}
{_hex_to_latex('uzhDark', c2)}{page_bg_tex}

\\titleformat{{\\section}}
  {{\\huge\\bfseries\\color{{uzhAccent}}}}
  {{\\color{{uzhAccent}}\\thesection.}}
  {{1em}}
  {{\\color{{uzhAccent}}}}
  [\\vspace{{-0.3em}}\\textcolor{{uzhAccent}}{{\\rule{{\\linewidth}}{{2pt}}}}]

\\begin{{document}}

\\begin{{minipage}}{{0.75\\linewidth}}
  {{\\fontsize{{48pt}}{{56pt}}\\selectfont \\textbf{{{title_text}}}\\par\\vspace{{0.8cm}}}}
  {{\\fontsize{{28pt}}{{34pt}}\\selectfont \\textbf{{{authors}}}}}\\par\\vspace{{0.4cm}}
  {{\\fontsize{{22pt}}{{28pt}}\\selectfont \\textcolor{{uzhDark}}{{{affil}}}}}\\par
\\end{{minipage}}%
\\begin{{minipage}}{{0.25\\linewidth}}
  \\raggedleft
  {logo_boxes}
\\end{{minipage}}

\\vspace{{1.5cm}}
\\textcolor{{uzhAccent}}{{\\rule{{\\linewidth}}{{4pt}}}}
\\vspace{{1cm}}

\\begin{{multicols}}{{{cols}}}
{chr(10).join(body)}
\\end{{multicols}}

\\end{{document}}
"""

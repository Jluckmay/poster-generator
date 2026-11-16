"""Renderização para template baseado em `a0poster` (UZH - Universidade de Zurique / LiRI)."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .config import POSTER_SIZES
from .i18n import labels_for
from .templates import TEMPLATES

_UNNUMBERED = {"references", "acknowledgments"}


def _pt(v: float) -> str:
    return f"{v:.2f}"


def _clean_title(t: str) -> str:
    return re.sub(r"^\s*\d+[\.\-\)]\s*", "", str(t or "")).strip()


def build_a0poster_tex(poster: Dict[str, Any], images: Dict[str, str]) -> str:
    from .latex import (
        _QR_OK, _hex_to_latex, _images_to_latex, _inline, escape_latex,
        references_to_latex, split_columns, text_to_latex,
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
    cols = max(1, min(4, poster.get("columns", 2)))
    w, h = POSTER_SIZES.get(paper_key, POSTER_SIZES["a0"])["cm"]
    if orient == "landscape":
        w, h = h, w
    a0_paper_opt = paper_key if paper_key in ("a0", "a1", "a2") else "a0"

    # Escala proporcional de fontes de acordo com as dimensões do papel
    scale = (min(w, h) / 84.1)
    title_fs = max(46, int(64 * scale))
    author_fs = max(24, int(34 * scale))
    meta_fs = max(18, int(24 * scale))
    sec_title_fs = max(28, int(38 * scale))
    body_fs = max(21, int(30 * scale))
    body_lh = int(body_fs * 1.35)

    sections = [
        {**sec, "images": [{"file": images[i["path"]], "caption": i["caption"]} for i in sec["images"] if i["path"] in images]}
        for sec in poster["sections"]
    ]

    body_cards: List[str] = []
    counter, fig = 0, [0]
    for idx, sec in enumerate(sections):
        raw_title = sec.get("title") or sec.get("id") or "Section"
        clean_title = _clean_title(raw_title)
        is_ref = sec["id"] in _UNNUMBERED or bool(re.search(r"refer[eê]nc", raw_title, re.IGNORECASE))
        if sec["id"] == "references":
            clean_title = labels.get("references", clean_title)
        if not is_ref:
            counter += 1
            display_title = f"{counter}. {clean_title}"
        else:
            display_title = clean_title

        if is_ref:
            text = references_to_latex(sec["content"], small=False)
            img_tex = ""
        else:
            placed_indices = set()
            text = text_to_latex(sec["content"], sec.get("images"), labels["figure"], fig, placed_indices)
            unplaced = [im for i, im in enumerate(sec.get("images", [])) if i not in placed_indices]
            img_tex = _images_to_latex(unplaced, labels["figure"], fig, r"\large") if unplaced else ""

        # Cartão estilizado com faixa lateral esquerda e fundo idêntico ao preview (.draft-block da UZH)
        body_cards.append(
            f"\\noindent\\begin{{minipage}}{{\\linewidth}}\n"
            f"\\vspace{{0.35cm}}\n"
            f"\\colorbox{{uzhCardBg}}{{\\parbox{{\\dimexpr\\linewidth-2\\fboxsep\\relax}}{{\n"
            f"  \\vspace{{0.35cm}}\n"
            f"  \\hbox{{\\textcolor{{uzhAccent}}{{\\vrule width 5pt}}\\hspace{{14pt}}\\begin{{minipage}}{{\\dimexpr\\linewidth-5pt-28pt\\relax}}\n"
            f"    \\vspace{{0.15cm}}\n"
            f"    {{\\color{{uzhAccent}}\\bfseries\\fontsize{{{sec_title_fs}pt}}{{{int(sec_title_fs * 1.25)}pt}}\\selectfont \\MakeUppercase{{{escape_latex(display_title)}}}}}\\par\\vspace{{0.35cm}}\n"
            f"    {{\\color{{uzhDark}}\\fontsize{{{body_fs}pt}}{{{body_lh}pt}}\\selectfont\n"
            f"      {text}\n"
            f"      {img_tex}\n"
            f"    }}\\par\\vspace{{0.25cm}}\n"
            f"  \\end{{minipage}}}}\n"
            f"  \\vspace{{0.35cm}}\n"
            f"}}}}\n"
            f"\\vspace{{0.4cm}}\n"
            f"\\end{{minipage}}\n"
        )

    # Distribuição em colunas por blocos (sem quebra de seções no meio)
    cols_split = split_columns(body_cards, cols)
    col_width_factor = (0.98 - (cols - 1) * 0.03) / cols
    col_tex = []
    for c in cols_split:
        col_tex.append(
            f"\\begin{{minipage}}[t]{{{col_width_factor:.3f}\\linewidth}}\n"
            + "".join(c)
            + "\\end{minipage}"
        )
    columns_body = " \\hfill ".join(col_tex)

    authors = escape_latex(poster.get("authors", "")).replace("\n", ", ")
    affil_bits = [escape_latex(ln.strip()) for ln in poster.get("affiliations", "").split("\n") if ln.strip()]
    if poster.get("email"):
        affil_bits.insert(0, escape_latex(poster["email"]))
    affil = "\\\\".join(affil_bits)

    header_logos = [images[p] for p in poster.get("logos_header", []) if p in images]
    logo_boxes = ""
    if header_logos:
        cells = [f"\\includegraphics[height={_pt(5 * scale)}cm,keepaspectratio]{{{f}}}" for f in header_logos]
        logo_boxes = " \\qquad ".join(cells)

    footer_logos = [images[p] for p in poster.get("logos_footer", []) if p in images]
    footer_tex = ""
    if footer_logos:
        h_cm = f"{_pt(4.5 * scale)}cm"
        if len(footer_logos) == 1:
            f_boxes = f"\\hfill \\includegraphics[height={h_cm},keepaspectratio]{{{footer_logos[0]}}} \\hfill\\null"
        else:
            f_boxes = " \\hfill ".join(f"\\includegraphics[height={h_cm},keepaspectratio]{{{f}}}" for f in footer_logos)
        footer_tex = (
            f"\\vfill\n"
            f"\\textcolor{{uzhAccent}}{{\\rule{{\\linewidth}}{{3pt}}}}\\par\\vspace{{0.5cm}}\n"
            f"\\noindent {f_boxes}\n"
        )

    title_text = _inline(poster.get('title', '')) or '~'

    return f"""\\documentclass[{a0_paper_opt},{orient}]{{a0poster}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[T1]{{fontenc}}
\\usepackage[{labels['babel']}]{{babel}}
\\usepackage[scaled=0.92]{{helvet}}
\\renewcommand{{\\familydefault}}{{\\sfdefault}}
\\usepackage{{geometry}}
\\geometry{{paperwidth={w:.1f}cm, paperheight={h:.1f}cm, left=3cm, top=3cm, right=3cm, bottom=3cm}}
\\usepackage{{amsmath,amssymb}}
\\usepackage{{graphicx}}
\\usepackage{{qrcode}}
\\usepackage[table]{{xcolor}}
\\usepackage{{colortbl}}
\\usepackage{{booktabs,array,tikz}}
\\usetikzlibrary{{arrows.meta,positioning,shapes.geometric,fit,calc}}

{_hex_to_latex('uzhAccent', c1)}
{_hex_to_latex('colorOne', c1)}
{_hex_to_latex('colorTwo', c2)}
{_hex_to_latex('colorThree', c3)}
{_hex_to_latex('uzhDark', c2)}{page_bg_tex}

\\definecolor{{tableHead}}{{HTML}}{{F1F5F9}}
\\definecolor{{tableLine}}{{HTML}}{{334155}}
\\definecolor{{diagFrame}}{{HTML}}{{CBD5E1}}
\\definecolor{{uzhCardBg}}{{HTML}}{{F8FAFC}}

\\setlength{{\\fboxsep}}{{14pt}}
\\setlength{{\\fboxrule}}{{1.8pt}}

\\begin{{document}}

\\noindent
\\begin{{minipage}}[t]{{0.62\\linewidth}}
  {{\\fontsize{{{title_fs}pt}}{{{int(title_fs * 1.15)}pt}}\\selectfont \\textbf{{\\color{{uzhAccent}} {title_text}}}\\par\\vspace{{0.5cm}}}}
  {{\\fontsize{{{author_fs}pt}}{{{int(author_fs * 1.25)}pt}}\\selectfont \\textbf{{\\color{{uzhDark}} {authors}}}\\par\\vspace{{0.3cm}}}}
  {{\\fontsize{{{meta_fs}pt}}{{{int(meta_fs * 1.3)}pt}}\\selectfont \\color{{gray!80!black}} {affil}\\par}}
\\end{{minipage}}%
\\hfill
\\begin{{minipage}}[t]{{0.36\\linewidth}}
  \\raggedleft
  {logo_boxes}
\\end{{minipage}}

\\vspace{{0.8cm}}
\\textcolor{{uzhAccent}}{{\\rule{{\\linewidth}}{{4.5pt}}}}
\\vspace{{0.8cm}}

\\noindent
{columns_body}

{footer_tex}
\\end{{document}}
"""

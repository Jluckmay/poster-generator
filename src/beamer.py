"""Renderização para template baseado em Beamer Poster (TU Delft)."""

from __future__ import annotations

from typing import Any, Dict, List

from .config import POSTER_SIZES
from .i18n import labels_for
from .templates import TEMPLATES

_UNNUMBERED = {"references", "acknowledgments"}


def build_beamer_tex(poster: Dict[str, Any], images: Dict[str, str]) -> str:
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
    block_body_bg = "tudBg" if has_custom_bg else "white"

    paper_key = poster.get("paper", "a0")
    orient = poster.get("orientation", "portrait")
    cols_count = max(1, poster.get("columns", 2))
    w, h = POSTER_SIZES.get(paper_key, POSTER_SIZES["a0"])["cm"]
    if orient == "landscape":
        w, h = h, w

    if paper_key in ("a0", "a1", "a2"):
        beamer_opts = f"orientation={orient},size={paper_key},scale=1.0"
    else:
        beamer_opts = f"orientation={orient},size=custom,width={w:.1f},height={h:.1f},scale=1.0"

    sections = [
        {**sec, "images": [{"file": images[i["path"]], "caption": i["caption"]} for i in sec["images"] if i["path"] in images]}
        for sec in poster["sections"]
    ]

    qr = ""
    if _QR_OK.match(poster.get("url", "")):
        qr = f"\\begin{{center}}\\qrcode[height=3.5cm]{{{poster['url']}}}\\end{{center}}"


    cols = split_columns(sections, cols_count)
    col_width = f"{0.96 / len(cols):.3f}\\textwidth"
    col_blocks: List[str] = []
    counter, fig = 0, [0]

    for ci, col in enumerate(cols):
        blocks_in_col: List[str] = []
        for sec in col:
            title = _inline(sec["title"])
            if sec["id"] not in _UNNUMBERED:
                counter += 1
                title = f"{counter}. {title}"
            if sec["id"] == "references":
                text = references_to_latex(sec["content"], small=True)
            else:
                text = text_to_latex(sec["content"])

            img_tex = _images_to_latex(sec["images"], labels["figure"], fig, "\\small")
            blocks_in_col.append(
                f"  \\begin{{block}}{{{title}}}\n"
                f"    {text}\n"
                f"    {img_tex}\n"
                f"  \\end{{block}}\n"
            )
        col_blocks.append(
            f"\\begin{{column}}{{{col_width}}}\n"
            + "".join(blocks_in_col)
            + "\\end{column}\n"
        )

    authors = escape_latex(poster.get("authors", "")).replace("\n", ", ")
    affil_bits = [escape_latex(ln.strip()) for ln in poster.get("affiliations", "").split("\n") if ln.strip()]
    if poster.get("email"):
        affil_bits.insert(0, escape_latex(poster["email"]))
    affil = "\\\\".join(affil_bits)

    header_logos = [images[p] for p in poster.get("logos_header", []) if p in images]
    logo_boxes = ""
    if header_logos:
        cells = [f"\\includegraphics[height=3.5cm,keepaspectratio]{{{f}}}" for f in header_logos]
        logo_boxes = "\\\\ \\vspace{0.5cm} " + " \\qquad ".join(cells)

    return f"""\\documentclass{{beamer}}
\\usepackage[{beamer_opts}]{{beamerposter}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[T1]{{fontenc}}
\\usepackage[{labels['babel']}]{{babel}}
\\usepackage{{amsmath,amssymb}}
\\usepackage{{graphicx}}
\\usepackage{{qrcode}}
\\usepackage{{xcolor}}
\\usepackage{{booktabs,array,tikz}}
\\usetikzlibrary{{arrows.meta,positioning,shapes.geometric,fit}}

\\usetheme{{Madrid}}
{_hex_to_latex('tudBlue', c1)}
{_hex_to_latex('tudDark', c2)}
{_hex_to_latex('tudBg', bg_color)}

\\setbeamercolor{{structure}}{{fg=tudBlue}}
\\setbeamercolor{{background canvas}}{{bg=tudBg}}
\\setbeamercolor{{block title}}{{bg=tudBlue,fg=white}}
\\setbeamercolor{{block body}}{{bg={block_body_bg},fg=black}}

\\title{{{_inline(poster.get('title', '')) or '~'}}}
\\author{{{authors}}}
\\institute{{{affil}{logo_boxes}}}

\\begin{{document}}
\\begin{{frame}}[t]
\\maketitle
\\vfill
\\begin{{columns}}[t]
{''.join(col_blocks)}
\\end{{columns}}
\\end{{frame}}
\\end{{document}}
"""

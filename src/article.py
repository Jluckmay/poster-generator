"""Renderização para templates baseados em `article` + `multicols` (ex.: DCC/UFMG)."""

from __future__ import annotations

from typing import Any, Dict, List

from .config import POSTER_SIZES
from .i18n import labels_for
from .templates import TEMPLATES

_UNNUMBERED = {"references", "acknowledgments"}


def _pt(v: float) -> str:
    return f"{v:.2f}"


def _fs(size: float, scale: float, lead: float = 1.25) -> str:
    return f"\\fontsize{{{_pt(size * scale)}}}{{{_pt(size * scale * lead)}}}\\selectfont"


def _logo(file: str, width: str, height_cm: float) -> str:
    return (
        f"\\begin{{minipage}}[c]{{{width}\\textwidth}}\\centering"
        f"\\includegraphics[width=\\linewidth,height={_pt(height_cm)}cm,keepaspectratio]{{{file}}}"
        f"\\end{{minipage}}"
    )


def _logo_row(files: List[str], height_cm: float, header: bool) -> str:
    if not files:
        return ""
    n = len(files)
    width = "0.22" if header else ("0.2" if n <= 4 else "0.17")
    cells = [_logo(f, width, height_cm) for f in files]
    if header:
        return "\\noindent" + "\\hfill".join(cells) + "\\par\n"
    if n == 1:
        return "\\noindent\\hfill" + cells[0] + "\\hfill\\null\\par\n"
    return "\\noindent" + "\\hfill".join(cells) + "\\par\n"


def article_dims(poster: Dict[str, Any]) -> tuple[float, float]:
    w, h = POSTER_SIZES[poster["paper"]]["cm"]
    return (h, w) if poster["orientation"] == "landscape" else (w, h)


def build_article_tex(poster: Dict[str, Any], images: Dict[str, str]) -> str:
    from .latex import (  # import tardio: evita ciclo
        _QR_OK, _hex_to_latex, _images_to_latex, _inline, escape_latex,
        references_to_latex, text_to_latex,
    )

    labels = labels_for(poster["language"])
    tpl = TEMPLATES[poster["template"]]
    c1, c2, c3 = tpl["colors"]
    if poster.get("colors") and poster["colors"].get("accent"):
        c1 = poster["colors"]["accent"]
    elif poster.get("accent"):
        c1 = poster["accent"]
    width, height = article_dims(poster)
    fit = float(poster.get("_fit") or 1.0)
    s = (min(width, height) / 60.0) * fit  # escala relativa ao modelo 60x90 cm
    cm = lambda v: f"{_pt(v * s)}cm"  # noqa: E731
    cap = _fs(24, s)

    sections = [
        {**sec, "images": [{"file": images[i["path"]], "caption": i["caption"]} for i in sec["images"] if i["path"] in images]}
        for sec in poster["sections"]
    ]

    body: List[str] = []
    counter, fig = 0, [0]
    for idx, sec in enumerate(sections):
        if idx:
            body.append(f"\\noindent\\textcolor{{accent}}{{\\rule{{\\linewidth}}{{{_pt(5 * s)}pt}}}}\\par\\vspace{{{cm(0.5)}}}")
        title = _inline(sec["title"])
        if sec["id"] not in _UNNUMBERED:
            counter += 1
            title = f"{counter}. {title}"
        text = references_to_latex(sec["content"], small=False) if sec["id"] == "references" else text_to_latex(sec["content"])
        if sec["id"] == "references":
            text = f"{{{_fs(24, s)}{text}}}"
        body.append(
            f"\\Needspace{{{cm(8)}}}\\noindent\\textcolor{{accent}}{{{_fs(40, s)}\\textbf{{\\MakeUppercase{{{title}}}}}}}\\par\\vspace{{{cm(1)}}}\n"
            f"{text}\n{_images_to_latex(sec['images'], labels['figure'], fig, cap)}\n\\vspace{{{cm(1)}}}"
        )


    header_logos = [images[p] for p in poster["logos_header"] if p in images]
    footer_logos = [images[p] for p in poster["logos_footer"] if p in images]
    authors = escape_latex(poster["authors"]).replace("\n", ", ")
    affil_bits = [escape_latex(ln.strip()) for ln in poster["affiliations"].split("\n") if ln.strip()]
    if poster["email"]:
        affil_bits.append(_inline(poster["email"]))
    affil = "\\\\".join(affil_bits)
    rule8 = f"\\textcolor{{accent}}{{\\rule{{\\textwidth}}{{{_pt(8 * s)}pt}}}}"
    cols = max(1, poster["columns"])
    open_cols, close_cols = (f"\\begin{{multicols}}{{{cols}}}", "\\end{multicols}") if cols > 1 else ("", "")
    footer = ""
    if footer_logos:
        footer = (
            f"\\noindent\\textcolor{{lightgray}}{{\\rule{{\\textwidth}}{{{_pt(3 * s)}pt}}}}\\par\\vspace{{{cm(1.2)}}}\n"
            + _logo_row(footer_logos, 6 * s, False)
        )

    return f"""\\documentclass[11pt]{{article}}
\\usepackage[paperwidth={_pt(width)}cm,paperheight={_pt(height)}cm,margin={cm(4)}]{{geometry}}
\\usepackage[T1]{{fontenc}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[{labels['babel']}]{{babel}}
\\IfFileExists{{noto-sans.sty}}{{\\usepackage[sfdefault]{{noto-sans}}}}{{\\usepackage{{helvet}}\\renewcommand{{\\familydefault}}{{\\sfdefault}}}}
\\usepackage{{xcolor}}
\\usepackage{{multicol}}
\\usepackage{{enumitem}}
\\usepackage{{needspace}}
\\usepackage{{amsmath,amssymb}}
\\usepackage{{graphicx}}
\\usepackage{{qrcode}}
\\usepackage{{booktabs,array,tikz}}
\\usetikzlibrary{{arrows.meta,positioning,shapes.geometric,fit}}
\\pagestyle{{empty}}
{_hex_to_latex('accent', c1)}
{_hex_to_latex('darkgray', c2)}
{_hex_to_latex('barblack', c3)}
\\setlength{{\\columnsep}}{{{cm(3)}}}
\\setlength{{\\parindent}}{{0pt}}
\\setlength{{\\parskip}}{{{cm(0.3)}}}
\\setlist[itemize]{{label=--, itemsep={cm(0.5)}, parsep=0pt, topsep={cm(0.5)}}}
\\setlist[enumerate]{{itemsep={cm(0.4)}, parsep=0pt, topsep={cm(0.5)}}}
\\begin{{document}}
\\raggedright
{_fs(28, s)}
{_logo_row(header_logos, 6 * s, True)}\\vspace{{{cm(1)}}}
\\begin{{center}}
  {{{_fs(54, s, 1.2)}\\textbf{{\\MakeUppercase{{{_inline(poster['title']) or '~'}}}}}}}\\par
  \\vspace{{{cm(1.2)}}}
  \\noindent\\textcolor{{accent}}{{\\rule{{\\textwidth}}{{{_pt(8 * s)}pt}}}}\\par
  \\vspace{{{cm(0.6)}}}
  {{{_fs(36, s, 1.2)}\\textbf{{{authors}}}}}\\par
  \\vspace{{{cm(0.6)}}}
  {{{_fs(30, s, 1.2)}\\textcolor{{darkgray}}{{{affil}}}}}\\par
\\end{{center}}
\\vspace{{{cm(0.4)}}}
\\noindent\\textcolor{{accent}}{{\\rule{{\\textwidth}}{{{_pt(8 * s)}pt}}}}\\par
\\vspace{{{cm(0.8)}}}
{open_cols}
{chr(10).join(body)}
{close_cols}
\\vfill
{footer}\\end{{document}}
"""

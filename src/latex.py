"""Renderização LaTeX (tikzposter) e compilação do pôster."""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .config import LATEX_TIMEOUT_S, POSTER_SIZES
from .i18n import labels_for
from .templates import TEMPLATES

_ESC = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

_UNICODE_MAP = {
    "≥": r"$\geq$", "≤": r"$\leq$", "±": r"$\pm$", "→": r"$\rightarrow$", "←": r"$\leftarrow$",
    "↑": r"$\uparrow$", "↓": r"$\downarrow$", "≈": r"$\approx$", "≠": r"$\neq$", "∞": r"$\infty$",
    "α": r"$\alpha$", "β": r"$\beta$", "γ": r"$\gamma$", "δ": r"$\delta$", "ε": r"$\epsilon$",
    "θ": r"$\theta$", "λ": r"$\lambda$", "μ": r"$\mu$", "π": r"$\pi$", "σ": r"$\sigma$",
    "φ": r"$\phi$", "ω": r"$\omega$", "Δ": r"$\Delta$", "Σ": r"$\Sigma$", "Ω": r"$\Omega$",
    "∑": r"$\sum$", "√": r"$\surd$", "∂": r"$\partial$", "−": "-", "\u00a0": "~", "\u2009": " ",
    "\u202f": " ", "\u200b": "", "\ufeff": "", "ﬁ": "fi", "ﬂ": "fl", "‐": "-", "‑": "-",
}
_KEEP_HIGH = set("–—‘’‚“”„•…€™†‡‰‹›")

_MATH_CMDS = {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "theta", "lambda", "mu", "nu", "pi",
    "rho", "sigma", "tau", "phi", "varphi", "chi", "psi", "omega", "Gamma", "Delta", "Theta",
    "Lambda", "Pi", "Sigma", "Phi", "Psi", "Omega", "frac", "sqrt", "sum", "prod", "int", "pm",
    "mp", "times", "cdot", "div", "leq", "geq", "le", "ge", "neq", "approx", "sim", "propto",
    "infty", "partial", "nabla", "rightarrow", "leftarrow", "Rightarrow", "to", "log", "ln", "exp",
    "sin", "cos", "tan", "lim", "min", "max", "mathrm", "mathbf", "mathit", "text", "left", "right",
    "ldots", "cdots", "degree", "circ", "bar", "hat", "vec", "overline", "in", "subset", "cup", "cap",
}
_MATH_OK = re.compile(r"^[A-Za-z0-9\s+\-*/=<>()\[\]{}^_.,;:|'!\\]*$")


def _safe_math(expr: str) -> bool:
    if not expr or len(expr) > 300 or not _MATH_OK.match(expr) or "^^" in expr:
        return False
    return all(c in _MATH_CMDS for c in re.findall(r"\\([A-Za-z]+)", expr)) and "\\\\" not in expr


def escape_latex(text: str) -> str:
    out: List[str] = []
    for ch in text:
        if ch in _ESC:
            out.append(_ESC[ch])
        elif ch in _UNICODE_MAP:
            out.append(_UNICODE_MAP[ch])
        elif ord(ch) > 0x17F and ch not in _KEEP_HIGH:
            continue
        elif ord(ch) < 32 and ch not in "\n\t\x00":
            continue
        else:
            out.append(ch)
    return "".join(out)


def _inline(text: str) -> str:
    """Escapa texto e aplica **negrito**, *itálico* e $math$ seguro."""
    maths: List[str] = []
    text = text.replace("\x00", "")

    def stash(m: "re.Match[str]") -> str:
        expr = m.group(1)
        if _safe_math(expr):
            maths.append(f"${expr}$")
            return f"\x00M{len(maths) - 1}\x00"
        return m.group(0)

    text = re.sub(r"(?<!\\)\$([^$\n]+?)\$", stash, text)
    esc = escape_latex(text)
    esc = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", esc)
    esc = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\\textit{\1}", esc)
    # Citações numéricas flutuantes como expoente (superscript) para economizar espaço
    esc = re.sub(r"\[(\d+(?:[,\s–-]+\d+)*)\]", r"\\textsuperscript{[\1]}", esc)
    # Citações estilo autor-ano [Truong and Koyejo 2026, Wang et al. 2026] como expoente
    esc = re.sub(
        r"\[([A-ZÀ-ÿ][^\[\]\n]*?\b(?:19|20)\d{2}[a-z]?[^\[\]\n]*?)\]",
        r"\\textsuperscript{[\1]}",
        esc,
    )
    return re.sub(r"\x00M(\d+)\x00", lambda m: maths[int(m.group(1))], esc)


_DANGEROUS_LATEX_CMD = re.compile(
    r"\\(?:"
    r"input|include|write18|immediate|openin|openout|newwrite|newread|read|catcode"
    r"|def|gdef|edef|xdef|let|futurelet|chardef|dimendef|skipdef|muskipdef|countdef"
    r"|toksdef|everyeof|everypar|everymath|everydisplay|loop|repeat|afterassignment"
    r"|aftergroup|expandafter|noexpand|special|directlua|luaexec|font|primitive"
    r"|shipout|batchmode|errorstopmode"
    r")\b",
    re.IGNORECASE,
)
_LATEX_ENV_PAT = re.compile(
    r"\\begin\{(?:tabular\*?|tabularx|tikzpicture|table|center)\}",
    re.IGNORECASE,
)


def _safe_latex_env(block: str) -> str | None:
    """Verifica se o bloco é um ambiente LaTeX estruturado seguro (tabular, tikzpicture, etc.) e aplica escala responsiva."""
    s = block.strip()
    if not _LATEX_ENV_PAT.search(s):
        return None
    if _DANGEROUS_LATEX_CMD.search(s):
        return None
    # Protege símbolos de porcentagem não escapados para não truncar linhas como comentário TeX
    safe = re.sub(r"(?<!\\)%", r"\%", s)
    # Remove \small / \footnotesize / \tiny internos que encolhem tabelas em pôsteres A0/60x90
    safe = re.sub(r"\\(?:small|footnotesize|scriptsize|tiny)\b", "", safe)
    # Envolve tabular ou tikzpicture em \resizebox{\linewidth}{!}{...} se ainda não estiver redimensionado
    if r"\resizebox" not in safe:
        safe = re.sub(
            r"(\\begin\{tabular\*?\}[\s\S]*?\\end\{tabular\*?\})",
            r"{\\renewcommand{\\arraystretch}{1.28}\\setlength{\\tabcolsep}{7pt}\\resizebox{\\linewidth}{!}{\1}}",
            safe,
        )
        safe = re.sub(
            r"(\\begin\{tikzpicture\}[\s\S]*?\\end\{tikzpicture\})",
            r"\\resizebox{\\linewidth}{!}{\1}",
            safe,
        )
    if not safe.startswith(r"\begin{center}") and (r"\begin{tabular" in safe or r"\begin{tikzpicture" in safe or r"\resizebox" in safe):
        return f"\\begin{{center}}\n{safe}\n\\end{{center}}"
    return safe


_ARROW_FLOW_RE = re.compile(r"(?:->|→|=>)")


def _is_arrow_pipeline(text: str) -> bool:
    s = text.strip()
    # Remove marcadores de lista e rótulos opcionais como "– Pipeline:", "• Fluxo:"
    s = re.sub(r"^[–—\-*•]\s*(?:\w[\w\s]*:\s*)?", "", s).strip()
    if not _ARROW_FLOW_RE.search(s):
        return False
    bracket_nodes = [m.strip() for m in re.findall(r"\[([^\[\]]+)\]", s) if m.strip()]
    if len(bracket_nodes) >= 2:
        return True
    parts = [p.strip().strip("[]") for p in re.split(r"\s*(?:->|→|=>)\s*", s) if p.strip()]
    return len(parts) >= 2


def _arrow_pipeline_to_latex(text: str) -> str:
    s = text.strip()
    s = re.sub(r"^[–—\-*•]\s*(?:\w[\w\s]*:\s*)?", "", s).strip()
    bracket_nodes = [m.strip() for m in re.findall(r"\[([^\[\]]+)\]", s) if m.strip()]
    if len(bracket_nodes) < 2:
        parts = [p.strip().strip("[]") for p in re.split(r"\s*(?:->|→|=>)\s*", s) if p.strip()]
        bracket_nodes = parts
    if len(bracket_nodes) < 2:
        return _inline(text)

    boxes: List[str] = []
    # If 4 or more nodes, stacked presentation ensures excellent readability in column
    if len(bracket_nodes) >= 4:
        for st in bracket_nodes[:6]:
            boxes.append(
                f"\\fbox{{\\parbox{{0.92\\linewidth}}{{\\centering\\large\\textbf{{{_inline(st)}}}}}}}"
            )
        joined = "\n  \\par\\vspace{6pt}$\\boldsymbol{\\downarrow}$\\par\\vspace{6pt}\n  ".join(boxes)
        return (
            "\\begin{center}\n"
            "{\\setlength{\\fboxsep}{9pt}\\setlength{\\fboxrule}{1.6pt}\n"
            f"  {joined}%\n"
            "}\n"
            "\\end{center}"
        )
    else:
        for st in bracket_nodes:
            boxes.append(
                f"\\fbox{{\\begin{{tabular}}{{@{{}}c@{{}}}}\\large\\textbf{{{_inline(st)}}}\\end{{tabular}}}}"
            )
        joined = "\n  $\\boldsymbol{\\rightarrow}$\n  ".join(boxes)
        return (
            "\\begin{center}\n"
            "{\\setlength{\\fboxsep}{9pt}\\setlength{\\fboxrule}{1.6pt}\n"
            "\\resizebox{0.98\\linewidth}{!}{%\n"
            f"  {joined}%\n"
            "}}\n"
            "\\end{center}"
        )


def _is_markdown_table(lines: List[str]) -> bool:
    if len(lines) < 2:
        return False
    l0 = lines[0].strip()
    l1 = lines[1].strip()
    if not (l0.startswith("|") or "|" in l0):
        return False
    return bool(re.match(r"^\s*\|?(\s*:?[-—–]{2,}:?\s*\|)+\s*:?[-—–]{2,}:?\s*\|?\s*$", l1))



def _markdown_table_to_latex(lines: List[str]) -> str:
    header_cells = [c.strip() for c in lines[0].strip().strip("|").split("|")]
    col_count = len(header_cells)
    if col_count == 0:
        return ""
    col_spec = "|l|" + "c|" * (col_count - 1) if col_count > 1 else "|l|"
    header_tex = " & ".join(f"\\textbf{{{_inline(c)}}}" for c in header_cells) + r" \\ \hline"
    rows: List[str] = []
    for ln in lines[2:]:
        if not ln.strip():
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        while len(cells) < col_count:
            cells.append("")
        cells = cells[:col_count]
        rows.append(" & ".join(_inline(c) for c in cells) + r" \\ \hline")
    body = "\n".join(rows)
    return (
        f"\\begin{{center}}\n"
        f"{{\\renewcommand{{\\arraystretch}}{{1.4}}\\setlength{{\\tabcolsep}}{{9pt}}\n"
        f"\\resizebox{{\\linewidth}}{{!}}{{%\n"
        f"\\begin{{tabular}}{{{col_spec}}}\n"
        f"\\hline\n"
        f"{header_tex}\n"
        f"{body}\n"
        f"\\end{{tabular}}%\n"
        f"}}}}\n"
        f"\\end{{center}}"
    )


_BULLET = re.compile(r"^\s*(?:[-*•–]\s+)(.*)$")
_NUMBERED = re.compile(r"^\s*\d{1,2}[.)]\s+(.*)$")


_INLINE_SEP_RE = re.compile(r"(?:\|\s*:?[-—–]+:?\s*){2,}\|?")
_SEP_CELL_RE = re.compile(r"^\s*:?[-—–]{2,}:?\s*$")


def explode_inline_tables(text: str) -> str:
    """Reconstrói tabelas Markdown achatadas em uma única linha (comum em texto vindo de LLM/PDF)."""
    out: List[str] = []
    for ln in text.split("\n"):
        m = _INLINE_SEP_RE.search(ln)
        if not m:
            out.append(ln)
            continue
        before = ln[: m.start()]
        if not before.strip(' |'):
            out.append(ln)
            continue
        raw_sep = m.group(0).strip('|')
        sep_cells = [c.strip() for c in raw_sep.split('|') if c.strip()]
        ncols = len(sep_cells)
        if ncols < 2:
            out.append(ln)
            continue
        pre = [c.strip() for c in before.split('|')]
        while pre and not pre[-1]:
            pre.pop()
        while pre and not pre[0]:
            pre.pop(0)
        if len(pre) < ncols:
            out.append(ln)
            continue
        header = pre[-ncols:]
        lead = " | ".join(pre[:-ncols]).strip()
        raw_after = ln[m.end():]
        cells = [c.strip() for c in raw_after.split('|')]
        if cells and not cells[0]:
            cells.pop(0)
        if cells and not cells[-1]:
            cells.pop()
        rows: List[List[str]] = []
        i = 0
        while i < len(cells):
            while i < len(cells) and not cells[i]:
                i += 1
            chunk = cells[i : i + ncols]
            if len(chunk) < ncols or not any(chunk):
                break
            rows.append(chunk)
            i += ncols
        if lead:
            out.append(lead)
            out.append("")
        out.append("| " + " | ".join(header) + " |")
        out.append("|" + "|".join(" --- " for _ in header) + "|")
        for r in rows:
            out.append("| " + " | ".join(r) + " |")
        out.append("")
    return "\n".join(out)


def _preprocess_structured_blocks(text: str) -> str:
    """Garante que tabelas Markdown/LaTeX e fluxogramas fiquem separados de listas por linha em branco."""
    text = re.sub(
        r"(\n)?(\\begin\{(?:center|tabular\*?|tabularx|tikzpicture)\}[\s\S]*?\\end\{(?:center|tabular\*?|tabularx|tikzpicture)\})(\n)?",
        r"\n\n\2\n\n",
        text,
    )
    lines = text.split("\n")
    out: List[str] = []
    in_md_table = False
    for idx, ln in enumerate(lines):
        s = ln.strip()
        next_s = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
        is_tbl_start = (
            not in_md_table
            and ("|" in s)
            and bool(re.match(r"^\s*\|?(\s*:?[-—–]{2,}:?\s*\|)+\s*:?[-—–]{2,}:?\s*\|?\s*$", next_s))
        )
        if is_tbl_start:
            if out and out[-1].strip():
                out.append("")
            in_md_table = True
            out.append(ln)
            continue
        if in_md_table:
            if "|" in s:
                out.append(ln)
                continue
            else:
                in_md_table = False
                if s:
                    out.append("")
        if _is_arrow_pipeline(s):
            if out and out[-1].strip():
                out.append("")
            out.append(ln)
            out.append("")
            continue
        out.append(ln)
    return "\n".join(out)


def text_to_latex(text: str) -> str:
    """Converte texto simples, listas, tabelas e diagramas em LaTeX."""
    normalized = _preprocess_structured_blocks(explode_inline_tables(text.strip()))
    blocks = re.split(r"\n\s*\n", normalized)
    out: List[str] = []
    for block in blocks:
        if not block.strip():
            continue
        raw_env = _safe_latex_env(block)
        if raw_env:
            out.append(raw_env + "\n")
            continue
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if _is_markdown_table(lines):
            out.append(_markdown_table_to_latex(lines) + "\n")
            continue
        if len(lines) == 1 and _is_arrow_pipeline(lines[0]):
            out.append(_arrow_pipeline_to_latex(lines[0]) + "\n")
            continue
        i = 0
        while i < len(lines):
            if _is_arrow_pipeline(lines[i]):
                out.append(_arrow_pipeline_to_latex(lines[i]) + "\n")
                i += 1
                continue
            kind = "ul" if _BULLET.match(lines[i]) else "ol" if _NUMBERED.match(lines[i]) else None
            if kind:
                rx = _BULLET if kind == "ul" else _NUMBERED
                items: List[str] = []
                while i < len(lines) and rx.match(lines[i]):
                    items.append(rx.match(lines[i]).group(1))  # type: ignore[union-attr]
                    i += 1
                env = "itemize" if kind == "ul" else "enumerate"
                out.append(
                    f"\\begin{{{env}}}\n"
                    + "\n".join(f"\\item {_inline(it)}" for it in items)
                    + f"\n\\end{{{env}}}"
                )
            else:
                para: List[str] = []
                while (
                    i < len(lines)
                    and not _BULLET.match(lines[i])
                    and not _NUMBERED.match(lines[i])
                    and not _is_arrow_pipeline(lines[i])
                ):
                    para.append(lines[i].strip())
                    i += 1
                if para:
                    joined_para = " ".join(para)
                    if _is_arrow_pipeline(joined_para):
                        out.append(_arrow_pipeline_to_latex(joined_para) + "\n")
                    else:
                        out.append(_inline(joined_para) + "\n")
    return "\n".join(out)


def references_to_latex(text: str, small: bool = True) -> str:
    raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    numbered: List[tuple[int, str]] = []
    for it in raw_lines:
        cleaned = it
        num = 0
        # Remove marcadores repetidos como '1. [1] [1]', '[1] [2]', '1.'
        m = re.match(r"^(?:(?:\[\d+\]|\d+[.)])\s*)+", cleaned)
        if m:
            prefix = m.group(0)
            nums = [int(n) for n in re.findall(r"\d+", prefix)]
            if nums:
                num = nums[-1] if len(nums) > 1 else nums[0]
            cleaned = cleaned[len(prefix):].strip()
        numbered.append((num, cleaned))
    if not numbered:
        return ""
    numbered.sort(key=lambda x: x[0] if x[0] > 0 else 999999)
    max_refs = 20
    out_items = []
    next_seq = 1
    for idx, (num, content) in enumerate(numbered[:max_refs], start=1):
        display_num = num if num > 0 else next_seq
        next_seq = max(next_seq, display_num + 1)
        out_items.append(f"\\item [{display_num}] {_inline(content)}")
    return (
        ("{\\small" if small else "{")
        + "\\begin{enumerate}\n"
        + "\n".join(out_items)
        + "\n\\end{enumerate}}"
    )


def _images_to_latex(images: List[Dict[str, str]], fig_label: str, counter: List[int], cap_cmd: str = "\\small") -> str:
    out: List[str] = []
    for start in range(0, len(images), 2):
        row = images[start : start + 2]
        w = "0.48" if len(row) == 2 else "0.9"
        cells = []
        for img in row:
            counter[0] += 1
            cap = img.get("caption", "")
            caption = (
                f"\\\\[2pt]{{{cap_cmd}\\itshape {fig_label} {counter[0]}: {_inline(cap)}}}" if cap else ""
            )
            cells.append(
                f"\\begin{{minipage}}[t]{{{w}\\linewidth}}\\centering"
                f"\\includegraphics[width=\\linewidth,height=0.22\\textheight,keepaspectratio]"
                f"{{{img['file']}}}{caption}\\end{{minipage}}"
            )
        out.append("\\begin{center}\n" + "\\hfill\n".join(cells) + "\n\\end{center}")
    return "\n".join(out)


def _weight(sec: Dict[str, Any]) -> int:
    return 350 + len(sec["content"]) + 900 * len(sec["images"])


def split_columns(
    sections: List[Dict[str, Any]],
    n: int,
) -> List[List[Dict[str, Any]]]:
    """Distribui seções contíguas em n colunas de forma otimizada e equilibrada."""
    n = max(1, min(n, len(sections) or 1))
    if n == 1 or not sections:
        return [sections] if sections else [[]]

    k = len(sections)
    if k <= n:
        cols: List[List[Dict[str, Any]]] = [[s] for s in sections]
        while len(cols) < n:
            cols.append([])
        return cols

    # Divisão simples e determinística, idêntica à do preview JS:
    # 2 colunas -> split no meio; demais -> divisão igual com ceil
    cols: List[List[Dict[str, Any]]] = [[] for _ in range(n)]
    if n == 2:
        split_idx = max(1, min(k - 1, k // 2))
        cols[0] = sections[:split_idx]
        cols[1] = sections[split_idx:]
    else:
        per_col = (k + n - 1) // n  # ceil(k/n)
        for c in range(n):
            start = c * per_col
            end = min(start + per_col, k)
            cols[c] = sections[start:end]
    return cols


_QR_OK = re.compile(r"^https?://[A-Za-z0-9\-._~:/?=@+]+$")


def _hex_to_latex(name: str, value: str) -> str:
    return f"\\definecolor{{{name}}}{{HTML}}{{{value}}}"


def build_tex(poster: Dict[str, Any], images: Dict[str, str]) -> str:
    """Gera o fonte LaTeX. `images` mapeia caminhos de upload -> nome de arquivo no build."""
    engine = TEMPLATES[poster["template"]].get("engine")
    if engine == "article":
        from .article import build_article_tex

        return build_article_tex(poster, images)
    elif engine == "sciposter":
        from .sciposter import build_sciposter_tex

        return build_sciposter_tex(poster, images)
    elif engine == "a0poster":
        from .a0poster import build_a0poster_tex

        return build_a0poster_tex(poster, images)
    elif engine == "beamer":
        from .beamer import build_beamer_tex

        return build_beamer_tex(poster, images)

    labels = labels_for(poster["language"])
    tpl = TEMPLATES[poster["template"]]
    paper = POSTER_SIZES[poster["paper"]]
    pw, ph = paper["cm"]
    if poster["orientation"] == "landscape":
        pw, ph = ph, pw
    c1, c2, c3 = tpl["colors"]
    bg_color = tpl["bg"]
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
    font = "\\renewcommand{\\familydefault}{\\sfdefault}\n" if tpl["sans"] else ""

    sections = []
    for s in poster["sections"]:
        sections.append(
            {**s, "images": [{"file": images[i["path"]], "caption": i["caption"]} for i in s["images"] if i["path"] in images]}
        )
    cols = split_columns(sections, poster["columns"])
    counter = [0]
    col_tex: List[str] = []
    for ci, col in enumerate(cols):
        parts = [f"\\column{{{1 / len(cols):.4f}}}"]
        for s in col:
            body = references_to_latex(s["content"]) if s["id"] == "references" else text_to_latex(s["content"])
            body += "\n" + _images_to_latex(s["images"], labels["figure"], counter)
            parts.append(f"\\block{{{_inline(s['title'])}}}{{\n{body}\n}}")
        col_tex.append("\n".join(parts))

    logos = "".join(
        f"\\includegraphics[height=6cm]{{{images[p]}}}\\hspace{{2cm}}" for p in poster["logos_header"] if p in images
    )
    title = _inline(poster["title"]) or "~"
    authors = escape_latex(poster["authors"]).replace("\n", ", ")
    institute_bits = [escape_latex(ln.strip()) for ln in poster["affiliations"].split("\n") if ln.strip()]
    if poster["email"]:
        institute_bits.insert(0, _inline(poster["email"]))
    institute = "\\\\".join(institute_bits)

    return f"""\\documentclass[{poster.get('_font') or paper['font']},a0paper,margin=20mm,innermargin=12mm,blockverticalspace=12mm,colspace=12mm,subcolspace=8mm]{{tikzposter}}
\\geometry{{paperwidth={pw * 10:.0f}mm,paperheight={ph * 10:.0f}mm,margin=20mm}}
\\usepackage[T1]{{fontenc}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[{labels['babel']}]{{babel}}
\\usepackage{{lmodern}}
\\usepackage{{amsmath,amssymb}}
\\usepackage{{graphicx}}
\\usepackage{{qrcode}}
\\usepackage{{booktabs,array}}
\\usetikzlibrary{{arrows.meta,positioning,shapes.geometric,fit}}
{font}\\definecolorstyle{{PosterColors}}{{
  {_hex_to_latex('colorOne', c1)}
  {_hex_to_latex('colorTwo', c2)}
  {_hex_to_latex('colorThree', c3)}
}}{{
  {_hex_to_latex('posterbg', bg_color)}
  \\colorlet{{backgroundcolor}}{{posterbg}}
  \\colorlet{{framecolor}}{{colorOne}}
  \\colorlet{{titlefgcolor}}{{white}}
  \\colorlet{{titlebgcolor}}{{colorOne}}
  \\colorlet{{blocktitlebgcolor}}{{colorTwo}}
  \\colorlet{{blocktitlefgcolor}}{{white}}
  \\colorlet{{blockbodybgcolor}}{{white}}
  \\colorlet{{blockbodyfgcolor}}{{black}}
  \\colorlet{{innerblocktitlebgcolor}}{{colorThree}}
  \\colorlet{{innerblocktitlefgcolor}}{{black}}
  \\colorlet{{innerblockbodybgcolor}}{{white}}
  \\colorlet{{innerblockbodyfgcolor}}{{black}}
  \\colorlet{{notefgcolor}}{{black}}
  \\colorlet{{notebgcolor}}{{colorThree}}
  \\colorlet{{noteframecolor}}{{colorOne}}
}}
\\usecolorstyle{{PosterColors}}
\\useblockstyle{{{tpl['block']}}}
\\usetitlestyle{{{tpl['title']}}}
\\usebackgroundstyle{{{tpl['background']}}}
\\title{{{title}}}
\\author{{{authors}}}
\\institute{{{institute}}}
\\titlegraphic{{{logos}}}
\\begin{{document}}
\\maketitle
\\begin{{columns}}
{chr(10).join(col_tex)}
\\end{{columns}}
\\end{{document}}
"""


def make_zip(tex: str, build_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("poster.tex", tex)
        for f in build_dir.iterdir():
            if f.suffix.lower() in (".png", ".jpg"):
                zf.write(f, f.name)
    return buf.getvalue()


def compile_tex(tex: str, build_dir: Path) -> Tuple[bytes, str]:
    """Compila com pdflatex (sem shell-escape). Retorna (pdf, log)."""
    exe = shutil.which("pdflatex")
    if not exe:
        raise RuntimeError("pdflatex não encontrado no PATH (instale TeX Live ou MiKTeX).")
    (build_dir / "poster.tex").write_text(tex, encoding="utf-8")
    (build_dir / "poster.pdf").unlink(missing_ok=True)
    log = ""
    env = {k: v for k, v in os.environ.items() if not k.lower().endswith(("_key", "_token", "_secret"))}
    env.update({"openin_any": "p", "openout_any": "p", "shell_escape": "f"})  # defesa em profundidade
    for _ in range(2):
        proc = subprocess.run(
            [exe, "-interaction=nonstopmode", "-no-shell-escape", "poster.tex"],
            cwd=build_dir, capture_output=True, timeout=LATEX_TIMEOUT_S, env=env,
        )
        log = proc.stdout.decode("utf-8", "replace")
        if "Rerun" not in log:
            break
    pdf = build_dir / "poster.pdf"
    if not pdf.exists() or pdf.stat().st_size == 0:
        err = [ln for ln in log.splitlines() if ln.startswith("!")][:5]
        raise RuntimeError("Falha ao compilar o LaTeX: " + " | ".join(err))
    return pdf.read_bytes(), log


FONT_STEPS = ["12pt", "14pt", "17pt", "20pt", "25pt"]
FIT_DEADLINE_S = 120  # tempo total máximo de tentativas de ajuste


def content_overflows(pdf: bytes) -> bool:
    """True se algum texto foi posicionado fora (abaixo) da página."""
    from pypdf import PdfReader

    page = PdfReader(io.BytesIO(pdf)).pages[0]
    ys: List[float] = []

    def visit(text: str, cm: Any, tm: Any, _fd: Any, _fs: Any) -> None:
        if text.strip():
            ys.append(tm[5] * cm[3] + cm[5])

    page.extract_text(visitor_text=visit)
    return bool(ys) and min(ys) < 0


ARTICLE_FIT_STEPS = [1.0, 0.92, 0.85, 0.78, 0.72, 0.66, 0.6, 0.55, 0.5, 0.45]


def fit_compile(poster: Dict[str, Any], images: Dict[str, str], build_dir: Path) -> Tuple[bytes, str, bool]:
    """Compila reduzindo a fonte base até o conteúdo caber. Retorna (pdf, tex, overflow)."""
    from pypdf import PdfReader

    t0 = time.monotonic()
    pdf, tex, over = b"", "", True
    if TEMPLATES[poster["template"]].get("engine") == "article":
        for fit in ARTICLE_FIT_STEPS:  # transbordo = conteúdo vai para 2ª página
            tex = build_tex({**poster, "_fit": fit}, images)
            pdf, _ = compile_tex(tex, build_dir)
            over = len(PdfReader(io.BytesIO(pdf)).pages) > 1
            if not over or time.monotonic() - t0 > FIT_DEADLINE_S:
                break
        return pdf, tex, over
    start = FONT_STEPS.index(POSTER_SIZES[poster["paper"]]["font"])
    for font in FONT_STEPS[start::-1]:
        tex = build_tex({**poster, "_font": font}, images)
        pdf, _ = compile_tex(tex, build_dir)
        over = content_overflows(pdf)
        if not over or time.monotonic() - t0 > FIT_DEADLINE_S:
            break
    return pdf, tex, over


def new_build_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="poster_"))

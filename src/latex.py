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
    if re.search(r"\\(?:draw|node|begin|end|path|fill|clip|coordinate)\b", s) or s.startswith(("\\", "%")):
        return False
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
    if not _is_arrow_pipeline(text):
        return _inline(text)
    s = text.strip()
    s = re.sub(r"^[–—\-*•]\s*(?:\w[\w\s]*:\s*)?", "", s).strip()
    bracket_nodes = [m.strip() for m in re.findall(r"\[([^\[\]]+)\]", s) if m.strip()]
    if len(bracket_nodes) < 2:
        parts = [p.strip().strip("[]") for p in re.split(r"\s*(?:->|→|=>)\s*", s) if p.strip()]
        bracket_nodes = parts
    if len(bracket_nodes) < 2:
        return _inline(text)

    nodes = bracket_nodes[:6]

    # TikZ colorido: usa colorOne (accent do poster) para bordas e setas, idêntico ao preview (sem moldura externa)
    if len(nodes) == 4:
        # Layout 2x2 com setas centralizado
        pos_lines = [
            f"  \\node[draw=colorOne, line width=2pt, fill=white, rounded corners=6pt,\n"
            f"        align=center, inner sep=9pt, font=\\Large\\bfseries, text=black, anchor=east] (n0) at (-14pt, 0) {{{_inline(nodes[0])}}};",
            f"  \\node[draw=colorOne, line width=2pt, fill=white, rounded corners=6pt,\n"
            f"        align=center, inner sep=9pt, font=\\Large\\bfseries, text=black, anchor=west] (n1) at (14pt, 0) {{{_inline(nodes[1])}}};",
            f"  \\node[draw=colorOne, line width=2pt, fill=white, rounded corners=6pt,\n"
            f"        align=center, inner sep=9pt, font=\\Large\\bfseries, text=black, anchor=east] (n2) at (-14pt, -52pt) {{{_inline(nodes[2])}}};",
            f"  \\node[draw=colorOne, line width=2pt, fill=white, rounded corners=6pt,\n"
            f"        align=center, inner sep=9pt, font=\\Large\\bfseries, text=black, anchor=west] (n3) at (14pt, -52pt) {{{_inline(nodes[3])}}};",
        ]
        arrow_lines = [
            r"  \draw[-{Stealth[scale=1.5]}, line width=2.2pt, color=colorOne] (n0) -- (n1);",
            r"  \draw[-{Stealth[scale=1.5]}, line width=2.2pt, color=colorOne] (n1.south) -- ++(0,-16pt) -| (n2.north);",
            r"  \draw[-{Stealth[scale=1.5]}, line width=2.2pt, color=colorOne] (n2) -- (n3);",
        ]
        body = "\n".join(pos_lines + arrow_lines)
        return (
            "\\begin{center}\n"
            "\\resizebox{\\ifdim\\width>0.95\\linewidth 0.95\\linewidth\\else\\width\\fi}{!}{%\n"
            "\\begin{tikzpicture}\n"
            f"{body}\n"
            "\\end{tikzpicture}%\n"
            "}\n"
            "\\end{center}"
        )
    elif len(nodes) > 4:
        # Layout vertical com setas para baixo
        tikz_nodes = []
        for i, st in enumerate(nodes):
            tikz_nodes.append(
                f"  \\node[draw=colorOne, line width=2pt, fill=white, rounded corners=6pt,\n"
                f"        text width=0.82\\linewidth, align=center, inner sep=9pt,\n"
                f"        font=\\Large\\bfseries, text=black] (n{i}) {{{_inline(st)}}};"
            )
        pos_lines = [tikz_nodes[0]]
        for i in range(1, len(nodes)):
            pos_lines.append(
                f"  \\node[draw=colorOne, line width=2pt, fill=white, rounded corners=6pt,\n"
                f"        text width=0.82\\linewidth, align=center, inner sep=9pt,\n"
                f"        font=\\Large\\bfseries, text=black, below=18pt of n{i-1}] (n{i}) {{{_inline(nodes[i])}}};"
            )
        arrow_lines = [
            f"  \\draw[-{{Stealth[scale=1.5]}}, line width=2.2pt, color=colorOne] (n{i}.south) -- (n{i+1}.north);"
            for i in range(len(nodes) - 1)
        ]
        body = "\n".join(pos_lines + arrow_lines)
        return (
            "\\begin{center}\n"
            "\\resizebox{\\ifdim\\width>0.95\\linewidth 0.95\\linewidth\\else\\width\\fi}{!}{%\n"
            "\\begin{tikzpicture}\n"
            f"{body}\n"
            "\\end{tikzpicture}%\n"
            "}\n"
            "\\end{center}"
        )
    elif len(nodes) == 3 and sum(len(n) for n in nodes) > 28:
        # Layout em 2 linhas com quebra responsiva idêntico ao preview (.draft-diagram flex-wrap), perfeitamente centralizado
        pos_lines = [
            f"  \\node[draw=colorOne, line width=2pt, fill=white, rounded corners=6pt,\n"
            f"        align=center, inner sep=9pt, font=\\Large\\bfseries, text=black, anchor=east] (n0) at (-14pt, 0) {{{_inline(nodes[0])}}};",
            f"  \\node[draw=colorOne, line width=2pt, fill=white, rounded corners=6pt,\n"
            f"        align=center, inner sep=9pt, font=\\Large\\bfseries, text=black, anchor=west] (n1) at (14pt, 0) {{{_inline(nodes[1])}}};",
            f"  \\node[draw=colorOne, line width=2pt, fill=white, rounded corners=6pt,\n"
            f"        align=center, inner sep=9pt, font=\\Large\\bfseries, text=black] (n2) at (14pt, -52pt) {{{_inline(nodes[2])}}};",
        ]
        arrow_lines = [
            r"  \draw[-{Stealth[scale=1.5]}, line width=2.2pt, color=colorOne] (n0) -- (n1);",
            r"  \draw[-{Stealth[scale=1.5]}, line width=2.2pt, color=colorOne] ($(n2.west)-(28pt,0)$) -- (n2.west);",
        ]
        body = "\n".join(pos_lines + arrow_lines)
        return (
            "\\begin{center}\n"
            "\\resizebox{\\ifdim\\width>0.95\\linewidth 0.95\\linewidth\\else\\width\\fi}{!}{%\n"
            "\\begin{tikzpicture}\n"
            f"{body}\n"
            "\\end{tikzpicture}%\n"
            "}\n"
            "\\end{center}"
        )
    else:
        # Layout horizontal com setas para a direita
        tikz_nodes = []
        tikz_nodes.append(
            f"  \\node[draw=colorOne, line width=2pt, fill=white, rounded corners=6pt,\n"
            f"        align=center, inner sep=9pt,\n"
            f"        font=\\Large\\bfseries, text=black] (n0) {{{_inline(nodes[0])}}};"
        )
        for i in range(1, len(nodes)):
            tikz_nodes.append(
                f"  \\node[draw=colorOne, line width=2pt, fill=white, rounded corners=6pt,\n"
                f"        align=center, inner sep=9pt,\n"
                f"        font=\\Large\\bfseries, text=black, right=20pt of n{i-1}] (n{i}) {{{_inline(nodes[i])}}};"
            )
        arrow_lines = [
            f"  \\draw[-{{Stealth[scale=1.5]}}, line width=2.2pt, color=colorOne] (n{i}.east) -- (n{i+1}.west);"
            for i in range(len(nodes) - 1)
        ]
        body = "\n".join(tikz_nodes + arrow_lines)
        return (
            "\\begin{center}\n"
            "\\resizebox{\\ifdim\\width>0.95\\linewidth 0.95\\linewidth\\else\\width\\fi}{!}{%\n"
            "\\begin{tikzpicture}\n"
            f"{body}\n"
            "\\end{tikzpicture}%\n"
            "}\n"
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
        f"{{\\fontsize{{20pt}}{{26pt}}\\selectfont\\renewcommand{{\\arraystretch}}{{1.75}}\\setlength{{\\tabcolsep}}{{14pt}}\n"
        f"\\arrayrulecolor{{tableLine}}\n"
        f"\\resizebox{{\\linewidth}}{{!}}{{%\n"
        f"\\begin{{tabular}}{{{col_spec}}}\n"
        f"\\hline\n"
        f"\\rowcolor{{tableHead}}\n"
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


def _parse_multiline_pipeline(lines: List[str]) -> List[str] | None:
    """Detecta sequência de blocos com setas verticais intercaladas (↓, ->, etc.)."""
    if len(lines) < 3:
        return None
    arrow_syms = {"↓", "->", "→", "=>", "|", "v", "V"}
    nodes = []
    is_pipeline = True
    for i, ln in enumerate(lines):
        s = ln.strip()
        if i % 2 == 1:
            if s not in arrow_syms:
                is_pipeline = False
                break
        else:
            if s in arrow_syms or not s:
                is_pipeline = False
                break
            nodes.append(s)
    if is_pipeline and len(nodes) >= 2:
        return nodes
    return None


def _parse_tikz_pipeline_nodes(block: str) -> List[str] | None:
    """Extrai sequência de nós de fluxogramas TikZ simples para unificar estilização com a paleta do pôster."""
    s = block.strip()
    if not (r"\begin{tikzpicture}" in s and r"\end{tikzpicture}" in s):
        return None
    if any(k in s for k in [r"\addplot", r"\datavisualization", r"\axis", r"\matrix"]):
        return None
    matches = re.findall(r"\\node\b[^{]*\{([^}]+)\}", s, flags=re.IGNORECASE)
    if len(matches) >= 2:
        cleaned = []
        for m in matches:
            t = m.strip()
            t = re.sub(r"\\textbf\{([^}]+)\}", r"\1", t).strip()
            t = t.replace(r"\&", "&")
            cleaned.append(t)
        return cleaned
    return None


_IMG_TAG_RE = re.compile(r"\[(?:imagem|figura|img|image)(?::(\d+))?(?:\|([^\]]+))?\]", re.IGNORECASE)


def text_to_latex(
    text: str,
    images: Optional[List[Dict[str, str]]] = None,
    fig_label: str = "Figura",
    counter: Optional[List[int]] = None,
    placed_indices: Optional[set] = None,
) -> str:
    """Converte texto simples, listas, tabelas, diagramas e imagens inline em LaTeX."""
    if counter is None:
        counter = [0]
    if placed_indices is None:
        placed_indices = set()
    normalized = _preprocess_structured_blocks(explode_inline_tables(text.strip()))
    # Isola tags de imagem em blocos próprios, mantendo agrupadas tags adjacentes na mesma linha
    normalized = re.sub(
        r"([^\n\s\]])\s*(\[(?:imagem|figura|img|image)[^\]]*\])",
        r"\1\n\n\2",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(\[(?:imagem|figura|img|image)[^\]]*\])\s*([^\n\s\[])",
        r"\1\n\n\2",
        normalized,
        flags=re.IGNORECASE,
    )
    blocks = re.split(r"\n\s*\n", normalized)
    out: List[str] = []
    for block in blocks:
        if not block.strip():
            continue
        # Tags de imagens inline: [imagem:1], [figura:2|Legenda], etc.
        if images and _IMG_TAG_RE.search(block):
            tag_matches = list(_IMG_TAG_RE.finditer(block))
            if not _IMG_TAG_RE.sub("", block).strip():
                row_imgs = []
                for tm in tag_matches:
                    raw_idx, custom_cap = tm.groups()
                    if raw_idx and raw_idx.isdigit():
                        idx = int(raw_idx) - 1
                    else:
                        avail = [k for k in range(len(images)) if k not in placed_indices and k not in [x[0] for x in row_imgs]]
                        idx = avail[0] if avail else -1
                    if 0 <= idx < len(images):
                        im_data = dict(images[idx])
                        if custom_cap and custom_cap.strip():
                            im_data["caption"] = custom_cap.strip()
                        row_imgs.append((idx, im_data))
                if row_imgs:
                    for k, _ in row_imgs:
                        placed_indices.add(k)
                    out.append(_images_to_latex([im for _, im in row_imgs], fig_label, counter) + "\n")
                    continue
        tikz_nodes = _parse_tikz_pipeline_nodes(block)
        if tikz_nodes:
            synthetic_arrow = " -> ".join(f"[{n}]" for n in tikz_nodes)
            out.append(_arrow_pipeline_to_latex(synthetic_arrow) + "\n")
            continue
        raw_env = _safe_latex_env(block)
        if raw_env:
            out.append(raw_env + "\n")
            continue
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if _is_markdown_table(lines):
            out.append(_markdown_table_to_latex(lines) + "\n")
            continue
        # Verifica se o bloco inteiro é um pipeline multilinhas (ex: linhas intercaladas com ↓)
        multi_nodes = _parse_multiline_pipeline(lines)
        if multi_nodes:
            synthetic_arrow = " -> ".join(f"[{n}]" for n in multi_nodes)
            out.append(_arrow_pipeline_to_latex(synthetic_arrow) + "\n")
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
    step = 3 if len(images) == 3 else 2
    for start in range(0, len(images), step):
        row = images[start : start + step]
        w = "0.31" if len(row) == 3 else ("0.48" if len(row) == 2 else "0.85")
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
    clean = str(value or "").lstrip("#")
    return f"\\definecolor{{{name}}}{{HTML}}{{{clean}}}"


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
    has_custom_bg = False
    body_color = None
    if poster.get("colors"):
        colors = poster["colors"]
        if colors.get("accent"):
            c1 = colors["accent"]
        if colors.get("subtitle"):
            c2 = colors["subtitle"]
        if colors.get("title"):
            c3 = colors["title"]
        if colors.get("body"):
            body_color = colors["body"]
        if colors.get("bg"):
            bg_color = colors["bg"]
            has_custom_bg = True
    elif poster.get("accent"):
        c1 = c2 = poster["accent"]
    font = "\\renewcommand{\\familydefault}{\\sfdefault}\n" if tpl["sans"] else ""

    body_fg_def = f"\n  {_hex_to_latex('colorBody', body_color)}" if body_color else ""
    body_fg_let = "colorBody" if body_color else "black"
    block_body_bg = "posterbg" if has_custom_bg else "white"
    if tpl["block"] == "AcademicCard":
        block_title_bg = "colorOne!8!white" if not has_custom_bg else "colorOne!12!posterbg"
        block_title_fg = "colorOne"
    else:
        block_title_bg = "colorTwo"
        block_title_fg = "white"

    sections = []
    for s in poster["sections"]:
        sections.append(
            {**s, "images": [{"file": images[i["path"]], "caption": i["caption"]} for i in s["images"] if i["path"] in images]}
        )
    cols = split_columns(sections, poster["columns"])

    footer_imgs = [images[p] for p in poster.get("logos_footer", []) if p in images]
    footer_tex = ""
    if footer_imgs:
        cells = "\\hfill ".join(f"\\includegraphics[height=3.5cm,width=0.15\\linewidth,keepaspectratio]{{{f}}}" for f in footer_imgs)
        footer_tex = f"\n\\node[above=12mm of bottomright, anchor=south east, xshift=-12mm] {{\\begin{{minipage}}{{\\linewidth}} {cells}\\end{{minipage}}}};\n"

    header_imgs = [images[p] for p in poster["logos_header"] if p in images]

    header_h = 18.0 if (header_imgs or poster.get("affiliations") or poster.get("email")) else 14.0
    footer_h = 8.0 if footer_imgs else 0.0
    avail_h = max(25.0, ph - 4.0 - 2.4 - header_h - footer_h - 4.0)

    counter = [0]
    col_tex: List[str] = []
    for ci, col in enumerate(cols):
        parts = [f"\\column{{{1 / len(cols):.4f}}}"]
        K = len(col)
        usable_body_h = max(10.0, avail_h - (K * 3.0) - ((K - 1) * 1.2)) if K else 10.0
        weights = []
        for s in col:
            content_len = len(s.get("content", ""))
            img_count = len(s.get("images", []))
            has_tbl_or_diag = 1 if ("|" in s.get("content", "") or "->" in s.get("content", "") or "→" in s.get("content", "")) else 0
            w = max(100, content_len + img_count * 450 + has_tbl_or_diag * 300)
            weights.append(w)
        total_w = sum(weights) or 1

        for idx, s in enumerate(col):
            if s["id"] == "references":
                body = references_to_latex(s["content"])
                img_tex = ""
            else:
                placed_indices = set()
                body = text_to_latex(s["content"], s.get("images"), labels["figure"], counter, placed_indices)
                unplaced = [im for i, im in enumerate(s.get("images", [])) if i not in placed_indices]
                img_tex = _images_to_latex(unplaced, labels["figure"], counter) if unplaced else ""
            if img_tex:
                body += "\n" + img_tex

            if tpl["block"] == "AcademicCard" and K > 0:
                target_h = (usable_body_h * weights[idx]) / total_w
                min_h = min(6.0, usable_body_h / K)
                target_h = max(min_h, target_h)

                content_len = len(s.get("content", ""))
                img_count = len(s.get("images", []))
                has_tbl_or_diag = 1 if ("|" in s.get("content", "") or "->" in s.get("content", "") or "→" in s.get("content", "")) else 0
                est_h = (content_len / 140.0) * 2.2 + (8.5 if img_count == 1 else 6.5 if img_count > 1 else 0) + has_tbl_or_diag * 5.0
                if target_h > est_h + 1.5:
                    body = f"\\parbox[t][{target_h:.1f}cm][t]{{\\linewidth}}{{\n{body}\n}}"

            title_text = _inline(s['title'])
            if tpl["block"] == "AcademicCard":
                title_text = f"\\textbf{{{title_text}}}"
            parts.append(f"\\block{{{title_text}}}{{\n{body}\n}}")
        col_tex.append("\n".join(parts))
    title = _inline(poster["title"]) or "~"
    authors = escape_latex(poster["authors"]).replace("\n", ", ")
    institute_bits = [escape_latex(ln.strip()) for ln in poster["affiliations"].split("\n") if ln.strip()]
    if poster["email"]:
        institute_bits.insert(0, _inline(poster["email"]))
    institute = "\\\\".join(institute_bits)

    if len(header_imgs) >= 2:
        left_logo = f"\\begin{{minipage}}[c]{{0.18\\linewidth}}\\raggedright\\includegraphics[height=5cm,width=\\linewidth,keepaspectratio]{{{header_imgs[0]}}}\\end{{minipage}}"
        right_logo = f"\\begin{{minipage}}[c]{{0.18\\linewidth}}\\raggedleft\\includegraphics[height=5cm,width=\\linewidth,keepaspectratio]{{{header_imgs[1]}}}\\end{{minipage}}"
        center_inst = f"\\begin{{minipage}}[c]{{0.60\\linewidth}}\\centering {institute}\\end{{minipage}}"
        institute_tex = f"{left_logo}\\hfill {center_inst}\\hfill {right_logo}"
        logos = ""
    elif len(header_imgs) == 1:
        left_logo = f"\\begin{{minipage}}[c]{{0.18\\linewidth}}\\raggedright\\includegraphics[height=5cm,width=\\linewidth,keepaspectratio]{{{header_imgs[0]}}}\\end{{minipage}}"
        right_spacer = f"\\begin{{minipage}}[c]{{0.18\\linewidth}}\\null\\end{{minipage}}"
        center_inst = f"\\begin{{minipage}}[c]{{0.60\\linewidth}}\\centering {institute}\\end{{minipage}}"
        institute_tex = f"{left_logo}\\hfill {center_inst}\\hfill {right_spacer}"
        logos = ""
    else:
        institute_tex = institute
        logos = ""

    titlegraphic_tex = f"\\titlegraphic{{{logos}}}\n" if logos else ""

    return f"""\\documentclass[{poster.get('_font') or paper['font']},a0paper,margin=0mm,innermargin=15mm,blockverticalspace=12mm,colspace=12mm,subcolspace=8mm]{{tikzposter}}
\\geometry{{paperwidth={pw * 10:.0f}mm,paperheight={ph * 10:.0f}mm,margin=0mm}}
\\makeatletter
\\setlength{{\\TP@visibletextwidth}}{{\\textwidth-2\\TP@innermargin}}
\\setlength{{\\TP@visibletextheight}}{{\\textheight-2\\TP@innermargin}}
\\makeatother
\\tikzposterlatexaffectionproofoff
\\usepackage[T1]{{fontenc}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[{labels['babel']}]{{babel}}
\\usepackage{{lmodern}}
\\usepackage{{amsmath,amssymb}}
\\usepackage{{graphicx}}
\\usepackage{{qrcode}}
\\usepackage{{booktabs,array,colortbl}}
\\usetikzlibrary{{arrows.meta,positioning,shapes.geometric,fit,calc}}
\\definecolor{{tableHead}}{{HTML}}{{F1F5F9}}
\\definecolor{{tableLine}}{{HTML}}{{334155}}
\\definecolor{{diagFrame}}{{HTML}}{{CBD5E1}}
\\defineblockstyle{{AcademicCard}}{{
    titlewidthscale=1, bodywidthscale=1, titleleft,
    titleoffsetx=0pt, titleoffsety=0pt, bodyoffsetx=0pt, bodyoffsety=0pt,
    bodyverticalshift=0pt, roundedcorners=10, linewidth=2.5pt,
    titleinnersep=6mm, bodyinnersep=8mm
}}{{
    \\begin{{scope}}[line width=\\blocklinewidth, rounded corners=\\blockroundedcorners]
        \\ifBlockHasTitle
           \\clip (blockbody.south west) rectangle (blocktitle.north east);
           \\fill[blockbodybgcolor] (blockbody.south west) rectangle (blocktitle.north east);
           \\fill[blocktitlebgcolor] (blocktitle.south west) rectangle (blocktitle.north east);
           \\draw[color=framecolor, line width=2pt] (blocktitle.south west) -- (blocktitle.south east);
           \\draw[color=framecolor] (blockbody.south west) rectangle (blocktitle.north east);
        \\else
           \\draw[color=framecolor, fill=blockbodybgcolor] (blockbody.south west) rectangle (blockbody.north east);
        \\fi
    \\end{{scope}}
}}
{font}\\definecolorstyle{{PosterColors}}{{
  {_hex_to_latex('colorOne', c1)}
  {_hex_to_latex('colorTwo', c2)}
  {_hex_to_latex('colorThree', c3)}{body_fg_def}
}}{{
  {_hex_to_latex('posterbg', bg_color)}
  \\colorlet{{backgroundcolor}}{{posterbg}}
  \\colorlet{{framecolor}}{{colorOne}}
  \\colorlet{{titlefgcolor}}{{white}}
  \\colorlet{{titlebgcolor}}{{colorOne}}
  \\colorlet{{blocktitlebgcolor}}{{{block_title_bg}}}
  \\colorlet{{blocktitlefgcolor}}{{{block_title_fg}}}
  \\colorlet{{blockbodybgcolor}}{{{block_body_bg}}}
  \\colorlet{{blockbodyfgcolor}}{{{body_fg_let}}}
  \\colorlet{{innerblocktitlebgcolor}}{{colorThree}}
  \\colorlet{{innerblocktitlefgcolor}}{{black}}
  \\colorlet{{innerblockbodybgcolor}}{{{block_body_bg}}}
  \\colorlet{{innerblockbodyfgcolor}}{{{body_fg_let}}}
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
\\institute{{{institute_tex}}}
{titlegraphic_tex}\\begin{{document}}
\\maketitle
\\begin{{columns}}
{chr(10).join(col_tex)}
\\end{{columns}}
{footer_tex}\\end{{document}}
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

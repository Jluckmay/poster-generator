"""Normalização e validação dos dados do pôster (entrada manual, upload ou IA)."""

from __future__ import annotations

import re
from typing import Any, Dict, List


def renumber_citations(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Remaps citation numbers in all section texts so they match the references list.
    Supports bracketed numbers [9], dot numbers 9., or plain numbers at line starts (9 Author...).
    """
    # Find references section
    ref_sec = None
    for sec in sections:
        if sec.get("id") == "references" or re.search(r"refer[eê]nc", sec.get("title", ""), re.IGNORECASE):
            ref_sec = sec
            break

    if not ref_sec or not ref_sec.get("content"):
        return sections

    ref_text = ref_sec["content"].replace("\r\n", "\n").replace("\r", "\n")
    # Break into items if separated on single lines or spaces before numbers
    ref_text = re.sub(r"(?:^|\s+)(?:\[\d{1,3}\]|\d{1,2}[.)]?)\s+(?=[A-ZÀ-ÿ])", r"\n\g<0>", ref_text)
    lines = [ln.strip() for ln in ref_text.split("\n") if ln.strip()]

    old_to_new: Dict[int, int] = {}
    new_refs: List[str] = []
    new_idx = 1
    for ln in lines:
        # Match '[1] ...', '1. ...', '1) ...', or '1 Author ...'
        m = re.match(r"^(?:\[(\d+)\]|(\d+)[.)]?)\s+(.+)", ln)
        if m:
            old_num = int(m.group(1) or m.group(2))
            body = m.group(3).strip()
            if old_num not in old_to_new:
                old_to_new[old_num] = new_idx
                new_refs.append(f"[{new_idx}] {body}")
                new_idx += 1
        else:
            new_refs.append(f"[{new_idx}] {ln}")
            new_idx += 1

    if not old_to_new:
        return sections

    valid_keys = set(old_to_new.keys())

    def remap_text(text: str) -> str:
        """Replace citation numbers in text according to old_to_new mapping."""
        def replace_bracket(m: re.Match) -> str:
            inner = m.group(1)
            parts = re.split(r"[,;]\s*", inner)
            new_parts = []
            for p in parts:
                p = p.strip()
                rng = re.match(r"^(\d+)\s*[-\u2013]\s*(\d+)$", p)
                if rng:
                    start, end = int(rng.group(1)), int(rng.group(2))
                    mapped = [str(old_to_new[n]) for n in range(start, end + 1) if n in old_to_new]
                    new_parts.extend(mapped)
                else:
                    if p.isdigit():
                        n = int(p)
                        if n in old_to_new:
                            new_parts.append(str(old_to_new[n]))
                    else:
                        new_parts.append(p)
            seen = set()
            dedup = []
            for np in new_parts:
                if np not in seen:
                    seen.add(np)
                    dedup.append(np)
            return "[" + ", ".join(dedup) + "]" if dedup else ""

        res = re.sub(r"\[(\d+(?:[,;\s\u2013-]+\d+)*)\]", replace_bracket, text)
        return re.sub(r"\s{2,}", " ", res).replace(" .", ".").replace(" ,", ",")

    # Apply remapping to all sections
    result = []
    for sec in sections:
        if sec is ref_sec:
            result.append({**sec, "content": "\n".join(new_refs)})
        else:
            result.append({**sec, "content": remap_text(sec.get("content", ""))})

    return result

from .config import LANGUAGES
from .i18n import labels_for
from .templates import DEFAULT_TEMPLATE, TEMPLATES, default_paper_for, papers_for

MAX_SECTIONS = 20
MAX_FIELD = 20_000


def _s(value: Any, limit: int = MAX_FIELD) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = "\n".join(str(v) for v in value)
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()[:limit]


def _hex(value: Any, default: str) -> str:
    v = _s(value, 16).lstrip("#")
    return v.upper() if re.fullmatch(r"[0-9a-fA-F]{6}", v) else default


def normalize_poster(data: Dict[str, Any]) -> Dict[str, Any]:
    """Retorna um dicionário saneado com todos os campos esperados pelo renderizador."""
    lang = data.get("language") if data.get("language") in LANGUAGES else "pt-BR"
    labels = labels_for(lang)
    template = data.get("template") if data.get("template") in TEMPLATES else DEFAULT_TEMPLATE
    paper = data.get("paper") if data.get("paper") in papers_for(template) else default_paper_for(template)
    orientation = "landscape" if data.get("orientation") == "landscape" else "portrait"
    default_cols = TEMPLATES[template].get("default_columns") or (3 if orientation == "landscape" else 2)
    try:
        columns = int(data.get("columns") or default_cols)
    except (TypeError, ValueError):
        columns = default_cols
    columns = max(1, min(4, columns))
    slots = TEMPLATES[template]["logos"]

    def _logo_list(key: str, limit: int) -> List[str]:
        raw = data.get(key) or []
        return [str(p) for p in raw if p][:limit] if isinstance(raw, list) else []

    # `logos` (legado) equivale ao cabeçalho
    logos_header = _logo_list("logos_header" if "logos_header" in data else "logos", slots["header"])
    logos_footer = _logo_list("logos_footer", slots["footer"])

    sections: List[Dict[str, Any]] = []
    raw_sections = data.get("sections")
    if isinstance(raw_sections, dict):  # formato {id: texto}
        raw_sections = [{"id": k, "content": v} for k, v in raw_sections.items()]
    for i, sec in enumerate((raw_sections or [])[:MAX_SECTIONS]):
        if not isinstance(sec, dict):
            continue
        sid = _s(sec.get("id"), 40) or f"custom{i}"
        title = _s(sec.get("title"), 200) or labels.get(sid, "")
        content = _s(sec.get("content"))
        images = []
        for img in sec.get("images") or []:
            if isinstance(img, dict) and img.get("path"):
                images.append({"path": str(img["path"]), "caption": _s(img.get("caption"), 400)})
        if not (content or images):
            continue
        if not title:
            title = sid.capitalize()
        sections.append({"id": sid, "title": title, "content": content, "images": images})

    sections = renumber_citations(sections)

    colors: Dict[str, str] = {}
    if isinstance(data.get("colors"), dict):
        for k in ("accent", "title", "subtitle", "body", "caption", "bg"):
            val = data["colors"].get(k)
            if val:
                colors[k] = _hex(val, "")

    return {
        "language": lang,
        "template": template,
        "paper": paper,
        "orientation": orientation,
        "columns": columns,
        "accent": _hex(data.get("accent"), ""),
        "colors": colors,
        "title": _s(data.get("title"), 500),
        "authors": _s(data.get("authors"), 1500),
        "affiliations": _s(data.get("affiliations"), 2000),
        "email": _s(data.get("email"), 200),
        "url": _s(data.get("url"), 300),
        "logos_header": logos_header,
        "logos_footer": logos_footer,
        "sections": sections,
    }

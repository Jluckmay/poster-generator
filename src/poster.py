"""Normalização e validação dos dados do pôster (entrada manual, upload ou IA)."""

from __future__ import annotations

import re
from typing import Any, Dict, List


def _is_results_or_conclusions(sec: Dict[str, Any]) -> bool:
    sid = str(sec.get("id") or "").strip().lower()
    title = str(sec.get("title") or "").strip().lower()
    return bool(re.search(r"\b(results?|resultados?|conclusions?|conclus[oõ]es?)\b", f"{sid} {title}"))


def strip_citations(text: str) -> str:
    """Removes citations like [1], [1, 2], [1-3] or [Author, 2024] from text."""
    if not text:
        return ""
    # Strip numeric brackets [1], [1, 2], [1-3], [1–3]
    res = re.sub(r"\s*\[\s*\d+(?:\s*[,;\s–-]+\s*\d+)*\s*\]", "", text)
    # Strip author-year citations like [Truong and Koyejo 2026]
    res = re.sub(r"\s*\[[A-Za-zÀ-ÿ]+(?:\s+et\s+al\.?)?,?\s*\d{4}\]", "", res)
    # Fix spacing before punctuation (e.g. "comparações ." -> "comparações.")
    res = re.sub(r"[ \t]+([.,;:!?])", r"\1", res)
    return res


def format_grouped_emails(email_str: str) -> str:
    """Agrupa e-mails com mesmo domínio no formato {u1, u2}@sub.dominio.com."""
    if not email_str or not email_str.strip():
        return ""
    s = email_str.strip()
    grouped_re = re.compile(r"\{([^}]+)\}@([A-Za-z0-9.\-]+)")
    normal_re = re.compile(r"([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+)")
    extracted: List[Tuple[str, str]] = []
    matches_g = list(grouped_re.finditer(s))
    if matches_g:
        for m in matches_g:
            users_part = m.group(1)
            dom = m.group(2).lower()
            for u in re.split(r"[,;\s]+", users_part):
                u_clean = u.strip()
                if u_clean:
                    extracted.append((u_clean, dom))
        s = grouped_re.sub("", s)
    for m in normal_re.finditer(s):
        u = m.group(1).strip()
        dom = m.group(2).strip().lower()
        if u and dom:
            extracted.append((u, dom))
    if not extracted:
        return email_str.strip()
    domain_users: Dict[str, List[str]] = {}
    for u, dom in extracted:
        if dom not in domain_users:
            domain_users[dom] = []
        if u not in domain_users[dom]:
            domain_users[dom].append(u)
    parts: List[str] = []
    for dom, users in domain_users.items():
        if len(users) == 1:
            parts.append(f"{users[0]}@{dom}")
        else:
            joined = ", ".join(users)
            parts.append(f"{{{joined}}}@{dom}")
    return ", ".join(parts)


def renumber_citations(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Remaps citation numbers in all section texts so they match the references list.
    Only references actually cited in the poster text are retained in the references list.
    Supports bracketed numbers [9], dot numbers 9., or plain numbers at line starts (9 Author...).
    Also strips citations from Results and Conclusions sections, where references should not be used.
    """
    # Find references section
    ref_sec = None
    for sec in sections:
        if sec.get("id") == "references" or re.search(r"refer[eê]nc", sec.get("title", ""), re.IGNORECASE):
            ref_sec = sec
            break

    if not ref_sec or not ref_sec.get("content"):
        return [
            {**sec, "content": strip_citations(sec.get("content", ""))} if _is_results_or_conclusions(sec) else sec
            for sec in sections
        ]

    # Coleta todos os números de citação efetivamente utilizados nas seções (exceto Resultados e Conclusões)
    used_citations: set[int] = set()
    for sec in sections:
        if sec is ref_sec or _is_results_or_conclusions(sec):
            continue
        c_text = sec.get("content", "")
        for m in re.finditer(r"\[(\d+(?:[,;\s\u2013-]+\d+)*)\]", c_text):
            inner = m.group(1)
            for p in re.split(r"[,;]\s*", inner):
                p = p.strip()
                rng = re.match(r"^(\d+)\s*[-\u2013]\s*(\d+)$", p)
                if rng:
                    start, end = int(rng.group(1)), int(rng.group(2))
                    for n in range(start, end + 1):
                        used_citations.add(n)
                elif p.isdigit():
                    used_citations.add(int(p))

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
            # Se citações foram detectadas no texto, inclui SOMENTE referências citadas!
            if used_citations and old_num not in used_citations:
                continue
            if old_num not in old_to_new:
                old_to_new[old_num] = new_idx
                new_refs.append(f"[{new_idx}] {body}")
                new_idx += 1
        else:
            if not used_citations:
                new_refs.append(f"[{new_idx}] {ln}")
                new_idx += 1

    # Fallback: se nenhuma referência bateu com as citações numéricas, mantém as primeiras 4
    if not new_refs and lines:
        for ln in lines[:4]:
            m = re.match(r"^(?:\[(\d+)\]|(\d+)[.)]?)\s+(.+)", ln)
            body = m.group(3).strip() if m else ln
            new_refs.append(f"[{new_idx}] {body}")
            if m:
                old_num = int(m.group(1) or m.group(2))
                old_to_new[old_num] = new_idx
            new_idx += 1

    if not old_to_new:
        return [
            {**sec, "content": strip_citations(sec.get("content", ""))} if _is_results_or_conclusions(sec) else sec
            for sec in sections
        ]

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
        return re.sub(r"[ \t]{2,}", " ", res).replace(" .", ".").replace(" ,", ",")

    # Apply remapping to all sections (stripping citations from results and conclusions)
    result = []
    for sec in sections:
        if sec is ref_sec:
            result.append({**sec, "content": "\n".join(new_refs)})
        elif _is_results_or_conclusions(sec):
            result.append({**sec, "content": strip_citations(sec.get("content", ""))})
        else:
            result.append({**sec, "content": remap_text(sec.get("content", ""))})

    return result

from .config import LANGUAGES
from .i18n import LABELS, SECTION_ALIASES, labels_for
from .templates import DEFAULT_TEMPLATE, TEMPLATES, default_paper_for, papers_for

MAX_SECTIONS = 20
MAX_FIELD = 20_000


def _norm_key(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9 &]", " ", s).strip()


_ALL_SECTION_LABEL_MAP: Dict[str, str] = {}
for _sid, _aliases in SECTION_ALIASES.items():
    for _al in _aliases:
        _ALL_SECTION_LABEL_MAP[_norm_key(_al)] = _sid
for _l_dict in LABELS.values():
    for _sid, _lbl in _l_dict.items():
        if _sid not in ("figure", "babel"):
            _ALL_SECTION_LABEL_MAP[_norm_key(_lbl)] = _sid


def normalize_section_title_language(sid: str, raw_title: str, lang: str) -> str:
    """Garante que cabeçalhos de seções padrão ou equivalentes em outro idioma sigam estritamente `lang`."""
    labels = labels_for(lang)
    cleaned = re.sub(r"^\s*(?:\d+(?:\.\d+)*|[IVX]+)[\.\-\)]\s*", "", str(raw_title or "")).strip()
    norm_t = _norm_key(cleaned)

    if sid in labels and sid not in ("figure", "babel"):
        if not cleaned or _ALL_SECTION_LABEL_MAP.get(norm_t) == sid:
            return labels[sid]

    matched_sid = _ALL_SECTION_LABEL_MAP.get(norm_t)
    if matched_sid and matched_sid in labels:
        return labels[matched_sid]

    if not cleaned:
        return labels.get(sid) or sid.capitalize()
    return cleaned


_AFFIL_EN_TO_PT = [
    (r"\bDepartment\s+of\s+Computer\s+Science\b", "Departamento de Ciência da Computação"),
    (r"\bDepartment\s+of\s+Information\s+Systems\b", "Departamento de Sistemas de Informação"),
    (r"\bDepartment\s+of\s+Electrical\s+Engineering\b", "Departamento de Engenharia Elétrica"),
    (r"\bDepartment\s+of\s+Mechanical\s+Engineering\b", "Departamento de Engenharia Mecânica"),
    (r"\bDepartment\s+of\s+Civil\s+Engineering\b", "Departamento de Engenharia Civil"),
    (r"\bDepartment\s+of\s+Mathematics\b", "Departamento de Matemática"),
    (r"\bDepartment\s+of\s+Physics\b", "Departamento de Física"),
    (r"\bDepartment\s+of\s+Chemistry\b", "Departamento de Química"),
    (r"\bDepartment\s+of\s+Statistics\b", "Departamento de Estatística"),
    (r"\bDepartment\s+of\s+Engineering\b", "Departamento de Engenharia"),
    (r"\bDepartment\s+of\s+", "Departamento de "),
    (r"\bFederal\s+University\s+of\s+Minas\s+Gerais\b", "Universidade Federal de Minas Gerais"),
    (r"\bFederal\s+University\s+of\s+", "Universidade Federal de "),
    (r"\bState\s+University\s+of\s+", "Universidade Estadual de "),
    (r"\bUniversity\s+of\s+", "Universidade de "),
    (r"\bFederal\s+Institute\s+of\s+", "Instituto Federal de "),
    (r"\bInstitute\s+of\s+", "Instituto de "),
    (r"\bFaculty\s+of\s+", "Faculdade de "),
    (r"\bSchool\s+of\s+", "Escola de "),
    (r"\bCent(?:er|re)\s+for\s+", "Centro de "),
    (r"\bLaboratory\s+of\s+", "Laboratório de "),
    (r"\bBrazil\b", "Brasil"),
]

_AFFIL_PT_TO_EN = [
    (r"\bDepartamento\s+de\s+Ci[êe]ncia\s+da\s+Computa[çc][ãa]o\b", "Department of Computer Science"),
    (r"\bDepartamento\s+de\s+Sistemas\s+de\s+Informa[çc][ãa]o\b", "Department of Information Systems"),
    (r"\bDepartamento\s+de\s+Engenharia\s+El[ée]trica\b", "Department of Electrical Engineering"),
    (r"\bDepartamento\s+de\s+Engenharia\s+Mec[âa]nica\b", "Department of Mechanical Engineering"),
    (r"\bDepartamento\s+de\s+Engenharia\s+Civil\b", "Department of Civil Engineering"),
    (r"\bDepartamento\s+de\s+Matem[áa]tica\b", "Department of Mathematics"),
    (r"\bDepartamento\s+de\s+F[íi]sica\b", "Department of Physics"),
    (r"\bDepartamento\s+de\s+Qu[íi]mica\b", "Department of Chemistry"),
    (r"\bDepartamento\s+de\s+Estat[íi]stica\b", "Department of Statistics"),
    (r"\bDepartamento\s+de\s+Engenharia\b", "Department of Engineering"),
    (r"\bDepartamento\s+d[eoa]s?\s+", "Department of "),
    (r"\bUniversidade\s+Federal\s+de\s+Minas\s+Gerais\b", "Federal University of Minas Gerais"),
    (r"\bUniversidade\s+Federal\s+d[eoa]s?\s+", "Federal University of "),
    (r"\bUniversidade\s+Estadual\s+d[eoa]s?\s+", "State University of "),
    (r"\bUniversidade\s+d[eoa]s?\s+", "University of "),
    (r"\bInstituto\s+Federal\s+d[eoa]s?\s+", "Federal Institute of "),
    (r"\bInstituto\s+d[eoa]s?\s+", "Institute of "),
    (r"\bFaculdade\s+d[eoa]s?\s+", "Faculty of "),
    (r"\bEscola\s+d[eoa]s?\s+", "School of "),
    (r"\bCentro\s+d[eoa]s?\s+", "Center for "),
    (r"\bLaborat[óo]rio\s+d[eoa]s?\s+", "Laboratory of "),
    (r"\bBrasil\b", "Brazil"),
]


def normalize_affiliations_language(affiliations: str, lang: str) -> str:
    """Normaliza termos institucionais comuns nas afiliações para o idioma selecionado (`pt-BR` ou `en-US`)."""
    if not affiliations or not affiliations.strip():
        return ""
    res = affiliations
    rules = _AFFIL_EN_TO_PT if lang == "pt-BR" else _AFFIL_PT_TO_EN
    for pattern, repl in rules:
        res = re.sub(pattern, repl, res, flags=re.IGNORECASE)
    return res


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
    other_lang = "en-US" if lang == "pt-BR" else "pt-BR"
    other_labels = labels_for(other_lang)
    for i, sec in enumerate((raw_sections or [])[:MAX_SECTIONS]):
        if not isinstance(sec, dict):
            continue
        sid = _s(sec.get("id"), 40) or f"custom{i}"
        title = normalize_section_title_language(sid, _s(sec.get("title"), 200), lang)
        content = _s(sec.get("content"))
        images = []
        for img in sec.get("images") or []:
            if isinstance(img, dict) and img.get("path"):
                images.append({"path": str(img["path"]), "caption": _s(img.get("caption"), 400)})
        if not (content or images):
            continue
        sections.append({"id": sid, "title": title, "content": content, "images": images})

    sections = renumber_citations(sections)

    colors: Dict[str, str] = {}
    if isinstance(data.get("colors"), dict):
        for k in ("accent", "title", "subtitle", "body", "caption", "bg"):
            val = data["colors"].get(k)
            if val:
                colors[k] = _hex(val, "")

    raw_title = _s(data.get("title"), 500)
    default_titles = {"pt-BR": "Título do Pôster", "en-US": "Research Poster Title"}
    other_default = default_titles.get(other_lang, "").lower()
    if not raw_title or raw_title.strip().lower() == other_default:
        poster_title = default_titles.get(lang, "Título do Pôster")
    else:
        poster_title = raw_title

    return {
        "language": lang,
        "template": template,
        "paper": paper,
        "orientation": orientation,
        "columns": columns,
        "accent": _hex(data.get("accent"), ""),
        "colors": colors,
        "title": poster_title,
        "authors": _s(data.get("authors"), 1500),
        "affiliations": normalize_affiliations_language(_s(data.get("affiliations"), 2000), lang),
        "email": format_grouped_emails(_s(data.get("email"), 400)),
        "url": _s(data.get("url"), 300),
        "logos_header": logos_header,
        "logos_footer": logos_footer,
        "sections": sections,
    }

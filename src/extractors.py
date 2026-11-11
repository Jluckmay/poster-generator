"""Extração de texto de trabalhos enviados (PDF, DOCX, TXT/MD/TEX) e parser heurístico."""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from typing import Any, Dict, List

from .config import MAX_DOC_CHARS
from .i18n import SECTION_ALIASES

ALLOWED_DOC_EXT = (".pdf", ".docx", ".txt", ".md", ".tex")
_MAX_ZIP_XML = 30 * 1024 * 1024


def extract_text(filename: str, raw: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        text = _pdf_text(raw)
    elif name.endswith(".docx"):
        text = _docx_text(raw)
    elif name.endswith(ALLOWED_DOC_EXT):
        text = raw.decode("utf-8", "replace")
        if name.endswith(".tex"):
            text = _strip_tex(text)
    else:
        raise ValueError("Formato não suportado. Use PDF, DOCX, TXT, MD ou TEX.")
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = clean_hyphens(text)
    return text.strip()[:MAX_DOC_CHARS]


def _pdf_text(raw: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        raise ValueError("PDF protegido por senha não é suportado.")
    return "\n".join((p.extract_text() or "") for p in reader.pages[:60])


def _docx_text(raw: bytes) -> str:
    from defusedxml import ElementTree as ET

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        info = zf.getinfo("word/document.xml")
        if info.file_size > _MAX_ZIP_XML:
            raise ValueError("DOCX grande demais.")
        root = ET.fromstring(zf.read("word/document.xml"))
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paras = []
    for p in root.iter(f"{ns}p"):
        paras.append("".join(t.text or "" for t in p.iter(f"{ns}t")))
    return "\n".join(paras)


def _strip_tex(src: str) -> str:
    src = re.sub(r"(?<!\\)%.*", "", src)
    m = re.search(r"\\begin\{document\}(.*)\\end\{document\}", src, re.S)
    body = m.group(1) if m else src
    title = re.search(r"\\title\{([^}]*)\}", src)
    body = re.sub(r"\\(?:sub)*section\*?\{([^}]*)\}", r"\n\1\n", body)
    body = re.sub(r"\\begin\{abstract\}", "\nAbstract\n", body)
    body = re.sub(r"\\(?:textbf|textit|emph|cite)\{([^}]*)\}", r"\1", body)
    body = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", "", body).replace("{", "").replace("}", "")
    return (title.group(1) + "\n" if title else "") + body


_SUFFIX_FRAGMENTS = {
    "ties", "ence", "ences", "tion", "tions", "ment", "ments", "ted",
    "ting", "able", "ible", "ing", "ings", "ity", "ities", "ive", "ives",
    "ally", "al", "als", "ularization", "ization", "izations", "ised", "ized",
    "ness", "nesses", "sion", "sions", "ture", "tures", "ous", "ously",
    "ated", "ating", "ates", "ance", "ances", "ism", "isms", "ist", "ists"
}

_INST_PREFIXES = {
    "universidade", "university", "departamento", "department", "instituto",
    "institute", "laboratorio", "laboratory", "faculdade", "faculty",
    "escola", "school", "centro", "center", "hospital", "campus", "dept",
    "college", "program", "programa"
}

_INST_ACRONYMS = {
    "ufmg", "usp", "unicamp", "ufrj", "unesp", "puc", "ufpe", "ufrgs",
    "ufba", "ufsc", "ufscar", "uff", "unb", "ufc", "mit", "cmu", "stanford",
    "berkeley", "oxford", "cambridge", "inria", "cnrs", "embrapa"
}

_AFFIL_KEYWORDS = _INST_PREFIXES | _INST_ACRONYMS | {"federal", "estadual", "nacional"}


def clean_hyphens(text: str) -> str:
    """Conserta palavras quebradas por hífens de fim de linha ou OCR em PDFs."""
    # Quebra de linha direta com hífen: word-\nnext -> wordnext
    text = re.sub(r"(\b[A-Za-z]{2,})-\s*\n\s*([a-z]{2,}\b)", r"\1\2", text)
    # Hífen com espaço inline oriundo de quebra de página/coluna: differ- ences -> differences
    def _fix_broken(m: re.Match) -> str:
        w1, w2 = m.group(1), m.group(2)
        if w2.lower() in _SUFFIX_FRAGMENTS or len(w1) <= 3:
            return w1 + w2
        return f"{w1}-{w2}"

    return re.sub(r"\b([A-Za-z]{2,})-\s+([a-z]{2,}\b)", _fix_broken, text)


def _format_references(raw: str, max_refs: int = 4) -> str:
    """Formata referências bibliográficas uma por linha, suportando formatos numéricos [1], 1. e autor-ano (APA/SBC/Harvard), limitadas a max_refs."""
    text = clean_hyphens(raw)
    text = re.sub(r"\s*(\[\d{1,3}\])\s*", r"\n\1 ", text)
    text = re.sub(r"(?<=[.\s])(\d{1,2}\.\s+[A-ZÀ-ÿ])", r"\n\1", text)
    text = re.sub(r"(?<=[.\d\n])\s+([A-ZÀ-ÿ][a-zA-ZÀ-ÿ'-]+,\s+[A-ZÀ-ÿ]\.)", r"\n\1", text)

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""

    _START = re.compile(
        r"^(?:\[\d{1,3}\]|\d{1,2}\.\s+[A-ZÀ-ÿ]|[A-ZÀ-ÿ][a-zA-ZÀ-ÿ'-]+,\s+[A-ZÀ-ÿ]\.|\b[A-ZÀ-ÿ][a-zA-ZÀ-ÿ'-]+\s+et\s+al\.)"
    )
    entries: List[str] = []
    for ln in lines:
        if entries and not _START.match(ln):
            entries[-1] += " " + ln
        else:
            entries.append(ln)

    cleaned: List[str] = []
    for e in entries[:max_refs]:
        c = re.sub(r"https?://\S+", "", e)
        c = re.sub(r"\bdoi:\s*\S+", "", c, flags=re.IGNORECASE)
        c = re.sub(r"\bURL\b:?", "", c)
        c = re.sub(r"[ \t]+", " ", c).strip(" ,.-")
        if c:
            cleaned.append(c)

    return "\n".join(cleaned)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9 &]", " ", s).strip()


_ALIAS_LOOKUP = {_norm(a): sid for sid, al in SECTION_ALIASES.items() for a in al}
_NUM = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s+")

_SECTION_KEYWORDS = {
    "conclusions": {"conclusion", "conclusions", "conclusao", "conclusoes", "remarks", "future work"},
    "results": {"result", "results", "resultado", "resultados", "findings", "experiments", "experimentos", "performance", "empirical", "benchmark"},
    "methods": {"method", "methods", "methodology", "metodologia", "metodos", "framework", "approach", "abordagem", "architecture", "arquitetura", "design", "setup", "evaluation", "avaliacao", "system", "model", "modelo", "proposed", "proposta", "implementation", "implementacao"},
    "introduction": {"introduction", "introducao", "background", "contexto", "motivation"},
    "abstract": {"abstract", "resumo", "summary"},
}

_GEO_KEYWORDS = {"brazil", "brasil", "minas", "gerais", "mg", "sp", "rj", "federal", "state"}


def _extract_all_emails(text: str) -> List[str]:
    """Extrai emails tanto no formato tradicional quanto agrupado {a, b}@dominio."""
    emails = []
    for m in re.finditer(r"\{([^}]+)\}\s*@([\w-]+(?:\.[\w-]+)+)", text):
        users = [u.strip() for u in m.group(1).split(",")]
        domain = m.group(2)
        for u in users:
            if u:
                emails.append(f"{u}@{domain}")
    clean_text = re.sub(r"\{[^}]+\}\s*@[\w-]+(?:\.[\w-]+)+", " ", text)
    for m in re.finditer(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", clean_text):
        emails.append(m.group(0))
    return emails


def _heading(line: str) -> tuple[str, str] | None:
    """Retorna (id_da_seção, texto_inline) se a linha for um cabeçalho conhecido."""
    raw = line.strip()
    if not raw:
        return None
    has_num = bool(_NUM.match(raw))
    body = _NUM.sub("", raw).strip()
    if not body:
        return None

    # 1. Cabeçalho inline com delimitador: "Abstract. Texto...", "Resumo: Texto...", "1. Introdução: Texto..."
    m = re.match(r"^([A-Za-z\u00C0-\u00FF0-9 &/-]{3,40}?)\s*[:.—–-]\s*(.*)$", body)
    if m:
        term = _norm(m.group(1))
        sid = _ALIAS_LOOKUP.get(term)
        if sid:
            return sid, m.group(2).strip()

    # 2. Cabeçalho direto por alias exato (ex: "Metodologia", "2. Introdução", "4. Results and Analysis")
    norm_body = _norm(body.rstrip(":."))
    sid = _ALIAS_LOOKUP.get(norm_body)
    if sid:
        return sid, ""

    # 3. Fallback por palavras-chave (prefixo do corpo):
    # Cabeçalhos numerados podem vir fundidos ao corpo do texto na extração de
    # PDF (ex: "2. METODOLOGIA Foram usados..."). Só aceita se a palavra-chave da
    # seção estiver no INÍCIO do corpo; o restante da linha vira conteúdo inline.
    # Isso evita confundir subseções como "4.1. Conditional Performance..." com
    # cabeçalho de seção (a palavra "performance" aparece no meio da linha).
    if has_num:
        body_words_norm = norm_body.split()
        body_words_orig = body.split()
        for target_sid, kw_set in _SECTION_KEYWORDS.items():
            for kw in kw_set:
                kw_words = kw.split()
                if len(body_words_norm) >= len(kw_words) and body_words_norm[: len(kw_words)] == kw_words:
                    remaining = " ".join(body_words_orig[len(kw_words) :]).strip()
                    return target_sid, remaining
    # Títulos curtos não numerados (ex: "Metodologia", "Resultados")
    is_short_title = len(body.split()) <= 6 and len(raw) <= 50 and not raw.endswith((".", ",", ";", ":"))
    if is_short_title:
        words = set(norm_body.split())
        for target_sid, kw_set in _SECTION_KEYWORDS.items():
            if words & kw_set:
                return target_sid, ""

    return None


def _condense(text: str, limit: int) -> str:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind(".\n"))
    return (cut[: end + 1] if end > limit * 0.5 else cut.rstrip() + "…").strip()


def _classify_header_line(line: str) -> tuple[List[str], List[str]]:
    """Separa autores e afiliações de uma linha do cabeçalho do artigo."""
    clean = re.sub(r"\{[^}]+\}\s*@[\w-]+(?:\.[\w-]+)+", " ", line)
    clean = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", " ", clean).strip()
    if not clean:
        return [], []

    # Se a linha contiver múltiplos blocos separados por vírgula (comum em layouts SBC/ACM)
    if "," in clean:
        clauses = [c.strip() for c in clean.split(",") if c.strip()]
        auth_out = []
        aff_out = []
        for c in clauses:
            c_clean = re.sub(r"^[\d*†‡^]+\s*", "", c).strip()
            tokens = c_clean.split()
            norm_tokens = [_norm(t) for t in tokens]
            if not norm_tokens:
                continue
            is_aff = any(t in _INST_PREFIXES or t in _INST_ACRONYMS or t in _GEO_KEYWORDS for t in norm_tokens)
            if is_aff:
                aff_out.append(c_clean)
            else:
                author_name = re.sub(r"[\d*†‡^]+$", "", c).strip()
                if author_name:
                    auth_out.append(author_name)
        if auth_out or aff_out:
            return auth_out, aff_out

    tokens = clean.split()
    norm_tokens = [_norm(t) for t in tokens]

    # Linha iniciada por prefixo institucional claro (ex: "Universidade Federal...", "Department of...")
    if any(norm_tokens[0] == p for p in _INST_PREFIXES) or (len(norm_tokens) > 1 and norm_tokens[1] in _INST_PREFIXES):
        return [], [clean]

    # Linha contendo apenas siglas ou termos institucionais puros (ex: "UFMG", "DCC / UFMG")
    if all(t in _INST_ACRONYMS or t in _INST_PREFIXES or t in {"de", "da", "do", "e", "of", "and", "/", "-", "dcc"} for t in norm_tokens):
        return [], [clean]

    # Linha mista com sigla institucional e nome de pessoa (ex: "UFMG Luiz Filipe Menezes Vieira" ou "Brendo Gético Eugênio UFMG")
    acronym_tokens = [w for w, nt in zip(tokens, norm_tokens) if nt in _INST_ACRONYMS or nt in _INST_PREFIXES]
    name_tokens = [w for w, nt in zip(tokens, norm_tokens) if nt not in _INST_ACRONYMS and nt not in _INST_PREFIXES]
    if acronym_tokens and name_tokens:
        aff = " ".join(acronym_tokens).strip()
        auth = " ".join(name_tokens).strip()
        return ([auth] if auth else []), ([aff] if aff else [])

    author_name = re.sub(r"[\d*†‡^]+$", "", clean).strip()
    return ([author_name] if author_name else []), []


def heuristic_parse(text: str) -> Dict[str, Any]:
    """Extração sem IA: detecta título/autores e seções pelos cabeçalhos usuais."""
    text = clean_hyphens(text)
    # Garante que cabeçalhos de seção embutidos em linhas de autores/emails iniciem em nova linha
    text = re.sub(
        r"(?:,\s*|\.\s+|\s{2,})\b(Abstract|Resumo|Introduction|Introdução|Methods|Metodologia|Results|Resultados|Discussion|Discussão|Conclusions?|Conclus[oõ]es?|References|Referências)\s*[:.—–-]\s*",
        lambda m: f"\n{m.group(1)}: ",
        text,
        flags=re.IGNORECASE,
    )
    # Insere quebra de linha antes de cabeçalhos de seção numerados que aparecem
    # no meio de uma linha (comum em PDFs de duas colunas onde a extração de texto
    # funde o final de uma seção com o cabeçalho da próxima, ex: "...conclusão.2. Métodos"
    # ou "...introdução 2. METODOLOGIA ..."). Isso evita que a primeira seção
    # consuma todo o documento como conteúdo.
    _HEADING_KEYWORDS = (
        "Abstract|Resumo|Introduction|Introdução|Methods|Metodologia|Results|Resultados|"
        "Discussion|Discussão|Conclusions?|Conclus[oõ]es?|References|Referências"
    )
    text = re.sub(
        r"\.\s*(?=\d+(?:\.\d+)*\.?\s+(?:" + _HEADING_KEYWORDS + r")\b)",
        ".\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?<=\w)\s+(?=\d+(?:\.\d+)*\.?\s+(?:" + _HEADING_KEYWORDS + r")\b)",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    lines = text.split("\n")
    sections: Dict[str, List[str]] = {}
    current: str | None = None
    head: List[str] = []
    for line in lines:
        h = _heading(line)
        if h:
            current = h[0]
            sections.setdefault(current, [])
            if h[1]:
                sections[current].append(h[1])
            continue
        if current is None:
            if line.strip():
                head.append(line.strip())
        else:
            sections[current].append(line)

    # Identificar emails e tokens de nome de usuário dos autores
    header_blob = "\n".join(head)
    emails = _extract_all_emails(header_blob or text[:3000])
    email_tokens = set()
    for e in emails:
        user = e.split("@")[0]
        for part in re.split(r"[._+-]", user):
            if len(part) >= 3:
                email_tokens.add(_norm(part))

    title_parts: List[str] = []
    authors_list: List[str] = []
    affiliations_list: List[str] = []

    idx = 0
    while idx < len(head) and idx < 3:
        line = head[idx]
        h_norm = _norm(line)
        if "@" in line or any(k in h_norm.split() for k in _AFFIL_KEYWORDS):
            break

        words = line.split()
        matched = [i for i, w in enumerate(words) if _norm(w) in email_tokens]
        if matched:
            first_m = matched[0]
            start = max(0, first_m - 1)
            t_part = " ".join(words[:start]).strip()
            a_part = " ".join(words[start:]).strip()
            if t_part:
                title_parts.append(t_part)
            if a_part:
                auths, affs = _classify_header_line(a_part)
                authors_list.extend(auths)
                affiliations_list.extend(affs)
            idx += 1
            break
        else:
            if idx > 0 and ("," in line or re.search(r"\band\b| e ", line)):
                break
            title_parts.append(line)
            idx += 1
            if len(line) < 40 and idx > 1:
                break

    title = " ".join(title_parts).strip()

    for h_line in head[idx:]:
        auths, affs = _classify_header_line(h_line)
        authors_list.extend(auths)
        affiliations_list.extend(affs)

    unique_authors: List[str] = []
    for a in authors_list:
        for sub_a in re.split(r",|\s+e\s+|\s+and\s+", a):
            sub_a = sub_a.strip()
            if not sub_a:
                continue
            sub_clean = re.sub(r"^[\d*†‡^]+\s*", "", sub_a).strip()
            sub_norm = _norm(sub_clean)
            if any(k in sub_norm.split() for k in _AFFIL_KEYWORDS) or any(k in sub_norm.split() for k in _GEO_KEYWORDS):
                if sub_clean not in affiliations_list:
                    affiliations_list.append(sub_clean)
            else:
                cleaned_name = re.sub(r"[\d*†‡^]+$", "", sub_clean).strip()
                if cleaned_name and cleaned_name not in unique_authors:
                    unique_authors.append(cleaned_name)

    authors = ", ".join(unique_authors)
    affiliations = "\n".join(dict.fromkeys([af.strip() for af in affiliations_list if af.strip()]))

    # Sem sessão de resumo no pôster: se abstract existir, incorpora no início da Introdução
    if "abstract" in sections:
        if "introduction" not in sections:
            sections["introduction"] = sections["abstract"]
        else:
            sections["introduction"] = sections["abstract"] + ["\n"] + sections["introduction"]
    if "objectives" in sections and "introduction" in sections:
        sections["introduction"].extend(sections["objectives"])
    if "discussion" in sections and "results" in sections:
        sections["results"].extend(sections["discussion"])

    limits = {"references": 800, "acknowledgments": 400}
    out_sections = []
    from .i18n import DEFAULT_SECTION_IDS

    for sid in DEFAULT_SECTION_IDS:
        if sid in sections:
            buf = sections[sid]
            content = "\n".join(buf).strip()
            if content:
                body = _format_references(content) if sid == "references" else _unwrap(clean_hyphens(content))
                out_sections.append({"id": sid, "content": _condense(body, limits.get(sid, 1100))})

    return {
        "title": title[:300].strip(),
        "authors": authors[:600].strip(),
        "affiliations": affiliations[:800].strip(),
        "email": emails[0] if emails else "",
        "sections": out_sections,
    }


def _unwrap(text: str) -> str:
    """Junta quebras de linha de PDF dentro de parágrafos, preservando listas e hífens corrigidos."""
    text = clean_hyphens(text)
    out: List[str] = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            out.append("")
        elif out and out[-1] and not re.match(r"^(?:[-*•–]|\d{1,2}[.)])\s", s) and not out[-1].endswith(":"):
            out[-1] += " " + s
        else:
            out.append(s)
    return "\n".join(out)

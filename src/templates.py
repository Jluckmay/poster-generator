"""Definições dos templates visuais (estilos tikzposter + `article`/multicols + paleta)."""

from __future__ import annotations

from typing import Any, Dict

from .config import MAX_LOGOS_FOOTER, MAX_LOGOS_HEADER, POSTER_SIZES

DEFAULT_TEMPLATE = "classic"

TIKZ_PAPERS = list(POSTER_SIZES)

# colors: colorOne (moldura/destaque), colorTwo, colorThree
# bg: fundo do pôster (HTML hex sem '#')
# logos: vagas de logotipos por região do template (cabeçalho/rodapé)
TEMPLATES: Dict[str, Dict[str, Any]] = {
    "classic": {
        "name": {"pt-BR": "Clássico", "en-US": "Classic"},
        "engine": "tikzposter",
        "block": "Default", "title": "Filled", "background": "Default",
        "colors": ("1F3A5F", "2E5C8A", "9DB9D8"), "bg": "EEF2F7", "sans": False,
        "logos": {"header": MAX_LOGOS_HEADER, "footer": MAX_LOGOS_FOOTER},
    },
    "modern": {
        "name": {"pt-BR": "Moderno", "en-US": "Modern"},
        "engine": "tikzposter",
        "block": "Basic", "title": "Basic", "background": "VerticalGradient",
        "colors": ("0F766E", "14B8A6", "99F6E4"), "bg": "F0FDFA", "sans": True,
        "logos": {"header": MAX_LOGOS_HEADER, "footer": MAX_LOGOS_FOOTER},
    },
    "minimal": {
        "name": {"pt-BR": "Minimalista", "en-US": "Minimal"},
        "engine": "tikzposter",
        "block": "Minimal", "title": "Empty", "background": "Default",
        "colors": ("1E293B", "475569", "94A3B8"), "bg": "FAFAFA", "sans": True,
        "logos": {"header": MAX_LOGOS_HEADER, "footer": MAX_LOGOS_FOOTER},
    },
    "bold": {
        "name": {"pt-BR": "Ousado", "en-US": "Bold"},
        "engine": "tikzposter",
        "block": "Envelope", "title": "Filled", "background": "Default",
        "colors": ("7C2D12", "EA580C", "FED7AA"), "bg": "FFF7ED", "sans": True,
        "logos": {"header": MAX_LOGOS_HEADER, "footer": MAX_LOGOS_FOOTER},
    },
    "corner": {
        "name": {"pt-BR": "Ondas Esmeralda", "en-US": "Emerald Waves"},
        "engine": "tikzposter",
        "block": "Corner", "title": "Wave", "background": "BottomVerticalGradient",
        "colors": ("064E3B", "059669", "A7F3D0"), "bg": "F0FDF4", "sans": False,
        "logos": {"header": MAX_LOGOS_HEADER, "footer": MAX_LOGOS_FOOTER},
    },
    "dcc": {
        "name": {"pt-BR": "Academic Red", "en-US": "Academic Red"},
        "engine": "article",
        "colors": ("CC0000", "444444", "1A1A1A"), "bg": "FFFFFF", "sans": True,
        "default_columns": 2,
        "papers": None, "default_paper": "60x90",
        "logos": {"header": MAX_LOGOS_HEADER, "footer": MAX_LOGOS_FOOTER},
    },
    "mostra_ic": {
        "name": {"pt-BR": "Mostra IC", "en-US": "Mostra IC"},
        "engine": "sciposter",
        "colors": ("0A3B75", "1F2937", "4B5563"), "bg": "FFFFFF", "sans": False,
        "default_columns": 2,
        "papers": None, "default_paper": "60x90",
        "logos": {"header": MAX_LOGOS_HEADER, "footer": MAX_LOGOS_FOOTER},
    },
    "uzh": {
        "name": {"pt-BR": "UZH / LiRI", "en-US": "UZH / LiRI"},
        "engine": "a0poster",
        "colors": ("0028A5", "3353B7", "1F2937"), "bg": "FFFFFF", "sans": True,
        "default_columns": 2,
        "papers": None, "default_paper": "60x90",
        "logos": {"header": MAX_LOGOS_HEADER, "footer": MAX_LOGOS_FOOTER},
    },
    "tudelft": {
        "name": {"pt-BR": "TU Delft", "en-US": "TU Delft"},
        "engine": "beamer",
        "colors": ("00A6D6", "002B49", "007396"), "bg": "F8FAFC", "sans": True,
        "default_columns": 2,
        "papers": None, "default_paper": "60x90",
        "logos": {"header": MAX_LOGOS_HEADER, "footer": MAX_LOGOS_FOOTER},
    },
}


def papers_for(tid: str) -> list:
    return TEMPLATES[tid].get("papers") or TIKZ_PAPERS


def default_paper_for(tid: str) -> str:
    return TEMPLATES[tid].get("default_paper", "60x90")


def public_templates() -> Dict[str, Any]:
    return {
        tid: {
            "name": t["name"],
            "colors": list(t["colors"]),
            "bg": t["bg"],
            "papers": papers_for(tid),
            "default_paper": default_paper_for(tid),
            "logos": t["logos"],
        }
        for tid, t in TEMPLATES.items()
    }

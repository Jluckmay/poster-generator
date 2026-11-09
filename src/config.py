"""Configuração central: provedores de IA, tamanhos de pôster e limites."""

from __future__ import annotations

import os
from typing import Any, Dict

LANGUAGES = ("pt-BR", "en-US")
DEFAULT_LANGUAGE = "pt-BR"
DEFAULT_PAPER = "60x90"

MAX_UPLOAD_BYTES = 60 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGES_TOTAL = 40
MAX_DOC_CHARS = 120_000
LATEX_TIMEOUT_S = 150

# 5 dimensões mais usadas (largura x altura em cm, retrato) e fonte base do tikzposter.
POSTER_SIZES: Dict[str, Dict[str, Any]] = {
    "60x90": {"cm": (60.0, 90.0), "font": "20pt"},
    "90x120": {"cm": (90.0, 120.0), "font": "25pt"},
    "a0": {"cm": (84.1, 118.9), "font": "25pt"},
    "a1": {"cm": (59.4, 84.1), "font": "20pt"},
    "a2": {"cm": (42.0, 59.4), "font": "17pt"},
}

# Limites de logotipos por região
MAX_LOGOS_HEADER = 2
MAX_LOGOS_FOOTER = 5

DEFAULT_PROVIDER = "nvidia"

# Provedores: chave via campo da requisição (nunca armazenada) ou variável de ambiente.
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "nvidia": {
        "name": "NVIDIA NIM",
        "env": "NVIDIA_API_KEY",
        "default_model": "nvidia/nemotron-3.5-super-vl-120b-a12b",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
    },
    "google": {
        "name": "Google Gemini",
        "env": "GEMINI_API_KEY",
        "default_model": "gemini-2.0-flash",
    },
    "openai": {
        "name": "OpenAI",
        "env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "url": "https://api.openai.com/v1/chat/completions",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "env": "ANTHROPIC_API_KEY",
        "default_model": "claude-3-5-haiku-latest",
        "url": "https://api.anthropic.com/v1/messages",
    },
    "deepseek": {
        "name": "DeepSeek",
        "env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "url": "https://api.deepseek.com/chat/completions",
    },
}


_EXPIRED_SERVER_KEYS: set[str] = set()


def mark_server_key_invalid(provider: str) -> None:
    _EXPIRED_SERVER_KEYS.add(provider)


def server_key_for(provider: str) -> str:
    if provider in _EXPIRED_SERVER_KEYS:
        return ""
    cfg = PROVIDERS.get(provider)
    return os.environ.get(cfg["env"], "").strip() if cfg else ""


def public_provider_info() -> Dict[str, Any]:
    return {
        pid: {
            "name": cfg["name"],
            "default_model": cfg["default_model"],
            "server_key": bool(server_key_for(pid)),
        }
        for pid, cfg in PROVIDERS.items()
    }

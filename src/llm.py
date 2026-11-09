"""Cliente multi-provedor para transformar o texto de um trabalho em conteúdo de pôster."""

from __future__ import annotations

import json
import re
from typing import Any, Dict

import requests

from .config import PROVIDERS, server_key_for
from .i18n import DEFAULT_SECTION_IDS

TIMEOUT_S = 45

_LANG_NAME = {"pt-BR": "Brazilian Portuguese", "en-US": "American English"}

SYSTEM_PROMPT = """You are an expert academic researcher and designer converting academic papers into structured, high-impact content for a scientific poster.
Return ONLY a valid JSON object, no markdown fences, with this exact shape:
{"title": str, "authors": str, "affiliations": str (one per line), "email": str,
 "sections": {"introduction": str, "methods": str, "results": str, "conclusions": str, "references": str}}

CRITICAL MANDATORY RULES:

1. POSTER STRUCTURE (STRICTLY 5 SECTIONS - NO ABSTRACT):
   - The poster consists of EXACTLY these 5 sections:
     "introduction", "methods", "results", "conclusions", "references".
   - DO NOT include an "abstract" section (scientific posters do not have an abstract).
   - If the source paper has an abstract, synthesize its core motivation and context into the "introduction".
   - If the paper has "objectives", synthesize them into "introduction" or "methods".

2. TARGET LANGUAGE & TRANSLATION (ABSOLUTE REQUIREMENT):
   - Target Language: {language}.
   - ALL content without exception (title, introduction, methods, results, conclusions, table headers, bullet points, captions) MUST be written strictly in {language}.
   - If the source paper is written in English (or any other language) and the target language is Brazilian Portuguese, you MUST TRANSLATE and synthesize ALL sections into clear, fluent, academic Brazilian Portuguese (PT-BR).
   - NEVER leave English sentences, paragraphs, or table headers in a Brazilian Portuguese poster (except universal acronyms such as IoT, AI, F1, 2PL, LSTM, CUDA, etc.).

3. MANDATORY VISUAL ELEMENTS IN METHODS & RESULTS (TABLES, DIAGRAMS & CHARTS):
   - In "methods": YOU MUST generate a methodology pipeline diagram or architecture flowchart using TikZ (\\begin{tikzpicture}...\\end{tikzpicture}) or a structured sequence with boxes and arrows (e.g. [Entrada] -> [Processamento] -> [Classificação]), based on the paper's actual methodology!
   - In "results": If the paper contains ANY quantitative data, benchmarks, metrics, accuracy/F1 comparisons, or model calibrations, YOU MUST synthesize them into a clean, compact LaTeX table using the tabular environment (or Markdown table syntax):
     \\begin{center}
     \\small
     \\begin{tabular}{|l|c|c|}
     \\hline
     \\textbf{Modelo / Método} & \\textbf{Macro F1} & \\textbf{Calibração} \\\\
     \\hline
     Random Forest & 0.965 & Alta \\\\
     Transformer & 0.892 & Moderada \\\\
     LSTM & 0.824 & Estável \\\\
     Baseline & 0.731 & Padrão \\\\
     \\hline
     \\end{tabular}
     \\end{center}
     DO NOT bury quantitative results inside a long block of text. Readers MUST see data visualized in a table or chart!

4. CITATIONS IN TEXT AS COMPACT SUPERSCRIPT NUMBERS:
   - Citations in the text MUST appear as compact bracketed numbers corresponding to the references list, e.g. [1], [2], [1, 3].
   - They will be typeset as floating superscripts to save poster space.
   - Example: "...modelos calibrados com curvas IRT [1], demonstrando superioridade de generalização [2]."

5. REFERENCES FILTERING (STRICTLY 3 TO 4 KEY REFERENCES):
   - Posters have strictly limited space. Include ONLY the 3 to 4 most relevant references cited in the paper (e.g. seminal papers, key datasets).
   - NEVER dump the paper's full bibliography!
   - Format each reference in a single line:
     [1] Author, A. et al. (Year). Short Title. Conference/Journal.
     [2] Author, B. et al. (Year). Short Title. Conference/Journal.

6. TEXT FORMATTING & VISUAL SCANNABILITY (NO MONOLITHIC PARAGRAPHS):
   - Academic posters are read from 1 to 2 meters away. NEVER output monolithic walls of text.
   - Format sections using concise bullet points (lines starting with "- ").
   - Use bold lead-ins for key points:
     - **Contexto:** ...
     - **Problema & Lacuna:** ...
     - **Metodologia Proposta:** ...
     - **Principais Achados:** ...
   - Highlight key metrics, numbers, models, and findings in **bold** (e.g. **Macro F1 de 0.965**, **Random Forest**, **6.561.840 respostas**).

7. SECTION BALANCING & LENGTH EQUILIBRIUM:
   - Ensure sections are well-balanced in length (approx. 70 to 120 words each, plus any table/diagram) so poster columns are visually harmonious and balanced.

8. ABSOLUTE TRUTHFULNESS:
   - Be strictly faithful to the source paper. NEVER invent or hallucinate metrics, facts, or numbers not present in the paper.
   - Fix broken syllable line-breaks from PDF extraction (e.g., "proper- ties" -> "properties").

9. Title & Metadata Isolation: "title" must ONLY contain the title of the paper. Keep authors, affiliations and emails strictly separated in their dedicated fields."""


class LLMError(RuntimeError):
    pass


def resolve_key(provider: str, user_key: str | None) -> str:
    key = (user_key or "").strip() or server_key_for(provider)
    if not key:
        raise LLMError("Chave de API ausente para o provedor selecionado.")
    return key


def chat(provider: str, api_key: str, model: str | None, system: str, user: str) -> str:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise LLMError("Provedor desconhecido.")
    model = model or cfg["default_model"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}", model) or ".." in model or model.startswith("/") or (provider == "google" and "/" in model):
        raise LLMError("Nome de modelo inválido.")
    try:
        if provider == "google":
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
                },
                timeout=TIMEOUT_S,
            )
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if provider == "anthropic":
            r = requests.post(
                cfg["url"],
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                json={
                    "model": model, "max_tokens": 4096, "temperature": 0.2, "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=TIMEOUT_S,
            )
            r.raise_for_status()
            return r.json()["content"][0]["text"]
        # Provedores OpenAI / NVIDIA / DeepSeek com fallback resiliente de modelos para NVIDIA NIM
        models_to_try = [model] if model else []
        if provider == "nvidia":
            # Consulta modelos ativos para evitar 410 de modelos EOL
            live_models = set()
            try:
                r_models = requests.get(
                    "https://integrate.api.nvidia.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                    timeout=5,
                )
                if r_models.ok:
                    data = r_models.json().get("data") or []
                    live_models = {m.get("id") for m in data if m.get("id")}
            except Exception:
                pass

            preferred = [
                m for m in (
                    model,
                    "meta/llama-3.3-70b-instruct",
                    "deepseek-ai/deepseek-r1",
                    "qwen/qwen2.5-72b-instruct",
                    "mistralai/mistral-large-2411",
                ) if m
            ]
            if live_models:
                models_to_try = [m for m in preferred if m in live_models] or [m for m in live_models if "instruct" in m or "chat" in m][:3] or list(live_models)[:2]
            else:
                models_to_try = preferred

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; BannerGenerator/1.0)",
        }

        last_exc: Exception | None = None
        for idx, m_name in enumerate(models_to_try):
            req_timeout = 35 if idx == 0 else 20
            # Alguns modelos/gateways da NVIDIA NIM rejeitam mensagens com role='system' ou exigem payload padrão
            message_variants = [
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                [{"role": "user", "content": f"{system}\n\n{user}"}],
            ]
            for msgs in message_variants:
                try:
                    r = requests.post(
                        cfg["url"],
                        headers=headers,
                        json={
                            "model": m_name,
                            "temperature": 0.2,
                            "max_tokens": 4096,
                            "stream": False,
                            "messages": msgs,
                        },
                        timeout=req_timeout,
                    )
                    r.raise_for_status()
                    res_data = r.json()
                    choices = res_data.get("choices") or []
                    if not choices:
                        continue
                    first_choice = choices[0]
                    msg = first_choice.get("message") or {}
                    content = msg.get("content")
                    if not content and msg.get("reasoning_content"):
                        content = msg.get("reasoning_content")
                    if not content and first_choice.get("text"):
                        content = first_choice.get("text")
                    if content and isinstance(content, str) and content.strip():
                        return content.strip()
                    continue
                except requests.HTTPError as exc:
                    last_exc = exc
                    if exc.response.status_code in (400, 404, 410, 422, 500, 502, 503):
                        continue
                    raise
                except requests.RequestException as exc:
                    last_exc = exc
                    continue
        if last_exc:
            raise last_exc
        raise LLMError("Nenhum modelo disponível para o provedor ou resposta vazia.")
    except requests.HTTPError as exc:  # nunca expõe cabeçalhos/chave
        detail = ""
        try:
            err_json = exc.response.json()
            if isinstance(err_json, dict):
                detail = err_json.get("detail") or err_json.get("message") or (err_json.get("error") if isinstance(err_json.get("error"), str) else (err_json.get("error") or {}).get("message"))
        except Exception:
            detail = (exc.response.text or "")[:150]
        detail_str = f" ({detail})" if detail else ""
        raise LLMError(f"Provedor retornou HTTP {exc.response.status_code}{detail_str}.") from None
    except (requests.RequestException, KeyError, IndexError, ValueError):
        raise LLMError("Falha ao consultar o provedor de IA.") from None


def parse_json_object(raw: Any) -> Dict[str, Any]:
    if not raw or not isinstance(raw, str):
        raise LLMError("Resposta da IA está vazia ou nula.")
    clean_raw = raw.strip()
    clean_raw = re.sub(r"^```(?:json)?|```$", "", clean_raw, flags=re.M).strip()
    start, end = clean_raw.find("{"), clean_raw.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("Resposta da IA não contém JSON válido.")
    snippet = clean_raw[start : end + 1]
    try:
        obj = json.loads(snippet)
    except json.JSONDecodeError:
        # Repara escapes de contrabarra do LaTeX em strings JSON (ex: \begin, \hline, \alpha)
        repaired = re.sub(r'\\(?![/"\\bfnrtu]|u[0-9a-fA-F]{4})', r'\\\\', snippet)
        try:
            obj = json.loads(repaired)
        except json.JSONDecodeError:
            raise LLMError("Resposta da IA não contém JSON válido.") from None
    if not isinstance(obj, dict):
        raise LLMError("Resposta da IA inválida.")
    return obj


def ai_extract(text: str, language: str, provider: str, api_key: str, model: str | None) -> Dict[str, Any]:
    system = SYSTEM_PROMPT.replace("{language}", _LANG_NAME.get(language, "Brazilian Portuguese"))
    raw_response = chat(provider, api_key, model, system, f"<paper>\n{text[:35000]}\n</paper>")
    obj = parse_json_object(raw_response)
    secs = obj.get("sections") if isinstance(obj.get("sections"), dict) else {}
    return {
        "title": str(obj.get("title") or "").strip(),
        "authors": str(obj.get("authors") or "").strip(),
        "affiliations": str(obj.get("affiliations") or "").strip(),
        "email": str(obj.get("email") or "").strip(),
        "sections": [{"id": sid, "content": str(secs.get(sid) or "").strip()} for sid in DEFAULT_SECTION_IDS],
    }

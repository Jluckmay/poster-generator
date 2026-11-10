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

3. MANDATORY VISUAL ELEMENTS IN METHODS & RESULTS (TABLES & PIPELINE DIAGRAMS):
   - In "methods": YOU MUST include a clean methodology pipeline / architecture flowchart on its own paragraph (separated by a blank line) using bracketed stages connected by `->`, with 3 to 5 concise stages (3 to 6 words per stage), based on the paper's actual methodology:
     [1. Entrada: CICIoT2023 & Edge-IIoTset] -> [2. Treino Multiseed (LR, RF, LSTM, Transformer)] -> [3. Respostas Binárias (6.56M itens)] -> [4. Calibração IRT (Rasch & 2PL)] -> [5. Análise de Validade & Estabilidade]
   - In "results": If the paper contains ANY quantitative data, benchmarks, metrics, accuracy/F1 comparisons, or model calibrations, YOU MUST synthesize them into a clean Markdown table on its own paragraph (separated by a blank line) with 3 to 4 concise columns and 4 to 6 key rows:
     | Escala / Dataset | Modelo | Macro F1 | Capacidade 2PL |
     | :--- | :--- | :---: | :---: |
     | CIC Features | Random Forest | **0.699** | **+1.039** |
     | CIC Features | Transformer | 0.625 | +0.157 |
     | Edge Features | Random Forest | **0.489** | **+0.626** |
     | Edge Features | Transformer | 0.477 | +0.265 |
     DO NOT bury quantitative results inside a wall of text. Always separate the table or pipeline from bullet points with a blank line (`\n\n`)!

4. NATURAL INLINE CITATIONS IN TEXT (NO STANDALONE "KEY REFERENCES" BULLETS):
   - Weave bracketed citation numbers `[1]`, `[2]`, `[3]`, `[4]` NATURALLY inside the sentences of "introduction", "methods", and "results" right where the corresponding concepts, datasets, or prior works are mentioned!
   - Example: "...benchmarks de detecção de intrusão IoT como CICIoT2023 [3] e Edge-IIoTset [4] classificam modelos sem estabelecer validade de construto [2], motivando calibrações via Teoria de Resposta ao Item (IRT) no nível de instância [1]."
   - NEVER create a standalone bullet point such as `- **Referências-chave:** [1], [2], [3]` or `- **Key references:** [1, 2, 3]`. Every reference in "references" MUST be cited naturally in context within the text!

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
            for fb in (
                "nvidia/nemotron-3.5-super-vl-120b-a12b",
                "nvidia/nemotron-3.5-lightning-30b-a3b",
                "mistralai/mistral-large-2411",
                "mistralai/mistral-large-4",
            ):
                if fb not in models_to_try:
                    models_to_try.append(fb)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; PosterGenerator/1.0)",
        }

        last_exc: Exception | None = None
        for idx, m_name in enumerate(models_to_try):
            req_timeout = 75 if idx == 0 else 45
            is_nemotron = "nemotron" in m_name.lower()
            # Modelos Nemotron 3.5 possuem raciocínio (thinking) ativo por padrão, podendo consumir
            # todos os tokens em reasoning_content e deixar content nulo se max_tokens for baixo.
            payload_variants = [
                {
                    "model": m_name,
                    "temperature": 0.2,
                    "max_tokens": 8192 if is_nemotron else 4096,
                    "stream": False,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    **({"chat_template_kwargs": {"enable_thinking": False}} if is_nemotron else {}),
                },
                {
                    "model": m_name,
                    "temperature": 0.2,
                    "max_tokens": 16384 if is_nemotron else 4096,
                    "stream": False,
                    "messages": [{"role": "user", "content": f"{system}\n\n{user}"}],
                },
            ]
            for payload in payload_variants:
                try:
                    r = requests.post(
                        cfg["url"],
                        headers=headers,
                        json=payload,
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
                    if not content and first_choice.get("text"):
                        content = first_choice.get("text")
                    # Só aproveita reasoning_content se content vier vazio E reasoning_content contiver o JSON
                    if (not content or not str(content).strip()) and msg.get("reasoning_content"):
                        rc = str(msg.get("reasoning_content"))
                        if "{" in rc and "}" in rc and '"sections"' in rc:
                            content = rc
                    if content and isinstance(content, str) and content.strip():
                        if "{" in content and "}" in content:
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


_LATEX_CMD_ESCAPE_RE = re.compile(
    r'(?<!\\)\\(begin|textbf|textit|textrm|texttt|textsc|text|beta|bottomrule|bullet|bar|bf|'
    r'frac|footnotesize|forall|right|rightarrow|rho|renewcommand|node|noindent|neq|nabla|natural|'
    r'tikzpicture|tabularx?|toprule|times|theta|tau)(?![a-zA-Z])'
)


def _escape_control_chars_in_json_strings(s: str) -> str:
    out: list[str] = []
    in_str = False
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == '"':
            bs = 0
            k = i - 1
            while k >= 0 and s[k] == "\\":
                bs += 1
                k -= 1
            if bs % 2 == 0:
                in_str = not in_str
            out.append(ch)
            i += 1
            continue
        if in_str:
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            elif ord(ch) < 0x20:
                out.append(" ")
            else:
                out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _repair_json_candidate(snippet: str) -> str:
    s = _LATEX_CMD_ESCAPE_RE.sub(r"\\\\\1", snippet)
    s = re.sub(r'(?<!\\)\\(?![/"\\bfnrtu]|u[0-9a-fA-F]{4})', r"\\\\", s)
    s = _escape_control_chars_in_json_strings(s)
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


def parse_json_object(raw: Any) -> Dict[str, Any]:
    if not raw or not isinstance(raw, str):
        raise LLMError("Resposta da IA está vazia ou nula.")
    clean_raw = raw.strip()
    # Remove blocos de raciocínio <think>...</think>
    clean_raw = re.sub(r"<think>[\s\S]*?</think>", "", clean_raw, flags=re.I).strip()
    if "</think>" in clean_raw.lower():
        idx_think = clean_raw.lower().rfind("</think>")
        clean_raw = clean_raw[idx_think + 8 :].strip()
    clean_raw = re.sub(r"^```(?:json)?|```$", "", clean_raw, flags=re.M).strip()

    # Coleta possíveis índices de início do objeto JSON principal
    starts: list[int] = []
    for m in re.finditer(r'\{\s*"(?:title|sections|authors)"', clean_raw):
        starts.append(m.start())
    first_brace = clean_raw.find("{")
    if first_brace >= 0 and first_brace not in starts:
        starts.append(first_brace)

    end = clean_raw.rfind("}")
    if not starts or end <= min(starts):
        raise LLMError("Resposta da IA não contém JSON válido.")

    decoder = json.JSONDecoder()
    for st in starts:
        if end <= st:
            continue
        snippet = clean_raw[st : end + 1]
        for candidate in (snippet, _repair_json_candidate(snippet)):
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                try:
                    obj, _ = decoder.raw_decode(candidate)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    continue

    raise LLMError("Resposta da IA não contém JSON válido.")


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

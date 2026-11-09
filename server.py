"""Servidor Flask: API de extração e geração de pôsteres + interface web."""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Tuple

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from src import config
from src.extractors import ALLOWED_DOC_EXT, extract_text, heuristic_parse
from src.i18n import DEFAULT_SECTION_IDS, LABELS
from src.images import save_image
from src.latex import build_tex, compile_tex, fit_compile, make_zip, new_build_dir
from src.llm import LLMError, ai_extract, resolve_key
from src.poster import normalize_poster
from src.templates import public_templates

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    ROOT = Path(sys._MEIPASS).resolve()
else:
    ROOT = Path(__file__).parent.resolve()
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_BYTES
_BUILD_SLOTS = threading.BoundedSemaphore(int(os.environ.get("MAX_CONCURRENT_BUILDS", "2")))


PROD_ALLOWED_ORIGIN = "https://jluckmay.github.io"


def _err(msg: str, code: int = 400) -> Tuple[Response, int]:
    return jsonify({"error": msg}), code


def _get_allowed_origin() -> str | None:
    origin = (request.headers.get("Origin") or "").strip()
    if not origin:
        return None
    # Permite estritamente jluckmay.github.io em produção
    if origin == PROD_ALLOWED_ORIGIN:
        return PROD_ALLOWED_ORIGIN
    # Permite origens locais de desenvolvimento
    if (
        origin.startswith("http://localhost:")
        or origin.startswith("http://127.0.0.1:")
        or origin in ("http://localhost", "http://127.0.0.1")
    ):
        return origin
    return None


@app.route("/api/<path:path>", methods=["OPTIONS"])
def api_options(path: str) -> Response:
    origin = request.headers.get("Origin")
    allowed = _get_allowed_origin()
    if origin and not allowed:
        return Response("Origem não autorizada", status=403)
    resp = Response(status=204)
    if allowed:
        resp.headers["Access-Control-Allow-Origin"] = allowed
        resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp


@app.before_request
def _validate_origin() -> Response | None:
    if request.path.startswith("/api/"):
        origin = request.headers.get("Origin")
        if origin and not _get_allowed_origin():
            return jsonify({"error": "Origem não permitida para conexões com este backend."}), 403
    return None


@app.after_request
def _headers(resp: Response) -> Response:
    allowed = _get_allowed_origin()
    if allowed:
        resp.headers["Access-Control-Allow-Origin"] = allowed
        resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Expose-Headers"] = "X-Poster-Overflow, Content-Disposition"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Permissions-Policy"] = "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self' data: blob:; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
        "worker-src 'self' blob: data: https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://use.typekit.net https://p.typekit.net; "
        "font-src 'self' https://fonts.gstatic.com https://use.typekit.net https://p.typekit.net data:; "
        "img-src 'self' blob: data:; "
        "frame-src 'self' blob: data: chrome-extension:; "
        "object-src 'self' blob: data:; "
        "connect-src 'self' http://127.0.0.1:5000 http://localhost:5000 https://poster-generator-nkqh.onrender.com https://cdnjs.cloudflare.com; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'self' https://jluckmay.github.io"
    )
    return resp


@app.get("/")
def index() -> Response:
    return send_from_directory(ROOT, "index.html")


@app.get("/assets/<path:name>")
def assets(name: str) -> Response:
    return send_from_directory(ROOT / "assets", name)


@app.get("/healthz")
def healthz() -> Response:
    return jsonify({"status": "ok", "pdflatex": bool(shutil.which("pdflatex"))})


@app.get("/api/config")
def api_config() -> Response:
    return jsonify(
        {
            "languages": list(config.LANGUAGES),
            "papers": list(config.POSTER_SIZES),
            "sizes": {k: v["cm"] for k, v in config.POSTER_SIZES.items()},
            "templates": public_templates(),
            "default_provider": config.DEFAULT_PROVIDER,
            "providers": config.public_provider_info(),
            "sections": DEFAULT_SECTION_IDS,
            "labels": {lang: {k: v for k, v in d.items() if k != "babel"} for lang, d in LABELS.items()},
            "doc_extensions": list(ALLOWED_DOC_EXT),
        }
    )


@app.post("/api/extract")
def api_extract() -> Tuple[Response, int] | Response:
    """Recebe um trabalho (PDF/DOCX/TXT/MD/TEX) e devolve os campos do pôster."""
    try:
        f = request.files.get("file")
        if not f or not f.filename:
            return _err("Nenhum arquivo enviado.")
        language = request.form.get("language", config.DEFAULT_LANGUAGE)
        mode = request.form.get("mode", "ai")
        try:
            text = extract_text(f.filename, f.read())
        except ValueError as exc:
            return _err(str(exc))
        except Exception:
            return _err("Não foi possível ler o arquivo.")
        if len(text) < 80:
            return _err("O arquivo não contém texto suficiente.")

        warning = ""
        result: Dict[str, Any] | None = None
        if mode == "ai":
            provider = request.form.get("provider", config.DEFAULT_PROVIDER)
            user_key = (request.form.get("api_key") or "").strip()
            server_key = config.server_key_for(provider)
            if not user_key and not server_key:
                warning = "Chave de API necessária para extração com IA."
            else:
                try:
                    key = user_key or server_key
                    result = ai_extract(text, language, provider, key, request.form.get("model") or None)
                except Exception as exc:
                    warning = str(exc)
                    if not user_key and ("410" in warning or "401" in warning or "403" in warning):
                        config.mark_server_key_invalid(provider)
                    if not user_key:
                        for fallback_p in ("google", "openai", "deepseek"):
                            if fallback_p != provider and config.server_key_for(fallback_p):
                                try:
                                    f_key = config.server_key_for(fallback_p)
                                    result = ai_extract(text, language, fallback_p, f_key, None)
                                    warning = ""
                                    break
                                except Exception:
                                    continue
        if result is None:
            result = heuristic_parse(text)
            if mode == "ai":
                if "410" in warning:
                    warning = "A chave deste provedor expirou (HTTP 410). Insira sua chave de API (ex: Gemini gratuita em Google AI Studio) para IA."
                elif "Chave de API necessária" in warning:
                    warning = "Chave de API não informada. Para síntese com IA, insira uma chave de API (ex: Gemini gratuita em Google AI Studio)."
                else:
                    warning = (warning + " — ").lstrip(" —") + "usando extração básica (sem IA)."
        return jsonify({"poster": result, "mode": "ai" if not warning and mode == "ai" else "basic", "warning": warning})
    except HTTPException:
        raise
    except Exception as exc:
        return jsonify({"error": f"Erro interno ao processar o arquivo: {str(exc)}"}), 500


@app.post("/api/generate")
def api_generate() -> Tuple[Response, int] | Response:
    """Gera o pôster. Campo `data` (JSON) + arquivos de imagem referenciados por nome de campo."""
    fmt = request.args.get("format", "pdf")
    if fmt not in ("pdf", "zip", "tex"):
        return _err("Formato inválido.")

    custom_tex_file = request.files.get("custom_tex")
    if custom_tex_file and custom_tex_file.filename:
        tex = custom_tex_file.read().decode("utf-8", errors="replace")
        if not tex.strip():
            return _err("Arquivo .tex vazio.")
        if fmt == "tex":
            return Response(tex, mimetype="text/plain", headers={"Content-Disposition": 'attachment; filename="poster.tex"'})
        build = new_build_dir()
        try:
            if not _BUILD_SLOTS.acquire(timeout=20):
                return _err("Servidor ocupado, tente novamente em instantes.", 503)
            try:
                pdf, _ = compile_tex(tex, build)
            except RuntimeError as exc:
                return _err(str(exc), 500)
            except Exception:
                return _err("Tempo esgotado ou erro ao compilar o arquivo LaTeX customizado.", 500)
            finally:
                _BUILD_SLOTS.release()
            if fmt == "zip":
                return Response(make_zip(tex, build), mimetype="application/zip", headers={"Content-Disposition": 'attachment; filename="poster-latex.zip"'})
            return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": 'inline; filename="poster.pdf"'})
        finally:
            shutil.rmtree(build, ignore_errors=True)

    try:
        data = json.loads(request.form.get("data", ""))
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        return _err("Dados do pôster inválidos.")

    poster = normalize_poster(data)
    if not poster["title"]:
        return _err("Informe o título do pôster.")
    if not poster["sections"]:
        return _err("Adicione conteúdo em pelo menos uma seção.")

    wanted = [i["path"] for s in poster["sections"] for i in s["images"]] + poster["logos_header"] + poster["logos_footer"]
    if len(wanted) > config.MAX_IMAGES_TOTAL:
        return _err("Imagens demais.")

    build = new_build_dir()
    try:
        images: Dict[str, str] = {}
        for n, field in enumerate(dict.fromkeys(wanted)):
            up = request.files.get(field)
            if not up:
                continue
            try:
                images[field] = save_image(up.read(), build, f"img{n}")
            except ValueError as exc:
                return _err(f"{up.filename or field}: {exc}")
        tex = build_tex(poster, images)
        if fmt == "tex":
            return Response(tex, mimetype="text/plain", headers={"Content-Disposition": 'attachment; filename="poster.tex"'})
        if not _BUILD_SLOTS.acquire(timeout=20):
            return _err("Servidor ocupado, tente novamente em instantes.", 503)
        try:
            pdf, tex, overflow = fit_compile(poster, images, build)
        except RuntimeError as exc:
            return _err(str(exc), 500)
        except Exception:
            return _err("Tempo esgotado ou erro ao compilar o pôster.", 500)
        finally:
            _BUILD_SLOTS.release()
        extra = {"X-Poster-Overflow": "1"} if overflow else {}
        if fmt == "zip":
            return Response(make_zip(tex, build), mimetype="application/zip", headers={"Content-Disposition": 'attachment; filename="poster-latex.zip"', **extra})
        return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": 'inline; filename="poster.pdf"', **extra})
    finally:
        shutil.rmtree(build, ignore_errors=True)


@app.errorhandler(413)
def too_large(_: Exception) -> Tuple[Response, int]:
    return _err("Upload maior que o limite permitido.", 413)


@app.errorhandler(500)
def handle_500(_: Exception) -> Tuple[Response, int]:
    return _err("Erro interno no servidor. Tente novamente em instantes.", 500)


def main() -> None:
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))


if __name__ == "__main__":
    main()

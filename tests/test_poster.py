"""Testes do gerador de pôsteres."""

import io
import json
import shutil

import pytest
from PIL import Image

from server import app
from src.extractors import extract_text, heuristic_parse
from src.latex import build_tex, escape_latex, split_columns, text_to_latex
from src.poster import normalize_poster
from src.templates import TEMPLATES

PAPER = """Efeito da luz no crescimento de plantas
Maria Silva, João Souza
Universidade Federal de Teste
maria@exemplo.edu

Resumo
Este estudo avaliou o crescimento de plantas sob diferentes espectros de luz durante 30 dias, com 5% de variação.

1. Introdução
A luz é essencial para a fotossíntese.
- Item um
- Item dois

Metodologia
Foram cultivadas 60 plantas.

Resultados
A luz azul aumentou a biomassa em 20%.

Conclusão
A luz importa.

Referências
[1] Autor A. Título. 2020.
[2] Autor B. Outro. 2021.
"""


def test_escape_blocks_injection():
    out = escape_latex(r"\input{/etc/passwd} 50% & #1 _x_ {y}")
    assert "\\input" not in out.replace("\\textbackslash{}input", "")
    assert r"\%" in out and r"\&" in out


def test_math_whitelist():
    assert "$\\alpha^2$" in text_to_latex("Valor $\\alpha^2$ ok")
    bad = text_to_latex(r"Mau $\input{x}$")
    assert "$\\input" not in bad


def test_bold_italic_and_lists():
    tex = text_to_latex("**forte** e *itálico*\n\n- a\n- b\n\n1. um\n2. dois")
    assert "\\textbf{forte}" in tex and "\\textit{itálico}" in tex
    assert "\\begin{itemize}" in tex and "\\begin{enumerate}" in tex


def test_superscript_citations():
    tex = text_to_latex("Segundo modelo [1] e estudos anteriores [2, 3].")
    assert r"\textsuperscript{[1]}" in tex
    assert r"\textsuperscript{[2, 3]}" in tex




def test_markdown_and_latex_tables_and_diagrams():
    md_tbl = "| Algoritmo | Acuracia |\n|---|---|\n| Random Forest | 88.5% |\n| Proposto | 96.2% |"
    tex_tbl = text_to_latex(md_tbl)
    assert r"\begin{tabular}" in tex_tbl
    assert r"\textbf{Algoritmo}" in tex_tbl
    assert "88.5" in tex_tbl
    assert r"\end{tabular}" in tex_tbl

    raw_tex = "\\begin{tabular}{cc}\n\\hline\nA & B \\\\\n\\hline\n\\end{tabular}"
    tex_out = text_to_latex(raw_tex)
    assert r"\begin{tabular}{cc}" in tex_out
    assert r"\begin{center}" in tex_out

    tikz_raw = "\\begin{tikzpicture}\n\\node (a) {Passo 1};\n\\end{tikzpicture}"
    tikz_out = text_to_latex(tikz_raw)
    assert r"\begin{tikzpicture}" in tikz_out
    assert r"\node (a)" in tikz_out

    injected = "\\begin{tabular}{c}\n\\input{/etc/passwd}\n\\end{tabular}"
    safe_out = text_to_latex(injected)
    assert r"\input" not in safe_out.replace(r"\textbackslash{}input", "")


def test_json_object_repairs_latex_escapes():
    from src.llm import parse_json_object
    raw_json = '{"title": "Teste", "sections": {"results": "\\begin{tabular}\\hline\\alpha & \\textbf{1}\\end{tabular}"}}'
    parsed = parse_json_object(raw_json)
    assert parsed["title"] == "Teste"
    assert r"\hline" in parsed["sections"]["results"]
def test_heuristic_parse():
    r = heuristic_parse(PAPER)
    ids = {s["id"] for s in r["sections"]}
    assert {"introduction", "methods", "results", "conclusions", "references"} <= ids
    assert "abstract" not in ids
    assert r["title"].startswith("Efeito da luz")
    assert r["email"] == "maria@exemplo.edu"


def test_extract_txt_and_unsupported():
    assert "Resumo" in extract_text("a.txt", PAPER.encode())
    with pytest.raises(ValueError):
        extract_text("a.exe", b"x")


def test_split_columns_balanced():
    secs = [{"content": "x" * 500, "images": []} for _ in range(6)]
    cols = split_columns(secs, 3)
    assert len(cols) == 3 and all(cols)


def test_normalize_defaults():
    p = normalize_poster({"template": "nope", "paper": "z", "columns": 99, "sections": [{"id": "abstract", "content": "x"}]})
    assert p["template"] == "classic" and p["paper"] == "60x90" and p["columns"] == 4
    assert p["sections"][0]["title"] == "Resumo"


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_config_endpoint(client):
    j = client.get("/api/config").get_json()
    assert set(j["templates"]) == set(TEMPLATES) and "pt-BR" in j["languages"]


def test_extract_endpoint_basic(client):
    r = client.post("/api/extract", data={"mode": "basic", "file": (io.BytesIO(PAPER.encode()), "p.txt")})
    assert r.status_code == 200 and r.get_json()["poster"]["title"]


def test_extract_ai_without_key_falls_back(client, monkeypatch):
    for k in ("GEMINI_API_KEY",):
        monkeypatch.delenv(k, raising=False)
    j = client.post("/api/extract", data={"mode": "ai", "file": (io.BytesIO(PAPER.encode()), "p.txt")}).get_json()
    assert j["mode"] == "basic" and j["warning"]


def test_generate_validation(client):
    assert client.post("/api/generate", data={"data": "{}"}).status_code == 400
    assert client.post("/api/generate", data={"data": "nope"}).status_code == 400


def test_bad_image_rejected(client):
    data = {"title": "T", "sections": [{"id": "abstract", "content": "x", "images": [{"path": "i0"}]}]}
    r = client.post("/api/generate?format=tex", data={"data": json.dumps(data), "i0": (io.BytesIO(b"not an image"), "x.png")})
    assert r.status_code == 400


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (200, 120), "red").save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="pdflatex ausente")
@pytest.mark.parametrize("tpl", list(TEMPLATES))
@pytest.mark.parametrize("lang", ["pt-BR", "en-US"])
def test_generate_pdf_all_templates(client, tpl, lang):
    data = {
        "title": "Título com & caracteres % especiais",
        "authors": "Ana, Bruno",
        "affiliations": "Univ. X",
        "email": "a@b.com",
        "url": "https://exemplo.com/p",
        "language": lang,
        "template": tpl,
        "paper": "a1",
        "orientation": "landscape",
        "columns": 3,
        "sections": [
            {"id": "abstract", "content": "Resumo com $x^2$ e **negrito**."},
            {"id": "results", "content": "- a\n- b", "images": [{"path": "i0", "caption": "Gráfico 50%"}, {"path": "i1"}]},
            {"id": "references", "content": "[1] Ref A\n[2] Ref B"},
            {"id": "custom1", "title": "Minha seção", "content": "texto"},
        ],
        "logos": ["l0"],
    }
    files = {"i0": (io.BytesIO(_png()), "a.png"), "i1": (io.BytesIO(_png()), "b.png"), "l0": (io.BytesIO(_png()), "l.png")}
    r = client.post("/api/generate", data={"data": json.dumps(data), **files})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.data.startswith(b"%PDF")


def test_build_tex_has_babel_and_columns():
    p = normalize_poster({"title": "T", "language": "en-US", "columns": 2, "sections": [{"id": "abstract", "content": "x"}, {"id": "results", "content": "y"}]})
    tex = build_tex(p, {})
    assert "[english]{babel}" in tex and tex.count("\\column{") == 2


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="pdflatex ausente")
def test_fit_reduces_font_and_flags_overflow(client):
    big = {"title": "T", "paper": "a2", "columns": 1, "sections": [{"id": f"c{i}", "title": "S", "content": "palavra " * 2500} for i in range(18)]}
    r = client.post("/api/generate", data={"data": json.dumps(big)})
    assert r.status_code == 200 and r.headers.get("X-Poster-Overflow") == "1"
    mid = {"title": "T", "paper": "a2", "columns": 2, "sections": [{"id": "abstract", "content": ("palavra " * 120 + "\n\n") * 6}]}
    r = client.post("/api/generate", data={"data": json.dumps(mid)})
    assert r.status_code == 200 and not r.headers.get("X-Poster-Overflow")


def test_logo_limits_per_template():
    p = normalize_poster({"template": "dcc", "logos_header": list("abc"), "logos_footer": list("abcdefg"), "sections": []})
    assert len(p["logos_header"]) == 2 and len(p["logos_footer"]) == 5 and p["paper"] == "60x90"
    p_custom = normalize_poster({"template": "dcc", "paper": "60x90", "sections": []})
    assert p_custom["paper"] == "60x90"
    c = normalize_poster({"template": "classic", "logos_header": list("abc"), "logos_footer": ["x"], "paper": "a3", "sections": []})
    assert len(c["logos_header"]) == 2 and c["logos_footer"] == [] and c["paper"] == "60x90"


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="pdflatex ausente")
@pytest.mark.parametrize("paper", ["60x90", "a2"])
def test_dcc_template_with_header_and_footer_logos(client, paper):
    data = {
        "title": "Otimização Avançada", "authors": "A, B", "affiliations": "DCC - UFMG", "email": "a@b.com",
        "url": "https://exemplo.com/p", "template": "dcc", "paper": paper, "columns": 2,
        "logos_header": ["h0", "h1", "h2"], "logos_footer": [f"f{i}" for i in range(6)],
        "sections": [
            {"id": "introduction", "content": "Texto $x^2$ com **negrito**." * 5},
            {"id": "results", "content": "- a\n- b", "images": [{"path": "g0", "caption": "Gráfico"}]},
            {"id": "references", "content": "[1] Ref A\n[2] Ref B"},
        ],
    }
    names = ["h0", "h1", "h2", "g0"] + [f"f{i}" for i in range(6)]
    files = {n: (io.BytesIO(_png()), n + ".png") for n in names}
    r = client.post("/api/generate", data={"data": json.dumps(data), **files})
    assert r.status_code == 200 and r.data.startswith(b"%PDF") and not r.headers.get("X-Poster-Overflow")
    z = client.post("/api/generate?format=zip", data={"data": json.dumps(data), **{n: (io.BytesIO(_png()), n + ".png") for n in names}})
    import zipfile
    with zipfile.ZipFile(io.BytesIO(z.data)) as zf:
        assert "poster.tex" in zf.namelist() and sum(n.endswith((".png", ".jpg")) for n in zf.namelist()) == 8


SIZES_CM = {"60x90": (60, 90), "90x120": (90, 120), "a0": (84.1, 118.9), "a1": (59.4, 84.1), "a2": (42, 59.4)}


def test_five_sizes_exposed(client):
    j = client.get("/api/config").get_json()
    assert j["papers"] == list(SIZES_CM) and len(j["papers"]) == 5
    for t in j["templates"].values():
        assert t["papers"] == list(SIZES_CM)


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="pdflatex ausente")
@pytest.mark.parametrize("tpl", ["classic", "dcc"])
@pytest.mark.parametrize("paper", list(SIZES_CM))
@pytest.mark.parametrize("orient", ["portrait", "landscape"])
def test_all_sizes_have_right_page_dimensions(client, tpl, paper, orient):
    from pypdf import PdfReader
    d = {"title": "T", "template": tpl, "paper": paper, "orientation": orient, "columns": 2,
         "sections": [{"id": "abstract", "content": "texto " * 60}]}
    r = client.post("/api/generate", data={"data": json.dumps(d)})
    assert r.status_code == 200 and not r.headers.get("X-Poster-Overflow")
    page = PdfReader(io.BytesIO(r.data)).pages[0]
    w_cm, h_cm = float(page.mediabox.width) / 72 * 2.54, float(page.mediabox.height) / 72 * 2.54
    ew, eh = SIZES_CM[paper]
    if orient == "landscape":
        ew, eh = eh, ew
    assert abs(w_cm - ew) < 0.6 and abs(h_cm - eh) < 0.6


# ---------------- segurança ----------------
def test_math_rejects_caret_notation_and_dangerous_cmds():
    assert "textasciicircum" in text_to_latex(r"$^^5cinput{x}$") and "$^^" not in text_to_latex(r"$^^5cinput{x}$")
    assert "$\\write" not in text_to_latex(r"$\write18{id}$")
    assert "\\text{" not in text_to_latex(r"$\text{\input{x}}$")


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="pdflatex ausente")
def test_latex_injection_does_not_read_files(client, tmp_path, monkeypatch):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRETVALUE")
    payload = rf"\input{{{secret.as_posix()}}} \immediate\write18{{echo pwn}} $^^5cinput{{{secret.as_posix()}}}$ ^^5cinput"
    d = {"title": payload, "authors": payload, "affiliations": payload, "email": payload, "url": payload,
         "sections": [{"id": "abstract", "title": payload, "content": payload,
                       "images": []}, {"id": "references", "content": payload}]}
    for tpl in ("classic", "dcc"):
        r = client.post("/api/generate", data={"data": json.dumps({**d, "template": tpl})})
        assert r.status_code == 200
        from pypdf import PdfReader
        text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.data)).pages)
        assert "TOPSECRETVALUE" not in text  # o payload aparece apenas como texto literal


def test_security_headers(client):
    r = client.get("/")
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert "frame-ancestors 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN" and r.headers["X-Content-Type-Options"] == "nosniff"


def test_oversized_upload_rejected(client):
    old = app.config["MAX_CONTENT_LENGTH"]
    app.config["MAX_CONTENT_LENGTH"] = 1000
    try:
        r = client.post("/api/extract", data={"file": (io.BytesIO(b"x" * 5000), "a.txt")})
        assert r.status_code == 413
    finally:
        app.config["MAX_CONTENT_LENGTH"] = old


def test_decompression_bomb_and_fake_image_rejected(client):
    buf = io.BytesIO()
    Image.new("1", (9000, 9000)).save(buf, "PNG")  # 81M pixels, ~pequeno em disco
    d = {"title": "T", "sections": [{"id": "abstract", "content": "x", "images": [{"path": "i0"}]}]}
    r = client.post("/api/generate?format=tex", data={"data": json.dumps(d), "i0": (io.BytesIO(buf.getvalue()), "b.png")})
    assert r.status_code == 400
    r = client.post("/api/generate?format=tex", data={"data": json.dumps(d), "i0": (io.BytesIO(b"<svg onload=alert(1)>"), "x.svg")})
    assert r.status_code == 400


def test_invalid_model_name_rejected():
    from src.llm import LLMError, chat
    for bad in ("../../v1/x", "a b", "x?key=1", "/abs"):
        with pytest.raises(LLMError):
            chat("google", "k", bad, "s", "u")


def test_docx_zip_bomb_and_garbage_handled(client):
    r = client.post("/api/extract", data={"mode": "basic", "file": (io.BytesIO(b"PK\x03\x04garbage"), "a.docx")})
    assert r.status_code == 400
    r = client.post("/api/extract", data={"mode": "basic", "file": (io.BytesIO(b"%PDF-1.4 broken"), "a.pdf")})
    assert r.status_code == 400


def test_custom_colors_normalized():
    from src.poster import normalize_poster
    p = normalize_poster({
        "title": "Title",
        "sections": [{"id": "sec1", "title": "S1", "content": "C1"}],
        "colors": {
            "accent": "#ff2a40",
            "title": "ffffff",
            "subtitle": "#e6edf8",
            "body": "1a1a1a",
            "bg": "#f0fdfa",
        }
    })
    assert p["colors"]["accent"] == "FF2A40"
    assert p["colors"]["title"] == "FFFFFF"
    assert p["colors"]["subtitle"] == "E6EDF8"
    assert p["colors"]["body"] == "1A1A1A"
    assert p["colors"]["bg"] == "F0FDFA"


def test_custom_tex_upload(client):
    tex_data = b"\\documentclass{article}\\begin{document}Custom Poster\\end{document}"
    r = client.post("/api/generate?format=tex", data={"custom_tex": (io.BytesIO(tex_data), "custom.tex")})
    assert r.status_code == 200
    assert "Custom Poster" in r.text

def test_all_templates_adapt_to_selected_paper():
    from src.templates import TEMPLATES
    from src.config import POSTER_SIZES
    for tid in TEMPLATES:
        for p in POSTER_SIZES:
            res = normalize_poster({"template": tid, "paper": p, "sections": []})
            assert res["paper"] == p, f"Template {tid} failed to adapt to paper {p}"


def test_cors_allowed_github_pages(client):
    r = client.get("/api/config", headers={"Origin": "https://jluckmay.github.io"})
    assert r.status_code == 200
    assert r.headers.get("Access-Control-Allow-Origin") == "https://jluckmay.github.io"


def test_cors_allowed_local(client):
    r = client.get("/api/config", headers={"Origin": "http://127.0.0.1:5000"})
    assert r.status_code == 200
    assert r.headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:5000"


def test_cors_unauthorized_origin_rejected(client):
    r = client.get("/api/config", headers={"Origin": "https://unauthorized-domain.com"})
    assert r.status_code == 403


def test_cors_options_preflight(client):
    r_ok = client.options("/api/generate", headers={"Origin": "https://jluckmay.github.io"})
    assert r_ok.status_code in (200, 204)
    assert r_ok.headers.get("Access-Control-Allow-Origin") == "https://jluckmay.github.io"

    r_bad = client.options("/api/generate", headers={"Origin": "https://attacker.com"})
    assert r_bad.status_code == 403


def test_clean_hyphens_and_formatting():
    from src.extractors import clean_hyphens, _format_references

    text = "We observe proper- ties and differ- ences with agree- ment. Fit- ted instances with benchmark- representation and reg- ularization."
    cleaned = clean_hyphens(text)
    assert "properties" in cleaned
    assert "differences" in cleaned
    assert "agreement" in cleaned
    assert "Fitted" in cleaned
    assert "regularization" in cleaned
    assert "benchmark-representation" in cleaned

    refs = "[1] First reference paper 2020. [2] Second reference paper 2021. [3] Third reference 2022."
    f_refs = _format_references(refs)
    lines = [ln for ln in f_refs.split("\n") if ln.strip()]
    assert len(lines) == 3
    assert lines[0].startswith("[1]")
    assert lines[1].startswith("[2]")
    assert lines[2].startswith("[3]")


def test_heuristic_parse_separates_author_from_title():
    from src.extractors import heuristic_parse

    paper_raw = """CONDITIONAL CAPABILITY AND MEASUREMENT VALIDITY IN IOT INTRUSION-DETECTION
BENCHMARKS JOÃO LUCAS MAYRINCK
UFMG
lucas.mayrinck@dcc.ufmg.br Brendo Gético Eugênio UFMG brendo.eugenio@dcc.ufmg.br
UFMG Luiz Filipe Menezes Vieira

Abstract
We investigate measurement proper- ties.

Introduction
An intrusion-detection benchmark with differ- ences.

References
[1] Author A. 2023. [2] Author B. 2024."""

    parsed = heuristic_parse(paper_raw)
    assert "JOÃO LUCAS MAYRINCK" not in parsed["title"]
    assert "BENCHMARKS" in parsed["title"]
    assert "JOÃO LUCAS MAYRINCK" in parsed["authors"]
    assert "Brendo Gético Eugênio" in parsed["authors"]
    assert "Luiz Filipe Menezes Vieira" in parsed["authors"]
    assert parsed["affiliations"] == "UFMG"
    assert parsed["email"] == "lucas.mayrinck@dcc.ufmg.br"

    ref_sec = next(s for s in parsed["sections"] if s["id"] == "references")
    assert "\n[2]" in ref_sec["content"]


def test_nvidia_default_model_is_nemotron():
    from src.config import PROVIDERS
    assert PROVIDERS["nvidia"]["default_model"] == "nvidia/nemotron-3.5-super-vl-120b-a12b"


def test_sbc_paper_format_parsing():
    from src.extractors import heuristic_parse

    sbc_text = """CONDITIONAL CAPABILITY AND MEASUREMENT VALIDITY IN IOT INTRUSION-DETECTION BENCHMARKS
João Lucas Mayrinck1, Brendo Gético Eugênio1, Luiz Filipe Menezes Vieira1, 1Department of Computer Science – Federal of Minas Gerais, Belo Horizonte – MG – Brazil, {lucas.mayrinck, brendo.eugenio, lfvieira}@dcc.ufmg.br, Abstract. Aggregate benchmark scores do not by themselves justify claims about general intrusion-detection capability. We investigate the conditional measurement properties of CICIoT2023.
University (UFMG)

1. Introdução
An intrusion-detection benchmark can rank classifiers without establishing what the resulting differences measure.

3. AI Measurement Science Framework
We operationalize IoT intrusion-detection capability under Rasch and 2PL models.

4. Results and Analysis
4.1. Conditional Performance and Capability Agreement (RQ1) Table 1 places conventional predictive performance.

5. Conclusions
The evaluated IoT benchmarks support reproducible conditional performance contrasts.

References
Al Nuaimi, T., Al Zaabi, S., Alyilieli, M., AlMaskari, M. (2023). A comparative evaluation. Degen, P.-B. (2025). Revisiting generalizability theory. Ferrag, M. A., Friha, O. (2022). Edge-IIoTset."""

    parsed = heuristic_parse(sbc_text)
    assert parsed["title"] == "CONDITIONAL CAPABILITY AND MEASUREMENT VALIDITY IN IOT INTRUSION-DETECTION BENCHMARKS"
    assert "João Lucas Mayrinck" in parsed["authors"]
    assert "Brendo Gético Eugênio" in parsed["authors"]
    assert "Luiz Filipe Menezes Vieira" in parsed["authors"]
    assert "Department of Computer Science" not in parsed["authors"]
    assert "Department of Computer Science" in parsed["affiliations"]
    assert "lucas.mayrinck@dcc.ufmg.br" in parsed["email"] or "lfvieira@dcc.ufmg.br" in parsed["email"]

    # Verify Abstract was parsed into introduction, not dumped into authors and not as standalone abstract
    intro_sec = next(s for s in parsed["sections"] if s["id"] == "introduction")
    assert "Aggregate benchmark scores" in intro_sec["content"]
    assert "Aggregate benchmark scores" not in parsed["authors"]
    assert not any(s["id"] == "abstract" for s in parsed["sections"])

    # Verify Methods and Results were both extracted
    methods_sec = next(s for s in parsed["sections"] if s["id"] == "methods")
    assert "operationalize IoT intrusion-detection" in methods_sec["content"]

    results_sec = next(s for s in parsed["sections"] if s["id"] == "results")
    assert "Conditional Performance" in results_sec["content"]

    # Verify References are formatted line-by-line
    ref_sec = next(s for s in parsed["sections"] if s["id"] == "references")
    ref_lines = [l for l in ref_sec["content"].split("\n") if l.strip()]
    assert len(ref_lines) == 3
    assert "Degen, P.-B." in ref_lines[1]


def test_parse_json_object_nemotron_thinking_and_latex():
    from src.llm import parse_json_object

    raw = (
        '<think>\nWe need to format {title} and use \\textbf{bold} in sections.\n</think>\n'
        'Here is the JSON result:\n'
        '```json\n'
        '{\n'
        '  "title": "IoT Intrusion Detection",\n'
        '  "authors": "Author A, Author B",\n'
        '  "affiliations": "UFMG",\n'
        '  "email": "a@ufmg.br",\n'
        '  "sections": {\n'
        '    "introduction": "- **Contexto:** Teste [1].",\n'
        '    "methods": "\\begin{tikzpicture}\n\\node {Entrada};\n\\end{tikzpicture}",\n'
        '    "results": "\\begin{tabular}{|l|c|}\\hline \\textbf{Modelo} & \\frac{1}{2} \\\\ \\hline\\end{tabular}",\n'
        '    "conclusions": "Conclusão final.",\n'
        '    "references": "[1] Ref A (2025)."\n'
        '  }\n'
        '}\n'
        '```\n'
        'Note: generated according to rules.'
    )
    obj = parse_json_object(raw)
    assert obj["title"] == "IoT Intrusion Detection"
    assert "\\begin{tikzpicture}" in obj["sections"]["methods"]
    assert "\\node" in obj["sections"]["methods"]
    assert "\\textbf{Modelo}" in obj["sections"]["results"]
    assert "\\frac{1}{2}" in obj["sections"]["results"]


def test_nvidia_chat_skips_non_json_reasoning_and_disables_thinking(monkeypatch):
    import requests
    from src.llm import chat

    calls = []

    class DummyResp:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
            self.text = json.dumps(data)

        def raise_for_status(self):
            if self.status_code >= 400:
                err = requests.HTTPError(f"HTTP {self.status_code}")
                err.response = self
                raise err

        def json(self):
            return self._data

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        if len(calls) == 1:
            return DummyResp(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "reasoning_content": "Thinking about how to summarize {paper}...",
                            }
                        }
                    ]
                },
            )
        return DummyResp(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"title": "OK", "sections": {"introduction": "A"}}',
                            "reasoning_content": None,
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(requests, "post", fake_post)
    out = chat("nvidia", "nvapi-test", "nvidia/nemotron-3.5-super-vl-120b-a12b", "sys", "usr")
    assert '"title": "OK"' in out
    assert len(calls) == 2
    assert calls[0].get("chat_template_kwargs") == {"enable_thinking": False}
    assert calls[0].get("max_tokens") == 8192

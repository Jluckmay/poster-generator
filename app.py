"""Gerador de Pôsteres Acadêmicos — Versão Local em Streamlit."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
from PIL import Image

from src import config
from src.extractors import extract_text, heuristic_parse
from src.i18n import DEFAULT_SECTION_IDS, LABELS, labels_for
from src.images import save_image
from src.latex import build_tex, compile_tex, fit_compile, make_zip
from src.llm import LLMError, ai_extract, resolve_key
from src.poster import normalize_poster
from src.templates import TEMPLATES, default_paper_for, papers_for

# ── Configuração da Página ──
st.set_page_config(
    page_title="poster-generator | Academic Poster & LaTeX Compiler",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS: Tema Terminal Escuro Idêntico ao Web App ──
st.markdown(
    """
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

  :root {
    --bg-main: #0a0d14;
    --bg-card: #0e1219;
    --bg-input: #141923;
    --line: #222938;
    --red: #e52e3d;
    --amber: #f59e0b;
    --fg: #e2e8f0;
    --muted: #94a3b8;
  }

  .stApp {
    background-color: var(--bg-main);
    color: var(--fg);
    font-family: 'Inter', sans-serif;
  }

  /* Cabeçalho Terminal */
  .terminal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 18px;
    background: var(--bg-card);
    border-bottom: 1px solid var(--line);
    border-top: 2px solid var(--red);
    margin-bottom: 20px;
    border-radius: 4px;
  }
  .brand-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 20px;
    font-weight: 800;
    color: #ffffff;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .brand-title span.prefix { color: var(--red); }
  .brand-sub {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--red);
    font-weight: 600;
    letter-spacing: 0.1em;
  }

  /* Cartões Estilo Terminal */
  .terminal-card {
    background: var(--bg-card);
    border: 1px solid var(--line);
    border-top: 2px solid var(--red);
    border-radius: 4px;
    padding: 16px 18px;
    margin-bottom: 16px;
  }
  .card-sec-badge {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: 700;
    color: var(--red);
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  /* Botões de Ação */
  div.stButton > button:first-child {
    background: var(--red);
    color: #ffffff;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
    border: none;
    border-radius: 4px;
    transition: all 0.2s;
  }
  div.stButton > button:first-child:hover {
    background: #c91f2d;
    box-shadow: 0 0 12px rgba(229, 46, 61, 0.4);
  }

  /* Templates Grid Preview */
  .tpl-badge {
    padding: 6px 10px;
    border-radius: 4px;
    border: 1px solid var(--line);
    background: var(--bg-input);
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    margin-bottom: 6px;
  }

  @media (max-width: 768px) {
    .terminal-header {
      flex-direction: column;
      align-items: flex-start;
      gap: 10px;
      padding: 10px 12px;
    }
    .brand-title {
      font-size: 16px;
    }
    .terminal-card {
      padding: 12px 14px;
    }
    div.stButton > button:first-child {
      min-height: 42px;
    }
  }
</style>
""",
    unsafe_allow_html=True,
)


# ── Dicionário de Textos da Interface (i18n) ──
UI_TEXT = {
    "pt-BR": {
        "title": "poster-generator",
        "tagline": "01 // PÔSTER ACADÊMICO & COMPILADOR LATEX",
        "s_mode": "01 // MODO DE PREENCHIMENTO",
        "mode_manual": "Preencher manualmente",
        "mode_upload": "Enviar trabalho",
        "drop_work": "Envie o arquivo do seu trabalho acadêmico (PDF, DOCX, TXT, MD, TEX)",
        "use_ai": "Usar IA para sintetizar o trabalho em formato de pôster",
        "provider": "Provedor de IA",
        "model": "Modelo (opcional)",
        "api_key": "Chave de API (opcional se configurada no ambiente)",
        "extract_btn": "Extrair Conteúdo do Trabalho",
        "extracting": "Analisando e estruturando documento...",
        "s_lang": "02 // IDIOMA DO PÔSTER",
        "lang_desc": "Define os cabeçalhos padrão das seções e o pacote babel correspondente no LaTeX.",
        "s_template": "03 // TEMPLATE E FORMATO",
        "paper": "Dimensões do Pôster",
        "orientation": "Orientação",
        "portrait": "Retrato (Vertical)",
        "landscape": "Paisagem (Horizontal)",
        "columns": "Colunas",
        "custom_colors": "Paleta de cores personalizada",
        "color_accent": "Destaque",
        "color_title": "Título",
        "color_subtitle": "Autores",
        "color_body": "Texto",
        "color_caption": "Legenda",
        "color_bg": "Fundo",
        "use_custom_tex": "Usar template LaTeX próprio (.tex)",
        "s_info": "04 // INFORMAÇÕES PRINCIPAIS",
        "work_title": "Título do Pôster",
        "authors": "Autores",
        "affiliations": "Afiliações Institucionais (uma por linha)",
        "email": "E-mail de Contato",
        "url": "Link / URL do Artigo ou Repositório (gera QR Code)",
        "logos_header": "Logotipos do Cabeçalho (PNG/JPG, máx 2)",
        "logos_footer": "Logotipos do Rodapé (PNG/JPG, máx 5)",
        "s_sections": "05 // SEÇÕES DO PÔSTER",
        "add_section": "Adicionar Nova Seção",
        "sec_title": "Título da Seção",
        "sec_content": "Conteúdo (suporta tópicos com '- ', **negrito**, *itálico*, $fórmulas$)",
        "sec_img": "Adicionar Figura/Gráfico nesta seção",
        "sec_caption": "Legenda da Figura",
        "s_preview": "VISUALIZAÇÃO DO PÔSTER",
        "load_sample": "Carregar Exemplo de Demonstração",
        "gen_btn": "🚀 Gerar Pôster (PDF)",
        "download_pdf": "⬇️ Baixar Pôster (PDF)",
        "download_zip": "📦 Baixar Código-Fonte LaTeX (.zip)",
        "working": "Compilando pôster LaTeX com pdflatex...",
        "success": "Pôster compilado com sucesso!",
        "overflow": "⚠️ Atenção: O conteúdo ultrapassou o espaço ideal. A fonte foi reduzida automaticamente.",
        "err_title": "Informe o título do pôster.",
        "err_sec": "Adicione conteúdo em pelo menos uma seção.",
        "ph_title": "Ex: Otimização de Algoritmos em Redes Complexas",
        "ph_authors": "Ex: Ana Silva, Carlos Santos, Orientador: Prof. Dr. João Souza",
        "ph_affiliations": "Ex: Departamento de Ciência da Computação - Universidade Federal",
        "ph_email": "contato@universidade.edu.br",
        "ph_url": "https://github.com/usuario/projeto",
        "ph_model": "Ex: gemini-2.0-flash ou gpt-4o-mini",
        "ph_api_key": "Cole sua chave de API do provedor (ou configure no ambiente local .env)",
        "ph_sec_title": "Título da seção",
        "ph_sec_content": "Texto ou tópicos...",
        "ph_caption": "Legenda da figura",
    },
    "en-US": {
        "title": "poster-generator",
        "tagline": "01 // ACADEMIC POSTER & LATEX COMPILER",
        "s_mode": "01 // INPUT MODE",
        "mode_manual": "Fill manually",
        "mode_upload": "Upload paper",
        "drop_work": "Upload your paper file (PDF, DOCX, TXT, MD, TEX)",
        "use_ai": "Use AI to condense and structure paper into poster format",
        "provider": "AI Provider",
        "model": "Model (optional)",
        "api_key": "API Key (optional if configured in environment)",
        "extract_btn": "Extract Paper Content",
        "extracting": "Analyzing and structuring paper...",
        "s_lang": "02 // POSTER LANGUAGE",
        "lang_desc": "Sets the default section headings and corresponding LaTeX babel package.",
        "s_template": "03 // TEMPLATE AND FORMAT",
        "paper": "Poster Dimensions",
        "orientation": "Orientation",
        "portrait": "Portrait (Vertical)",
        "landscape": "Landscape (Horizontal)",
        "columns": "Columns",
        "custom_colors": "Custom color palette",
        "color_accent": "Accent",
        "color_title": "Title",
        "color_subtitle": "Authors",
        "color_body": "Body",
        "color_caption": "Caption",
        "color_bg": "Background",
        "use_custom_tex": "Use custom LaTeX template (.tex)",
        "s_info": "04 // MAIN INFORMATION",
        "work_title": "Poster Title",
        "authors": "Authors",
        "affiliations": "Institutional Affiliations (one per line)",
        "email": "Contact Email",
        "url": "Paper / Repository URL (generates QR Code)",
        "logos_header": "Header Logos (PNG/JPG, max 2)",
        "logos_footer": "Footer Logos (PNG/JPG, max 5)",
        "s_sections": "05 // POSTER SECTIONS",
        "add_section": "Add New Section",
        "sec_title": "Section Title",
        "sec_content": "Content (supports '- ' bullets, **bold**, *italic*, $math$)",
        "sec_img": "Add Figure/Plot to this section",
        "sec_caption": "Figure Caption",
        "s_preview": "POSTER PREVIEW",
        "load_sample": "Load Demo Sample",
        "gen_btn": "🚀 Generate Poster (PDF)",
        "download_pdf": "⬇️ Download Poster (PDF)",
        "download_zip": "📦 Download LaTeX Source (.zip)",
        "working": "Compiling LaTeX poster with pdflatex...",
        "success": "Poster successfully compiled!",
        "overflow": "⚠️ Warning: Content exceeded space. Font size reduced automatically.",
        "err_title": "Please provide the poster title.",
        "err_sec": "Please add content to at least one section.",
        "ph_title": "e.g. Optimizing Deep Neural Networks for Edge Devices",
        "ph_authors": "e.g. Jane Doe, John Smith, Advisor: Prof. Dr. Alan Turing",
        "ph_affiliations": "e.g. Department of Computer Science - Stanford University",
        "ph_email": "contact@university.edu",
        "ph_url": "https://github.com/username/project",
        "ph_model": "e.g. gemini-2.0-flash or gpt-4o-mini",
        "ph_api_key": "Paste your provider API key (or configure in local .env)",
        "ph_sec_title": "Section title",
        "ph_sec_content": "Text or bullet points...",
        "ph_caption": "Figure caption",
    },
}

# ── Inicialização do Estado (Session State) ──
if "ui_lang" not in st.session_state:
    st.session_state.ui_lang = "pt-BR"
if "poster_lang" not in st.session_state:
    st.session_state.poster_lang = "pt-BR"
if "title" not in st.session_state:
    st.session_state.title = ""
if "authors" not in st.session_state:
    st.session_state.authors = ""
if "affiliations" not in st.session_state:
    st.session_state.affiliations = ""
if "email" not in st.session_state:
    st.session_state.email = ""
if "url" not in st.session_state:
    st.session_state.url = ""
if "template" not in st.session_state:
    st.session_state.template = "classic"
if "paper" not in st.session_state:
    st.session_state.paper = "60x90"
if "orientation" not in st.session_state:
    st.session_state.orientation = "portrait"
if "columns" not in st.session_state:
    st.session_state.columns = 2
if "sections" not in st.session_state:
    st.session_state.sections = [
        {"id": "introduction", "title": "Introdução", "content": ""},
        {"id": "methods", "title": "Metodologia", "content": ""},
        {"id": "results", "title": "Resultados", "content": ""},
        {"id": "conclusions", "title": "Conclusões", "content": ""},
        {"id": "references", "title": "Referências", "content": ""},
    ]
if "compiled_pdf" not in st.session_state:
    st.session_state.compiled_pdf = None
if "compiled_zip" not in st.session_state:
    st.session_state.compiled_zip = None
if "compiled_img" not in st.session_state:
    st.session_state.compiled_img = None
if "overflow" not in st.session_state:
    st.session_state.overflow = False


def t(key: str) -> str:
    return UI_TEXT.get(st.session_state.ui_lang, UI_TEXT["pt-BR"]).get(key, key)


def load_demo_sample():
    lang = st.session_state.get("poster_lang", "pt-BR")
    sample_file = Path("examples/sample_poster_en.json" if lang == "en-US" else "examples/sample_poster.json")
    if not sample_file.exists():
        sample_file = Path("examples/sample_poster.json")
    if sample_file.exists():
        try:
            data = json.loads(sample_file.read_text(encoding="utf-8"))
            st.session_state.title = data.get("title", "")
            st.session_state.authors = data.get("authors", "")
            st.session_state.affiliations = data.get("affiliations", "")
            st.session_state.email = data.get("email", "")
            st.session_state.url = data.get("url", "")
            st.session_state.template = data.get("template", "classic")
            st.session_state.paper = data.get("paper", "60x90")
            st.session_state.orientation = data.get("orientation", "portrait")
            st.session_state.columns = data.get("columns", 2)
            st.session_state.sections = data.get("sections", [])
            st.session_state.poster_lang = data.get("language", lang)
            msg = "Demo sample loaded successfully!" if st.session_state.get("ui_lang") == "en-US" else "Exemplo de demonstração carregado com sucesso!"
            st.success(msg)
        except Exception as e:
            st.error(f"Erro ao carregar exemplo: {e}")


# ── Cabeçalho Principal ──
col_head1, col_head2 = st.columns([3, 1])
with col_head1:
    st.markdown(
        f"""
    <div class="brand-title">
        <span class="prefix">~/</span> {t('title')}
        <span style="font-size: 11px; margin-left: 12px; color: var(--red);">[Streamlit Edition]</span>
    </div>
    <div class="brand-sub">{t('tagline')}</div>
    """,
        unsafe_allow_html=True,
    )
with col_head2:
    lang_choice = st.radio(
        "Interface Language",
        options=["pt-BR", "en-US"],
        horizontal=True,
        index=0 if st.session_state.ui_lang == "pt-BR" else 1,
        key="ui_lang_radio",
        label_visibility="collapsed",
    )
    if lang_choice != st.session_state.ui_lang:
        st.session_state.ui_lang = lang_choice
        st.rerun()

st.markdown("---")

# ── Layout de 2 Colunas: Formulário à Esquerda, Visualizador à Direita ──
col_form, col_preview = st.columns([1, 1], gap="large")

# ══════════════════════════════════════════════════════════
# COLUNA ESQUERDA: ENTRADA DE DADOS E CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════
with col_form:

    # 1. Modo de Preenchimento
    st.markdown(f'<div class="card-sec-badge">{t("s_mode")}</div>', unsafe_allow_html=True)
    input_mode = st.radio(
        "Modo",
        options=[t("mode_manual"), t("mode_upload")],
        horizontal=True,
        label_visibility="collapsed",
    )

    if input_mode == t("mode_upload"):
        uploaded_doc = st.file_uploader(
            t("drop_work"),
            type=["pdf", "docx", "txt", "md", "tex"],
            key="uploaded_paper",
        )
        use_ai = st.checkbox(t("use_ai"), value=True)
        if use_ai:
            ai_prov_col, ai_mod_col = st.columns(2)
            with ai_prov_col:
                provider = st.selectbox(
                    t("provider"),
                    options=list(config.PROVIDERS.keys()),
                    format_func=lambda x: config.PROVIDERS[x]["name"],
                )
            with ai_mod_col:
                model_input = st.text_input(t("model"), placeholder=t("ph_model"))
            api_key_input = st.text_input(t("api_key"), type="password", placeholder=t("ph_api_key"))

        if uploaded_doc and st.button(t("extract_btn")):
            with st.spinner(t("extracting")):
                try:
                    raw_bytes = uploaded_doc.read()
                    text = extract_text(uploaded_doc.name, raw_bytes)
                    result = None
                    warning = ""
                    if use_ai and text:
                        try:
                            key = resolve_key(provider, api_key_input.strip() or None)
                            result = ai_extract(text, st.session_state.poster_lang, provider, key, model_input.strip() or None)
                        except LLMError as exc:
                            warning = str(exc)
                    if result is None:
                        result = heuristic_parse(text)
                        if use_ai:
                            warning = (warning + " — ").lstrip(" — ") + "usando extração básica sem IA."

                    if result:
                        st.session_state.title = result.get("title", st.session_state.title)
                        st.session_state.authors = result.get("authors", st.session_state.authors)
                        st.session_state.affiliations = result.get("affiliations", st.session_state.affiliations)
                        st.session_state.email = result.get("email", st.session_state.email)
                        if result.get("sections"):
                            st.session_state.sections = [s for s in result["sections"] if s.get("id") != "abstract"]
                        if warning:
                            st.warning(warning)
                        else:
                            st.success("Trabalho extraído com sucesso!")
                        st.rerun()
                except Exception as exc:
                    st.error(f"Erro ao processar arquivo: {exc}")

    # 2. Idioma do Pôster
    st.markdown(f'<div class="card-sec-badge">{t("s_lang")}</div>', unsafe_allow_html=True)
    st.caption(t("lang_desc"))
    p_lang = st.radio(
        "Poster Language",
        options=list(config.LANGUAGES),
        format_func=lambda x: "🇧🇷 Português (pt-BR)" if x == "pt-BR" else "🇺🇸 English (en-US)",
        horizontal=True,
        index=0 if st.session_state.poster_lang == "pt-BR" else 1,
        label_visibility="collapsed",
    )
    st.session_state.poster_lang = p_lang

    # 3. Template e Formato
    st.markdown(f'<div class="card-sec-badge">{t("s_template")}</div>', unsafe_allow_html=True)

    template_names = {tid: tpl["name"].get(st.session_state.ui_lang, tid) for tid, tpl in TEMPLATES.items()}
    tpl_selected = st.selectbox(
        "Template",
        options=list(TEMPLATES.keys()),
        index=list(TEMPLATES.keys()).index(st.session_state.template) if st.session_state.template in TEMPLATES else 0,
        format_func=lambda x: f"{template_names[x]} ({TEMPLATES[x]['engine']})",
    )
    st.session_state.template = tpl_selected

    col_paper, col_orient, col_cols = st.columns(3)
    with col_paper:
        available_papers = papers_for(st.session_state.template)
        cur_paper_idx = available_papers.index(st.session_state.paper) if st.session_state.paper in available_papers else 0
        st.session_state.paper = st.selectbox(
            t("paper"),
            options=available_papers,
            index=cur_paper_idx,
            format_func=lambda p: f"{p.upper()} ({config.POSTER_SIZES[p]['cm'][0]} × {config.POSTER_SIZES[p]['cm'][1]} cm)" if p in config.POSTER_SIZES else p,
        )

    with col_orient:
        st.session_state.orientation = st.selectbox(
            t("orientation"),
            options=["portrait", "landscape"],
            index=0 if st.session_state.orientation == "portrait" else 1,
            format_func=lambda o: t("portrait") if o == "portrait" else t("landscape"),
        )

    with col_cols:
        st.session_state.columns = st.selectbox(
            t("columns"),
            options=[1, 2, 3, 4],
            index=st.session_state.columns - 1,
        )

    # Cores Personalizadas (Opcional)
    use_custom_colors = st.checkbox(t("custom_colors"), value=False)
    custom_colors = {}
    if use_custom_colors:
        c1, c2, c3 = st.columns(3)
        c4, c5, c6 = st.columns(3)
        with c1:
            custom_colors["accent"] = st.color_picker(t("color_accent"), value=f"#{TEMPLATES[st.session_state.template]['colors'][0]}").lstrip("#")
        with c2:
            custom_colors["title"] = st.color_picker(t("color_title"), value="#FFFFFF").lstrip("#")
        with c3:
            custom_colors["subtitle"] = st.color_picker(t("color_subtitle"), value=f"#{TEMPLATES[st.session_state.template]['colors'][1]}").lstrip("#")
        with c4:
            custom_colors["body"] = st.color_picker(t("color_body"), value="#1A1A1A").lstrip("#")
        with c5:
            custom_colors["caption"] = st.color_picker(t("color_caption"), value="#374151").lstrip("#")
        with c6:
            custom_colors["bg"] = st.color_picker(t("color_bg"), value=f"#{TEMPLATES[st.session_state.template]['bg']}").lstrip("#")

    # Template Customizado (.tex)
    use_custom_tex = st.checkbox(t("use_custom_tex"), value=False)
    custom_tex_file = None
    if use_custom_tex:
        custom_tex_file = st.file_uploader("Arquivo .tex", type=["tex"])

    # 4. Informações Principais
    st.markdown(f'<div class="card-sec-badge">{t("s_info")}</div>', unsafe_allow_html=True)
    st.session_state.title = st.text_input(t("work_title"), value=st.session_state.title, placeholder=t("ph_title"))
    st.session_state.authors = st.text_input(t("authors"), value=st.session_state.authors, placeholder=t("ph_authors"))
    st.session_state.affiliations = st.text_area(t("affiliations"), value=st.session_state.affiliations, placeholder=t("ph_affiliations"), height=70)

    info_col1, info_col2 = st.columns(2)
    with info_col1:
        st.session_state.email = st.text_input(t("email"), value=st.session_state.email, placeholder=t("ph_email"))
    with info_col2:
        st.session_state.url = st.text_input(t("url"), value=st.session_state.url, placeholder=t("ph_url"))

    # Upload de Logos
    slots = TEMPLATES[st.session_state.template]["logos"]
    uploaded_header_logos = []
    uploaded_footer_logos = []
    if slots.get("header", 0) > 0:
        uploaded_header_logos = st.file_uploader(
            t("logos_header"),
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="header_logos",
        )
    if slots.get("footer", 0) > 0:
        uploaded_footer_logos = st.file_uploader(
            t("logos_footer"),
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="footer_logos",
        )

    # 5. Seções do Pôster
    st.markdown(f'<div class="card-sec-badge">{t("s_sections")}</div>', unsafe_allow_html=True)

    sec_labels = labels_for(st.session_state.poster_lang)
    for idx, sec in enumerate(st.session_state.sections):
        with st.expander(f"📌 {sec.get('title') or sec.get('id', f'Seção {idx+1}')}", expanded=(idx < 2)):
            sec_col_t, sec_col_del = st.columns([4, 1])
            with sec_col_t:
                sec["title"] = st.text_input(t("sec_title"), value=sec.get("title", ""), placeholder=t("ph_sec_title"), key=f"sec_title_{idx}")
            with sec_col_del:
                st.write("")
                if st.button("🗑️", key=f"del_sec_{idx}", help="Remover esta seção"):
                    st.session_state.sections.pop(idx)
                    st.rerun()

            sec["content"] = st.text_area(
                t("sec_content"),
                value=sec.get("content", ""),
                placeholder=t("ph_sec_content"),
                key=f"sec_content_{idx}",
                height=100,
            )

            c_snip1, c_snip2, c_snip3 = st.columns(3)
            with c_snip1:
                if st.button("📊 + Tabela", key=f"btn_tbl_{idx}", help="Inserir modelo de tabela quantitativa"):
                    sec["content"] = (sec.get("content", "") + "\n\n| Parâmetro / Métrica | Baseline | Proposto | Variação |\n| :--- | :---: | :---: | :---: |\n| Acurácia (%) | 84.2 | 96.5 | +12.3% |\n| Macro F1 | 0.81 | 0.94 | +16.0% |\n| Latência (ms) | 48.0 | 19.5 | -59.4% |\n").strip()
                    st.rerun()
            with c_snip2:
                if st.button("🔀 + TikZ", key=f"btn_tikz_{idx}", help="Inserir modelo de fluxograma TikZ"):
                    sec["content"] = (sec.get("content", "") + "\n\n\\begin{tikzpicture}\n\\node[draw, rounded corners, fill=blue!10] (A) {Entrada / Dados};\n\\node[draw, rounded corners, fill=green!10, right=of A] (B) {Processamento & Extração};\n\\node[draw, rounded corners, fill=red!10, right=of B] (C) {Resultados & Classificação};\n\\draw[->, thick] (A) -- (B);\n\\draw[->, thick] (B) -- (C);\n\\end{tikzpicture}\n").strip()
                    st.rerun()
            with c_snip3:
                if st.button("📋 + Tópicos", key=f"btn_top_{idx}", help="Inserir tópicos formatados com citação"):
                    sec["content"] = (sec.get("content", "") + "\n\n- **Objetivo Central:** Descrição sintética da meta da pesquisa.\n- **Destaque Metodológico:** Abordagem técnica e parâmetros chave.\n- **Impacto Principal:** Resultado quantitativo comprovado [1].\n").strip()
                    st.rerun()

            # Upload de imagem na seção
            sec_img = st.file_uploader(
                f"{t('sec_img')} ({sec['title'] or idx})",
                type=["png", "jpg", "jpeg"],
                key=f"sec_img_{idx}",
            )
            if sec_img:
                sec["image_file"] = sec_img
                sec["caption"] = st.text_input(t("sec_caption"), value=sec.get("caption", ""), placeholder=t("ph_caption"), key=f"sec_cap_{idx}")
            else:
                sec.pop("image_file", None)

    if st.button(f"➕ {t('add_section')}"):
        st.session_state.sections.append({"id": f"custom_{len(st.session_state.sections)}", "title": "Nova Seção", "content": ""})
        st.rerun()


# ══════════════════════════════════════════════════════════
# COLUNA DIREITA: VISUALIZAÇÃO E DOWNLOADS
# ══════════════════════════════════════════════════════════
with col_preview:
    st.markdown(f'<div class="card-sec-badge">{t("s_preview")}</div>', unsafe_allow_html=True)

    btn_sample, btn_compile = st.columns([1, 1])
    with btn_sample:
        if st.button(f"🧪 {t('load_sample')}"):
            load_demo_sample()
            st.rerun()

    with btn_compile:
        generate_clicked = st.button(t("gen_btn"), type="primary", use_container_width=True)

    if generate_clicked:
        if not use_custom_tex and not st.session_state.title.strip():
            st.error(t("err_title"))
        elif not use_custom_tex and not any(s.get("content", "").strip() for s in st.session_state.sections):
            st.error(t("err_sec"))
        else:
            with st.spinner(t("working")):
                build_dir = Path(tempfile.mkdtemp(prefix="st_poster_"))
                try:
                    images_map = {}
                    img_counter = 0

                    # Processa logos de cabeçalho
                    header_logo_paths = []
                    for h_logo in (uploaded_header_logos or [])[: slots.get("header", 2)]:
                        saved_name = save_image(h_logo.read(), build_dir, f"hlogo_{img_counter}")
                        header_logo_paths.append(saved_name)
                        images_map[saved_name] = saved_name
                        img_counter += 1

                    # Processa logos de rodapé
                    footer_logo_paths = []
                    for f_logo in (uploaded_footer_logos or [])[: slots.get("footer", 5)]:
                        saved_name = save_image(f_logo.read(), build_dir, f"flogo_{img_counter}")
                        footer_logo_paths.append(saved_name)
                        images_map[saved_name] = saved_name
                        img_counter += 1

                    # Processa imagens das seções
                    norm_sections = []
                    for s_idx, sec in enumerate(st.session_state.sections):
                        sec_imgs = []
                        if "image_file" in sec and sec["image_file"]:
                            saved_name = save_image(sec["image_file"].read(), build_dir, f"fig_{img_counter}")
                            sec_imgs.append({"path": saved_name, "caption": sec.get("caption", "")})
                            images_map[saved_name] = saved_name
                            img_counter += 1
                        norm_sections.append(
                            {
                                "id": sec.get("id", f"sec_{s_idx}"),
                                "title": sec.get("title", ""),
                                "content": sec.get("content", ""),
                                "images": sec_imgs,
                            }
                        )

                    poster_data = {
                        "title": st.session_state.title,
                        "authors": st.session_state.authors,
                        "affiliations": st.session_state.affiliations,
                        "email": st.session_state.email,
                        "url": st.session_state.url,
                        "language": st.session_state.poster_lang,
                        "template": st.session_state.template,
                        "paper": st.session_state.paper,
                        "orientation": st.session_state.orientation,
                        "columns": st.session_state.columns,
                        "colors": custom_colors if use_custom_colors else {},
                        "logos_header": header_logo_paths,
                        "logos_footer": footer_logo_paths,
                        "sections": norm_sections,
                    }

                    if use_custom_tex and custom_tex_file:
                        tex_str = custom_tex_file.read().decode("utf-8", errors="replace")
                        pdf_bytes, _ = compile_tex(tex_str, build_dir)
                        zip_bytes = make_zip(tex_str, build_dir)
                        overflow = False
                    else:
                        normalized = normalize_poster(poster_data)
                        pdf_bytes, final_tex, overflow = fit_compile(normalized, images_map, build_dir)
                        zip_bytes = make_zip(final_tex, build_dir)

                    st.session_state.compiled_pdf = pdf_bytes
                    st.session_state.compiled_zip = zip_bytes
                    st.session_state.overflow = overflow

                    # Renderiza página 1 como PNG para visualização
                    pdf_path = build_dir / "poster.pdf"
                    png_prefix = build_dir / "preview_page"
                    pdftoppm = shutil.which("pdftoppm")
                    if pdftoppm and pdf_path.exists():
                        subprocess.run([pdftoppm, "-png", "-r", "120", str(pdf_path), str(png_prefix)], check=False)
                        generated_pngs = sorted(build_dir.glob("preview_page-*.png"))
                        if generated_pngs:
                            st.session_state.compiled_img = generated_pngs[0].read_bytes()
                    else:
                        st.session_state.compiled_img = None

                    st.success(t("success"))
                except Exception as exc:
                    st.error(f"Erro na compilação: {exc}")
                finally:
                    shutil.rmtree(build_dir, ignore_errors=True)

    # Exibe avisos de overflow se houver
    if st.session_state.overflow:
        st.warning(t("overflow"))

    # Exibe visualização da imagem compilada ou fallback
    if st.session_state.compiled_img:
        st.image(st.session_state.compiled_img, caption="Pré-visualização do Pôster", use_column_width=True)
    elif st.session_state.compiled_pdf:
        st.info("Pôster compilado. Baixe o PDF abaixo para visualizar.")

    # Botões de Download
    if st.session_state.compiled_pdf:
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                label=t("download_pdf"),
                data=st.session_state.compiled_pdf,
                file_name=f"poster-{st.session_state.template}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        with dl_col2:
            st.download_button(
                label=t("download_zip"),
                data=st.session_state.compiled_zip,
                file_name=f"poster-{st.session_state.template}-latex.zip",
                mime="application/zip",
                use_container_width=True,
            )
    else:
        st.markdown(
            """
        <div style="border: 1px dashed var(--line); padding: 40px 20px; text-align: center; border-radius: 4px; color: var(--muted); margin-top: 15px;">
            <div style="font-size: 32px; margin-bottom: 8px;">📑</div>
            <div>A pré-visualização do pôster compilado aparecerá aqui após clicar em <strong>"Gerar Pôster"</strong>.</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

<div align="center">

# ~/ poster-generator

**Academic Poster Compiler · LaTeX to High-Resolution PDF**

[![CI & Test Suite](https://github.com/Jluckmay/poster-generator/actions/workflows/ci.yml/badge.svg)](https://github.com/Jluckmay/poster-generator/actions/workflows/ci.yml)
[![Deploy GitHub Pages](https://github.com/Jluckmay/poster-generator/actions/workflows/deploy-pages.yml/badge.svg)](https://github.com/Jluckmay/poster-generator/actions/workflows/deploy-pages.yml)
[![Release & Executable](https://github.com/Jluckmay/poster-generator/actions/workflows/release.yml/badge.svg)](https://github.com/Jluckmay/poster-generator/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

**Language / Idioma:**  
[English](#english) · [Português](#português)

</div>

---

<a name="english"></a>
# English

**poster-generator** is an automated academic poster compiler that converts structured content or scientific publications directly into print-ready **LaTeX → PDF** documents. Supporting multiple underlying LaTeX engines (`tikzposter`, `article`, `sciposter`, `a0poster`, `beamerposter`), it provides rigorous, consistent localization in **en-US** ("poster") and **pt-BR** ("pôster").

The project includes three complete and integrated interfaces:
1. **Web SPA Frontend (`index.html`)**: Responsive HTML5 + CSS3 + vanilla JavaScript application with PDF.js viewer, real-time draft rendering, dark/light theme awareness, and GitHub Pages compatibility.
2. **Local Streamlit Application (`app.py`)**: Native Python interactive application for local generation, AI extraction, custom palette management, and instant compilation.
3. **Standalone Desktop Executable (`poster-generator.exe`)**: Self-contained Windows application packaged via PyInstaller that starts a secure local backend and automatically opens the browser at `http://127.0.0.1:5000`.

---

## 📁 Project Structure

```
poster-generator/
├── .github/
│   └── workflows/
│       ├── ci.yml               # Automated test suite and security checks on GitHub Actions
│       ├── deploy-pages.yml     # Continuous deployment of static SPA to GitHub Pages
│       └── release.yml          # Automated Windows .exe build and GitHub Release publisher
├── assets/                      # Visual identity, logos, and icons
│   ├── icons/                   # Multi-format favicons (SVG, PNG, ICO)
│   └── README.md                # Asset design specifications
├── examples/                    # Sample payloads and API usage files
│   ├── sample_poster.json       # Portuguese sample poster payload (60x90 cm)
│   ├── sample_poster_en.json    # English sample poster payload (60x90 cm)
│   └── README.md                # cURL API testing guide
├── scripts/                     # Utility scripts and deployment tooling
│   └── build_exe.py             # PyInstaller standalone desktop compiler script
├── src/                         # Backend application core
│   ├── a0poster.py              # UZH / LiRI template renderer (a0poster engine)
│   ├── article.py               # Academic Red template renderer (article engine)
│   ├── beamer.py                # TU Delft template renderer (beamerposter engine)
│   ├── config.py                # Dimensions (POSTER_SIZES), providers, limits, and server keys
│   ├── extractors.py            # Text extraction from PDF, DOCX, TXT, MD, and TEX
│   ├── i18n.py                  # Localization dictionaries (pt-BR / en-US) and section aliases
│   ├── images.py                # Safe image decoding, sanitization, and downscaling
│   ├── latex.py                 # pdflatex compilation, font fitting, and zip generation
│   ├── llm.py                   # Multi-provider LLM client (NVIDIA NIM, Gemini, OpenAI, Claude, DeepSeek)
│   ├── poster.py                # Poster normalization, input sanitization, and validation
│   ├── sciposter.py             # Mostra IC template renderer (sciposter engine)
│   └── templates.py             # Registry and palettes for all 9 visual templates
├── tests/                       # Automated test suite (pytest)
│   ├── conftest.py              # Test fixtures and Flask test client
│   └── test_poster.py           # Unit, integration, security, and rendering tests
├── .dockerignore                # Ignored files for Docker build
├── .gitignore                   # Ignored files for Git tracking
├── .nojekyll                    # Disables Jekyll processing on GitHub Pages
├── app.py                       # Local interactive Streamlit application
├── desktop.py                   # Desktop launcher for standalone executable
├── Dockerfile                   # TeX Live + Gunicorn Docker container for Render/Cloud
├── index.html                   # Web SPA interface (HTML5 + CSS3 + vanilla JS)
├── LICENSE                      # MIT Open Source License
├── pyproject.toml               # Python package metadata and configuration
├── render.yaml                  # Infrastructure-as-Code deployment manifest for Render
├── requirements.txt             # Project runtime dependencies
└── server.py                    # Flask web server and REST API endpoints
```

---

## 🚀 Key Features

### 1. Canonical 5-Section Academic Layout (No Redundant Abstract)
- Standardized strictly to the **5 canonical scientific poster sections**:
  - **Introduction** (includes high-level context and problem motivation)
  - **Methodology**
  - **Results**
  - **Conclusions**
  - **References**
- Eliminates redundant abstract blocks to maximize high-value space for data, tables, and figures.

### 2. Intelligent Document Extraction & Data Visualization
- **Automatic Upload Extraction**: Extraction begins immediately upon selecting or dragging any document (`.pdf`, `.docx`, `.txt`, `.md`, `.tex`).
- **AI-Powered Synthesis** (NVIDIA NIM, Google Gemini, OpenAI, Anthropic Claude, DeepSeek):
  - **LaTeX Tables in Results**: Automatically synthesizes quantitative benchmarks, metrics, and comparisons into clean LaTeX tabular environments (`tabular` / `booktabs`).
  - **TikZ Flowcharts in Methodology**: Generates vector pipeline diagrams (`tikzpicture`) illustrating multi-stage architectures, workflows, and experimental setups.
  - **Strict Truthfulness**: Zero hallucination; pure fidelity to explicit paper findings and data.
  - **Target Language Enforcement**: Full translation into the selected language (`en-US` or `pt-BR`).
- **Heuristic Fallback** (Offline / No Key): Robust header-based regex parser that extracts sections, authors, affiliations, and emails without needing AI credentials.

### 3. Visual Resources in Manual Fill Mode
- Quick-insert snippet toolbars in each section:
  - `+ 📊 Table`: Inserts clean comparative quantitative table templates (Markdown / LaTeX).
  - `+ 🔀 TikZ Diagram`: Inserts structured methodology pipeline flowcharts.
  - `+ 📋 Bullets`: Inserts scannable bullet points with bold lead-ins.
  - `+ 📎 Attach Image`: Direct upload of high-resolution figures.

### 4. Floating Superscript Citations & Clean References List
- **Floating Citations**: Numerical in-text citations like `[1]`, `[2, 3]` are automatically formatted as superscripts (`\textsuperscript{[1]}` in LaTeX and `<sup class="draft-cite">[1]</sup>` in HTML draft preview) to conserve space.
- **Structured References List**: References render as an enumerated list (`<ol class="draft-refs-list">`) with individual breaks, preventing wall-of-text blocks.

### 5. 9 Visual Style Templates
- **Classic**: Traditional academic conference format (`tikzposter`).
- **Modern**: Clean vertical gradient and contemporary typography (`tikzposter`).
- **Minimal**: Editorial, minimalist layout with high contrast (`tikzposter`).
- **Bold**: High-contrast warm blocks (`tikzposter`).
- **Emerald Waves**: Curved accents in emerald tones (`tikzposter`).
- **Academic Red**: Contrasting header/footer accent bars with up to 5 footer logos (`article`).
- **Mostra IC**: Scientific symposium layout with callout boxes (`sciposter`).
- **UZH / LiRI**: Swiss academic institutional typography (`a0poster`).
- **TU Delft**: Modular column layout based on Beamer (`beamerposter`).

### 6. Universal Dimensions & Orientations
- **Standard Dimensions**: **60 × 90 cm** (Default), **90 × 120 cm**, **A0** (84.1 × 118.9 cm), **A1** (59.4 × 84.1 cm), **A2** (42.0 × 59.4 cm).
- **Orientations**: **Portrait** (Vertical) and **Landscape** (Horizontal).
- Dynamic CSS aspect ratio scaling and zero distortion across dimensions.

### 7. Advanced Customization & Theming
- **Hexadecimal Color Palette & Dark Popover**:
  - Dedicated control over 6 document colors (`Accent`, `Title`, `Authors`, `Body`, `Caption`, `Background`).
  - Monospace hex inputs (`#RRGGBB`) with bidirectional synchronization.
  - Floating dark color picker with 2D saturation/brightness canvas, hue slider, eyedropper tool (*EyeDropper API*), and template preset chips.
- **Theme-Aware Preview**: Preview container smoothly toggles between Dark Mode and Light Mode backgrounds.
- **Custom LaTeX Template (`.tex`)**: Upload and direct compilation of external `.tex` templates.

### 8. Full Mobile & Desktop Responsiveness
- Fluid layout tested from 360px mobile viewports up to 1920px+ desktop monitors.
- Mobile bottom sheet drawer for live previews and floating action bar.

### 9. Export & Zero-Overflow Compilation
- **Live Draft Preview**: Instant client-side DOM rendering.
- **PDF.js Viewer**: High-fidelity page viewer with zoom and fit controls.
- **Zero-Overflow**: Automatic font scale-down algorithm if content exceeds paper boundaries.
- **Direct Downloads**: Print-ready PDF or full LaTeX source bundle (`.zip` containing `poster.tex` and figures).

---

## 🔒 Security & Sandboxing

- **LaTeX Isolation**: Strict execution with `pdflatex -no-shell-escape` and hard timeout (`LATEX_TIMEOUT_S = 150`).
- **Dangerous Command Blacklist**: Blocks `\input`, `\write18`, `\openin`, `\catcode`, `\def`, `\let`, `\directlua`, and TeX macros.
- **Math Sanitization**: Formula expressions `$...$` whitelisted against safe LaTeX math tokens.
- **Zero-Storage**: Ephemeral build sandboxes created via `tempfile.mkdtemp` and purged after response delivery.
- **XML / DOCX Protection**: Word documents sanitized using `defusedxml`.
- **Image Hygiene**: Re-encoded and verified through Pillow before inclusion.
- **Strict Web Security**: Content-Security-Policy (CSP) headers, XSS escaping, and explicit memory release with `URL.revokeObjectURL`.

---

## 🛠️ Installation & Execution

### Prerequisites
- Python ≥ 3.10
- LaTeX distribution installed (`pdflatex` in PATH): [TeX Live](https://www.tug.org/texlive/) or [MiKTeX](https://miktex.org/).

```bash
# 1. Clone the repository
git clone https://github.com/Jluckmay/poster-generator.git
cd poster-generator

# 2. Install dependencies
pip install -r requirements.txt
```

### Option A: Standalone Windows Executable (.exe)
1. Download `poster-generator-windows-x64.zip` from the latest [GitHub Release](https://github.com/Jluckmay/poster-generator/releases).
2. Extract the ZIP and double-click `poster-generator.exe`.
3. The app starts a local server and opens `http://127.0.0.1:5000` in your default browser.

To compile the executable yourself:
```bash
python scripts/build_exe.py
```
Output is created in `dist/poster-generator.exe`.

### Option B: Local Streamlit Application (`app.py`)
Run the interactive Streamlit interface:
```bash
streamlit run app.py
```
Opens in your browser at `http://localhost:8501`.

### Option C: Flask REST Server + Web SPA (`server.py`)
Run the Flask API backend and serve the Web SPA:
```bash
python server.py
```
Available at `http://127.0.0.1:5000`.

### Running Automated Tests
```bash
python -m pytest
```

---

## 🔑 AI Providers & Credentials

API keys can be supplied directly in the interface (per request, never saved to disk) or via environment variables:
```bash
export NVIDIA_API_KEY="your-key"
export GEMINI_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
export ANTHROPIC_API_KEY="your-key"
export DEEPSEEK_API_KEY="your-key"
```

---

## 🌐 Hosting & Architecture

- **GitHub Pages Frontend (`https://jluckmay.github.io/poster-generator/`)**:
  - Static SPA deployed via `.github/workflows/deploy-pages.yml`.
  - **Dynamic Backend Resolution**: Points to Render production backend on GitHub Pages, and to `http://127.0.0.1:5000` when running locally.
  - **Non-Blocking Initialization**: Background server wake-up never blocks UI editing or draft preview.
- **Render Production Backend (`https://poster-generator-nkqh.onrender.com`)**:
  - Dockerized TeX Live and Gunicorn backend configured in `render.yaml`.
  - **Strict CORS Policy**: Restricted exclusively to `https://jluckmay.github.io` and local origins.
  - **Cold-Start Resilience**: Heartbeat pinging and `robustFetch` retry logic.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

<br><br>

---

<a name="português"></a>
# Português

O **poster-generator** é um compilador e gerador automatizado de pôsteres acadêmicos que converte dados estruturados ou artigos científicos diretamente em documentos **LaTeX → PDF** prontos para impressão. Com suporte a múltiplos motores LaTeX (`tikzposter`, `article`, `sciposter`, `a0poster`, `beamerposter`), oferece localização completa e consistente em **pt-BR** ("pôster") e **en-US** ("poster").

O projeto conta com três interfaces completas e integradas:
1. **Aplicação Web SPA (`index.html`)**: Aplicação responsiva em HTML5 + CSS3 + JavaScript puro com visualizador PDF.js integrado, rascunho em tempo real, suporte dinâmico a temas claro/escuro e deploy no GitHub Pages.
2. **Aplicação Local Streamlit (`app.py`)**: Interface interativa nativa em Python para geração direta, extração por IA, customização de paleta e compilação instantânea.
3. **Executável Desktop Standalone (`poster-generator.exe`)**: Aplicativo autônomo para Windows gerado via PyInstaller que inicia o servidor local seguro e abre automaticamente o navegador padrão em `http://127.0.0.1:5000`.

---

## 📁 Estrutura do Projeto

```
poster-generator/
├── .github/
│   └── workflows/
│       ├── ci.yml               # Pipeline de testes automatizados e lint no GitHub Actions
│       ├── deploy-pages.yml     # Deploy contínuo da SPA estática no GitHub Pages
│       └── release.yml          # Build automatizado de .exe para Windows e publicação em Releases
├── assets/                      # Identidade visual, logos e ícones
│   ├── icons/                   # Favicons em múltiplos formatos (SVG, PNG, ICO)
│   └── README.md                # Especificações de design dos assets
├── examples/                    # Payloads e exemplos de uso via API
│   ├── sample_poster.json       # Exemplo em Português (padrão 60x90 cm)
│   ├── sample_poster_en.json    # Exemplo em Inglês (padrão 60x90 cm)
│   └── README.md                # Guia de teste da API com cURL
├── scripts/                     # Scripts utilitários e automação
│   └── build_exe.py             # Script de compilação do executável standalone com PyInstaller
├── src/                         # Núcleo da aplicação backend
│   ├── a0poster.py              # Renderizador do template UZH / LiRI (motor a0poster)
│   ├── article.py               # Renderizador do template Academic Red (motor article)
│   ├── beamer.py                # Renderizador do template TU Delft (motor beamerposter)
│   ├── config.py                # Dimensões (POSTER_SIZES), provedores, limites e chaves de servidor
│   ├── extractors.py            # Extração de texto de PDF, DOCX, TXT, MD e TEX
│   ├── i18n.py                  # Dicionários de localização (pt-BR / en-US) e aliases de seções
│   ├── images.py                # Sanitização, decodificação segura e redimensionamento de imagens
│   ├── latex.py                 # Compilação pdflatex, ajuste de fonte e geração zip
│   ├── llm.py                   # Cliente multi-provedor de IA (NVIDIA NIM, Gemini, OpenAI, Claude, DeepSeek)
│   ├── poster.py                # Normalização, sanitização e validação dos dados do pôster
│   ├── sciposter.py             # Renderizador do template Mostra IC (motor sciposter)
│   └── templates.py             # Registro e paletas dos 9 templates disponíveis
├── tests/                       # Suíte de testes automatizados (pytest)
│   ├── conftest.py              # Fixtures e cliente de teste Flask
│   └── test_poster.py           # Testes unitários, de integração, segurança e compilação
├── .dockerignore                # Arquivos ignorados no build Docker
├── .gitignore                   # Arquivos ignorados no versionamento Git
├── .nojekyll                    # Desativa processamento Jekyll no GitHub Pages
├── app.py                       # Interface local interativa em Streamlit
├── desktop.py                   # Launcher desktop para executável standalone
├── Dockerfile                   # Container Docker com TeX Live e Gunicorn para Render/Cloud
├── index.html                   # Interface Web SPA (HTML5 + CSS3 + JS puro)
├── LICENSE                      # Licença de Código Aberto MIT
├── pyproject.toml               # Metadados do pacote Python e configurações de build
├── render.yaml                  # Manifesto Infrastructure-as-Code para deploy no Render
├── requirements.txt             # Dependências de execução do projeto
└── server.py                    # Servidor web Flask e rotas da API REST
```

---

## 🚀 Recursos Principais

### 1. Estrutura Canônica de 5 Seções (Sem Resumo Redundante)
- Padronização estrita nas **5 seções canônicas de eventos científicos**:
  - **Introdução** (inclui motivação e contexto do trabalho)
  - **Metodologia**
  - **Resultados**
  - **Conclusões**
  - **Referências**
- Eliminação de blocos redundantes de resumo para maximizar espaço útil para dados, tabelas e figuras.

### 2. Extração Inteligente de Artigos & Visualização de Dados
- **Extração Automática no Upload**: O processamento inicia imediatamente ao selecionar ou soltar qualquer documento (`.pdf`, `.docx`, `.txt`, `.md`, `.tex`).
- **Síntese por Inteligência Artificial** (NVIDIA NIM, Google Gemini, OpenAI, Anthropic Claude, DeepSeek):
  - **Tabelas LaTeX nos Resultados**: Estrutura dados quantitativos, métricas e benchmarks automaticamente em ambientes tabulares limpos (`tabular` / `booktabs`).
  - **Fluxogramas TikZ na Metodologia**: Cria diagramas vetoriais (`tikzpicture`) ilustrando etapas metodológicas, pipelines e arquiteturas.
  - **Fidelidade Estrita**: Zero alucinação; total adesão aos dados e fatos do artigo original.
  - **Consistência de Idioma**: Tradução acadêmica fluida para o idioma do pôster (`pt-BR` ou `en-US`).
- **Extração Heurística Offline** (Sem Chave): Parser robusto baseado em expressões regulares que identifica cabeçalhos, autores, filiações e emails sem depender de internet ou IA.

### 3. Recursos Visuais no Preenchimento Manual
- Barra de snippets rápidos em cada seção:
  - `+ 📊 Tabela`: Insere modelos de tabelas comparativas formatadas (Markdown / LaTeX).
  - `+ 🔀 Diagrama TikZ`: Insere modelos de pipelines metodológicos visuais.
  - `+ 📋 Tópicos`: Insere listas com lead-ins em negrito.
  - `+ 📎 Anexar Imagem`: Upload direto de figuras de alta resolução.

### 4. Citações Numéricas Flutuantes & Lista de Referências Limpa
- **Citações Flutuantes**: Notações numéricas no texto (ex: `[1]`, `[2, 3]`) convertidas para expoente sobrescrito (`\textsuperscript{[1]}` no LaTeX e `<sup class="draft-cite">[1]</sup>` no preview), economizando espaço horizontal.
- **Lista Estruturada de Referências**: Exibição como lista ordenada `<ol class="draft-refs-list">` com separação individual, evitando blocos densos de texto corrido.

### 5. 9 Templates de Estilo Visual
- **Clássico**: Visual tradicional acadêmico para conferências (`tikzposter`).
- **Moderno**: Gradiente vertical e visual contemporâneo leve (`tikzposter`).
- **Minimalista**: Estilo editorial neutro e limpo (`tikzposter`).
- **Ousado**: Blocos envolventes com cores quentes (`tikzposter`).
- **Ondas Esmeralda**: Acabamento com curvas e tons esmeralda (`tikzposter`).
- **Academic Red**: Barras de contraste superior/inferior, suporte a até 5 logos de rodapé (`article`).
- **Mostra IC**: Estilo científico com caixas de destaque (`sciposter`).
- **UZH / LiRI**: Layout institucional suíço com tipografia sóbria (`a0poster`).
- **TU Delft**: Estrutura modular em colunas com base em Beamer (`beamerposter`).

### 6. Dimensões Universais e Orientações
- **Dimensões Suportadas**: **60 × 90 cm** (Padrão), **90 × 120 cm**, **A0** (84.1 × 118.9 cm), **A1** (59.4 × 84.1 cm), **A2** (42.0 × 59.4 cm).
- **Orientações**: **Retrato** (Vertical) e **Paisagem** (Landscape).
- Adaptação proporcional dinâmica sem distorções no design.

### 7. Customização Avançada & Temas
- **Paleta de Cores Hexadecimal & Seletor Dark Integrado**:
  - Controle individual das 6 cores do documento (`Destaque`, `Título`, `Autores`, `Texto`, `Legenda`, `Fundo`).
  - Campos hexadecimais explícitos (`#RRGGBB`) com sincronização bidirecional.
  - Seletor flutuante escuro com canvas 2D de saturação/brilho, slider de matiz, conta-gotas (*EyeDropper API*) e chips de presets dos templates.
- **Fundo do Preview Dinâmico**: O container de pré-visualização alterna automaticamente entre temas claro e escuro.
- **Template LaTeX Próprio (`.tex`)**: Upload e compilação direta de templates `.tex` personalizados.

### 8. Responsividade Total (Mobile a Desktop)
- Layout fluido testado em resoluções de 360px a 1920px+.
- Drawer deslizante (bottom sheet) em dispositivos móveis e barra de ações flutuante.

### 9. Exportação & Compilação Zero-Overflow
- **Rascunho em Tempo Real**: Pré-visualização instantânea no cliente via DOM.
- **Visualizador PDF.js**: Visualização em alta resolução com controles de zoom e ajuste.
- **Zero-Overflow**: Algoritmo de redução inteligente de tamanho de fonte se o conteúdo exceder a página.
- **Downloads Diretos**: PDF de alta resolução pronto para impressão ou pacote completo `.zip` contendo código-fonte LaTeX (`poster.tex`) e imagens.

---

## 🔒 Segurança & Isolamento

- **Isolamento de LaTeX**: Execução com `pdflatex -no-shell-escape` e tempo limite estrito (`LATEX_TIMEOUT_S = 150`).
- **Bloqueio de Comandos Perigosos**: Interdição de `\input`, `\write18`, `\openin`, `\catcode`, `\def`, `\let`, `\directlua` e macros TeX de sistema.
- **Sanitização Matemática**: Expressões `$...$` validadas contra lista de comandos matemáticos seguros.
- **Zero-Storage**: Processamento em diretórios temporários efêmeros (`tempfile.mkdtemp`), completamente removidos após a resposta.
- **Prevenção XML / DOCX**: Arquivos Word processados de forma segura através do `defusedxml`.
- **Higiene de Imagens**: Revalidação e decodificação via Pillow antes da inclusão no documento.
- **Segurança Web**: Políticas rigorosas de Content-Security-Policy (CSP), escape contra XSS e liberação explícita de memória via `URL.revokeObjectURL`.

---

## 🛠️ Instalação e Execução

### Pré-requisitos
- Python ≥ 3.10
- Distribuição LaTeX instalada (`pdflatex` no PATH): [TeX Live](https://www.tug.org/texlive/) ou [MiKTeX](https://miktex.org/).

```bash
# 1. Clonar o repositório
git clone https://github.com/Jluckmay/poster-generator.git
cd poster-generator

# 2. Instalar dependências
pip install -r requirements.txt
```

### Opção A: Executável Windows Standalone (.exe)
1. Baixe o arquivo `poster-generator-windows-x64.zip` na aba [GitHub Releases](https://github.com/Jluckmay/poster-generator/releases).
2. Extraia o ZIP e execute `poster-generator.exe`.
3. A aplicação inicia o servidor local seguro e abre automaticamente `http://127.0.0.1:5000` no seu navegador padrão.

Para compilar o executável na sua própria máquina:
```bash
python scripts/build_exe.py
```
O arquivo final é salvo em `dist/poster-generator.exe`.

### Opção B: Interface Local em Streamlit (`app.py`)
Inicia a aplicação Python interativa:
```bash
streamlit run app.py
```
Acessível no navegador em `http://localhost:8501`.

### Opção C: Servidor Flask REST + Interface Web SPA (`server.py`)
Inicia o backend Flask e serve o frontend SPA:
```bash
python server.py
```
Acessível em `http://127.0.0.1:5000`.

### Executar a Suíte de Testes Automatizados
```bash
python -m pytest
```

---

## 🔑 Provedores de IA & Credenciais

As chaves de API podem ser inseridas diretamente na interface do usuário (por chamada, jamais gravadas em disco) ou configuradas como variáveis de ambiente:
```bash
export NVIDIA_API_KEY="sua-chave"
export GEMINI_API_KEY="sua-chave"
export OPENAI_API_KEY="sua-chave"
export ANTHROPIC_API_KEY="sua-chave"
export DEEPSEEK_API_KEY="sua-chave"
```

---

## 🌐 Hospedagem & Arquitetura

- **Frontend no GitHub Pages (`https://jluckmay.github.io/poster-generator/`)**:
  - SPA estática hospedada via `.github/workflows/deploy-pages.yml`.
  - **Resolução Dinâmica de Backend**: Conecta automaticamente ao backend Render no GitHub Pages e ao servidor local (`http://127.0.0.1:5000`) em execuções locais.
  - **Inicialização Sem Travamento**: Verificações de servidor em background nunca bloqueiam a navegação ou o rascunho em tempo real.
- **Backend de Produção no Render (`https://poster-generator-nkqh.onrender.com`)**:
  - Container Docker com TeX Live e Gunicorn configurado em `render.yaml`.
  - **CORS Estrito**: Restrito exclusivamente a `https://jluckmay.github.io` e ambientes de desenvolvimento local.
  - **Resiliência a Cold-Start**: Heartbeats e retentativas automáticas (`robustFetch`).

---

## 📄 Licença

Este projeto é distribuído sob os termos da [Licença MIT](LICENSE).

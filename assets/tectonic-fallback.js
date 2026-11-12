/* Browser fallback compiler built from nl5887/tectonic-wasm (MIT). */
(function () {
  "use strict";

  const BASE = new URL("tectonic/", document.currentScript.src);
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let compilerPromise;

  function readCString(bytes, start, end) {
    let stop = start;
    while (stop < end && bytes[stop] !== 0) stop++;
    return decoder.decode(bytes.subarray(start, stop));
  }

  function parseTarGzip(gzipBytes) {
    if (typeof DecompressionStream !== "function") {
      throw new Error("Este navegador não oferece descompressão gzip necessária ao compilador local.");
    }
    return new Response(new Blob([gzipBytes]).stream().pipeThrough(new DecompressionStream("gzip")))
      .arrayBuffer().then(buffer => {
        const tar = new Uint8Array(buffer);
        const files = [];
        for (let offset = 0; offset + 512 <= tar.length;) {
          const header = tar.subarray(offset, offset + 512);
          if (header.every(byte => byte === 0)) break;
          const name = readCString(header, 0, 100);
          const prefix = readCString(header, 345, 500);
          const path = (prefix ? `${prefix}/${name}` : name).replace(/^\.\//, "");
          const sizeText = readCString(header, 124, 136).trim();
          const size = parseInt(sizeText || "0", 8) || 0;
          const type = String.fromCharCode(header[156] || 48);
          const dataStart = offset + 512;
          if (path && (type === "0" || type === "7")) {
            files.push([path, tar.slice(dataStart, dataStart + size)]);
          }
          offset = dataStart + Math.ceil(size / 512) * 512;
        }
        if (!files.some(([name]) => name === "latex.fmt")) {
          throw new Error("O bundle Tectonic local não contém latex.fmt.");
        }
        return files;
      });
  }

  function makeImports(module) {
    let instance = null;
    let stdout = "";
    const imports = {};
    const getView = () => new DataView(instance.exports.memory.buffer);
    const writeU32 = (pointer, value) => getView().setUint32(pointer, value >>> 0, true);
    const writeU64 = (pointer, value) => getView().setBigUint64(pointer, BigInt(value), true);
    const invoke = (...args) => {
      const table = instance && instance.exports.__indirect_function_table;
      if (!table) throw new Error("Tabela de funções Tectonic não inicializada.");
      const target = table.get(args[0]);
      if (typeof target !== "function") throw new Error("Callback WASM inválido.");
      return target(...args.slice(1));
    };
    const wasi = {
      args_sizes_get: (argc, size) => { writeU32(argc, 0); writeU32(size, 0); return 0; },
      args_get: () => 0,
      environ_sizes_get: (count, size) => { writeU32(count, 0); writeU32(size, 0); return 0; },
      environ_get: () => 0,
      proc_exit: code => { throw new Error(`Tectonic WASM encerrou com código ${code}.`); },
      fd_close: () => 0,
      fd_read: (_fd, _iov, _count, readPtr) => { writeU32(readPtr, 0); return 0; },
      fd_write: (fd, iov, count, writtenPtr) => {
        let total = 0;
        const view = getView();
        for (let i = 0; i < count; i++) {
          const ptr = view.getUint32(iov + i * 8, true);
          const len = view.getUint32(iov + i * 8 + 4, true);
          const value = decoder.decode(new Uint8Array(instance.exports.memory.buffer, ptr, len));
          total += len;
          if (fd === 2) stdout += value;
        }
        writeU32(writtenPtr, total);
        return 0;
      },
      fd_seek: (_fd, _offset, _whence, resultPtr) => { writeU64(resultPtr, 0); return 0; },
      clock_time_get: (_clock, _precision, resultPtr) => { writeU64(resultPtr, BigInt(Date.now()) * 1000000n); return 0; },
      random_get: (ptr, len) => {
        const view = new Uint8Array(instance.exports.memory.buffer);
        for (let offset = 0; offset < len; offset += 65536) {
          crypto.getRandomValues(view.subarray(ptr + offset, ptr + Math.min(len, offset + 65536)));
        }
        return 0;
      }
    };
    const env = {
      emscripten_longjmp: () => { throw new Error("Tectonic WASM interrompeu a compilação."); },
      emscripten_notify_memory_growth: () => {},
      hb_graphite2_face_get_gr_face: () => 0,
      __main_argc_argv: () => 0,
      __syscall_getcwd: (ptr, len) => {
        const text = encoder.encode("/\0");
        if (len < text.length) return -1;
        new Uint8Array(instance.exports.memory.buffer, ptr, text.length).set(text);
        return text.length - 1;
      },
      __syscall_unlinkat: () => 0,
      __syscall_rmdir: () => 0
    };
    for (const item of WebAssembly.Module.imports(module)) {
      const namespace = item.module === "wasi_snapshot_preview1" ? wasi : env;
      if (item.name.startsWith("invoke_")) namespace[item.name] = invoke;
      if (item.kind !== "function" || typeof namespace[item.name] !== "function") {
        throw new Error(`Import WASM não suportado: ${item.module}.${item.name}`);
      }
      (imports[item.module] ||= {})[item.name] = namespace[item.name];
    }
    return { imports, setInstance(value) { instance = value; }, getLog() { return stdout; } };
  }

  async function loadCompiler(onStatus) {
    if (!compilerPromise) {
      compilerPromise = (async () => {
        onStatus("Carregando o compilador Tectonic WASM...");
        const [wasmResponse, bundleResponse] = await Promise.all([
          fetch(new URL("tectonic_wasm.wasm", BASE)),
          fetch(new URL("tectonic-bundle.tar.gz", BASE))
        ]);
        if (!wasmResponse.ok || !bundleResponse.ok) throw new Error("Não foi possível carregar os arquivos locais do Tectonic.");
        const [wasmBytes, bundleBytes] = await Promise.all([wasmResponse.arrayBuffer(), bundleResponse.arrayBuffer()]);
        onStatus("Preparando os pacotes LaTeX locais (primeira compilação)...");
        const packageFiles = await parseTarGzip(bundleBytes);
        const module = await WebAssembly.compile(wasmBytes);
        return { module, packageFiles };
      })().catch(error => { compilerPromise = null; throw error; });
    }
    return compilerPromise;
  }

  function allocBytes(instance, bytes) {
    const ptr = instance.exports.malloc(Math.max(1, bytes.length));
    if (!ptr) throw new Error("Memória insuficiente para compilar o pôster.");
    new Uint8Array(instance.exports.memory.buffer, ptr, bytes.length).set(bytes);
    return ptr;
  }

  function addFile(instance, name, bytes) {
    const nameBytes = encoder.encode(name);
    const namePtr = allocBytes(instance, nameBytes);
    const dataPtr = allocBytes(instance, bytes);
    try {
      instance.exports.tectonic_add_file(namePtr, nameBytes.length, dataPtr, bytes.length);
    } finally {
      instance.exports.free(namePtr);
      instance.exports.free(dataPtr);
    }
  }

  async function rasterize(file) {
    if (!file || !file.type.startsWith("image/")) throw new Error(`Arquivo de imagem inválido: ${file && file.name}`);
    const bitmap = await createImageBitmap(file);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, bitmap.width);
    canvas.height = Math.max(1, bitmap.height);
    canvas.getContext("2d", { alpha: true }).drawImage(bitmap, 0, 0);
    bitmap.close();
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error(`Não foi possível converter ${file.name} para PNG.`);
    return new Uint8Array(await blob.arrayBuffer());
  }

  function escapeTex(text) {
    return String(text || "").replace(/[\\{}#$%&_]/g, ch => ({
      "\\": "\\textbackslash{}", "{": "\\{", "}": "\\}", "#": "\\#", "$": "\\$",
      "%": "\\%", "&": "\\&", "_": "\\_"
    })[ch]).replace(/\^/g, "\\textasciicircum{}").replace(/~/g, "\\textasciitilde{}");
  }

  function inlineTex(text) {
    const bold = [];
    let value = escapeTex(text).replace(/\*\*(.+?)\*\*/g, (_, part) => {
      bold.push(part); return `\u0000B${bold.length - 1}\u0000`;
    });
    value = value.replace(/(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])/g, "\\textit{$1}");
    return value.replace(/\u0000B(\d+)\u0000/g, (_, i) => `\\textbf{${bold[+i]}}`);
  }

  function renderTable(lines) {
    const rows = [lines[0], ...lines.slice(2)].map((line, rowIndex) => line.trim().replace(/^\||\|$/g, "").split("|").map(cell => {
      const value = inlineTex(cell.trim());
      return rowIndex === 0 ? `\\textbf{${value}}` : value;
    }));
    const count = rows[0].length;
    const columns = "|X|" + "Y|".repeat(Math.max(0, count - 1));
    return `\\begingroup\\setlength{\\tabcolsep}{4pt}\\renewcommand{\\arraystretch}{1.15}\\small
\\begin{center}\\begin{tabularx}{\\linewidth}{${columns}}\\hline
${rows.map(row => `${Array.from({ length: count }, (_, i) => row[i] || "").join(" & ")} \\\\ \\hline`).join("\n")}
\\end{tabularx}\\end{center}\\endgroup`;
  }

  function renderPipeline(text, accent) {
    const nodes = [...text.matchAll(/\[([^\[\]]+)\]/g)].map(match => match[1].trim());
    const parsed = nodes.length >= 2 ? nodes : text.split(/\s*(?:->|\u2192|=>)\s*/).map(part => part.trim().replace(/^\[|\]$/g, "")).filter(Boolean);
    if (parsed.length < 2) return inlineTex(text);
    const box = node => `\\textcolor{posteraccent}{\\fbox{\\color{posterbody}\\strut\\parbox{0.18\\linewidth}{\\centering\\bfseries ${inlineTex(node)}}}}`;
    return `\\begingroup\\setlength{\\fboxsep}{5pt}\\setlength{\\fboxrule}{0.8pt}
\\begin{center}\\small ${parsed.map((node, i) => `${box(node)}${i < parsed.length - 1 ? `\\,\\textcolor{posteraccent}{$\\rightarrow$}\\,` : ""}`).join("")}\\end{center}\\endgroup`;
  }

  function renderContent(text, accent) {
    const blocks = String(text || "").trim().split(/\n\s*\n/).filter(Boolean);
    return blocks.map(block => {
      const lines = block.split("\n").map(line => line.trim()).filter(Boolean);
      if (lines.length > 1 && lines[0].includes("|") && /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$/.test(lines[1])) return renderTable(lines);
      const flow = lines.length === 1 ? lines[0] : block;
      if (/(?:->|\u2192|=>)/.test(flow) && (flow.includes("[") || lines.length === 1)) return renderPipeline(flow, accent);
      if (lines.every(line => /^[-*\u2022\u2013]\s+/.test(line))) {
        return `\\begin{itemize}\\setlength{\\itemsep}{0.15em}${lines.map(line => `\\item ${inlineTex(line.replace(/^[-*\u2022\u2013]\s+/, ""))}`).join("\n")}\\end{itemize}`;
      }
      return lines.map(line => `\\noindent ${inlineTex(line)}\\par`).join("\n");
    }).join("\\vspace{0.5em}\n");
  }

  function dimensions(data, theme) {
    const sizes = theme.sizes || {};
    const pair = sizes[data.paper] || { cm: ({ a0: [84.1, 118.9], a1: [59.4, 84.1], a2: [42, 59.4], "90x120": [90, 120], "60x90": [60, 90] }[data.paper] || [84.1, 118.9]) };
    const cm = Array.isArray(pair) ? pair : pair.cm || pair;
    const width = Number(cm[0]) || 84.1;
    const height = Number(cm[1]) || 118.9;
    return data.orientation === "landscape" ? [height, width] : [width, height];
  }

  function buildTex(data, theme, imageNames) {
    const template = theme.templates && theme.templates[data.template] || {};
    const colors = data.colors || {};
    const accent = (colors.accent || data.accent || `#${(template.colors || ["1F3A5F"])[0]}`).replace(/^#/, "");
    const background = (colors.bg || template.bg || "FFFFFF").replace(/^#/, "");
    const bodyColor = (colors.body || "1A1A1A").replace(/^#/, "");
    const [width, height] = dimensions(data, theme);
    const points = ({ a0: 25, "90x120": 25, "60x90": 20, a1: 20, a2: 17 })[data.paper] || 25;
    const count = Math.max(1, Math.min(4, Number(data.columns) || 2));
    const margin = Math.max(1.5, Math.min(2.5, width * 0.025));
    const logo = (id, maxWidth) => imageNames.get(id)
      ? `\\includegraphics[height=0.055\\textheight,width=${maxWidth}\\linewidth,keepaspectratio]{${imageNames.get(id)}}` : "";
    const header = (data.logos_header || []).map(id => logo(id, 0.17)).filter(Boolean).join("\\hfill ");
    const footer = (data.logos_footer || []).map(id => logo(id, 0.16)).filter(Boolean).join("\\hfill ");
    const sections = data.sections || [];
    const buckets = Array.from({ length: count }, () => []);
    const perColumn = Math.ceil(sections.length / count);
    sections.forEach((section, index) => buckets[Math.min(count - 1, Math.floor(index / perColumn))].push(section));
    const columnGap = "1.2em";
    const columnWidth = `\\dimexpr(\\linewidth-${count - 1}\\columnsep)/${count}\\relax`;
    const columns = buckets.map(bucket => `\\begin{minipage}[t][0.79\\textheight][s]{${columnWidth}}
${bucket.map((section, sectionIndex) => {
      const title = escapeTex(section.title || section.id || "Section");
      const content = renderContent(section.content || "", `#${accent}`);
      const images = (section.images || []).map(image => imageNames.get(image.path)
        ? `\\par\\begin{center}\\includegraphics[width=0.95\\linewidth,height=0.18\\textheight,keepaspectratio]{${imageNames.get(image.path)}}${image.caption ? `\\\\{\\small\\itshape ${escapeTex(image.caption)}}` : ""}\\end{center}` : "").join("\n");
      return `${sectionIndex ? "\\vfill\n" : ""}\\noindent{\\color{posteraccent}\\rule{\\linewidth}{1.2pt}}\\par
{\\color{posteraccent}\\bfseries\\fontsize{${Math.round(points * 1.25)}pt}{${Math.round(points * 1.5)}pt}\\selectfont ${title}}\\par\\smallskip
{\\color{posterbody}\\fontsize{${points}pt}{${Math.round(points * 1.25)}pt}\\selectfont ${content}${images}}`;
    }).join("\n")}
\\end{minipage}`).join(`\\hspace{${columnGap}}`);
    return `\\documentclass{article}
\\usepackage[paperwidth=${width}cm,paperheight=${height}cm,margin=${margin}cm]{geometry}
\\usepackage{fontspec,xcolor,graphicx,tabularx,array,amsmath,amssymb}
\\newcolumntype{Y}{>{\\centering\\arraybackslash}X}
\\setmainfont{Latin Modern Sans}
\\pagestyle{empty}\\setlength{\\parindent}{0pt}\\setlength{\\parskip}{0.25em}
\\setlength{\\columnsep}{1.2em}
\\definecolor{posteraccent}{HTML}{${accent}}\\definecolor{posterbg}{HTML}{${background}}\\definecolor{posterbody}{HTML}{${bodyColor}}
\\pagecolor{posterbg}
\\begin{document}\\color{posterbody}
\\noindent${header}\\par\\vspace{0.4em}
{\\centering{\\color{posteraccent}\\bfseries\\fontsize{${Math.round(points * 1.8)}pt}{${Math.round(points * 2.1)}pt}\\selectfont ${escapeTex(data.title || "Poster") }\\par}
\\vspace{0.2em}{\\fontsize{${Math.round(points * 1.1)}pt}{${Math.round(points * 1.3)}pt}\\selectfont ${escapeTex(data.authors || "")}\\par}
{\\small ${escapeTex([data.affiliations || "", data.email || ""].filter(Boolean).join(" / "))}\\par}}
\\vspace{0.8em}\\noindent${columns}\\par
\\vfill\\noindent${footer}
\\end{document}`;
  }

  async function compile(input, onStatus) {
    const { module, packageFiles } = await loadCompiler(onStatus);
    const host = makeImports(module);
    const instance = await WebAssembly.instantiate(module, host.imports);
    host.setInstance(instance);
    const wasm = instance.exports;
    const apiVersion = wasm.tectonic_wasm_version();
    if (!Number.isInteger(apiVersion) || apiVersion < 1 || apiVersion > 100) {
      throw new Error(`Versão inválida da API Tectonic WASM: ${apiVersion}.`);
    }
    onStatus("Carregando pacotes LaTeX no compilador WASM...");
    packageFiles.forEach(([name, bytes]) => addFile(instance, name, bytes));

    const imageNames = new Map();
    const imageFiles = new Map();
    const entries = input.files instanceof Map ? input.files : new Map(input.files || []);
    let imageNumber = 0;
    for (const [id, file] of entries) {
      if (!file || !file.type || !file.type.startsWith("image/")) continue;
      const name = `poster-image-${imageNumber++}.png`;
      const bytes = await rasterize(file);
      addFile(instance, name, bytes);
      imageNames.set(id, name);
      imageFiles.set(id, name);
    }

    const data = input.data;
    const theme = input.theme || {};
    const tex = buildTex(data, theme, imageNames);
    onStatus("Compilando o pôster com Tectonic WASM...");
    const texBytes = encoder.encode(tex);
    const texPtr = allocBytes(instance, texBytes);
    try {
      wasm.tectonic_set_input(texPtr, texBytes.length);
      const code = wasm.tectonic_compile();
      if (code !== 0) throw new Error(`Tectonic não conseguiu compilar o documento (código ${code}).`);
    } finally {
      wasm.free(texPtr);
    }
    const outputBufferSize = 8192;
    const outputPtr = wasm.malloc(outputBufferSize);
    if (!outputPtr) throw new Error("Memória insuficiente para localizar o PDF compilado.");
    let outputList = "";
    try {
      const written = wasm.tectonic_list_outputs(outputPtr, outputBufferSize);
      const listLength = Number.isInteger(written) && written > 0 && written < outputBufferSize ? written : outputBufferSize;
      outputList = decoder.decode(new Uint8Array(wasm.memory.buffer, outputPtr, listLength)).replace(/\0+$/g, "").trim();
    } finally {
      wasm.free(outputPtr);
    }
    const outputNames = [...new Set(["poster.pdf", ...outputList.split(/[\r\n]+/), "texput.pdf"].map(name => name.trim()).filter(Boolean))];
    for (const name of outputNames) {
      const nameBytes = encoder.encode(name);
      const namePtr = allocBytes(instance, nameBytes);
      try {
        const size = wasm.tectonic_get_output_size(namePtr, nameBytes.length);
        if (!size) continue;
        const pdfPtr = wasm.malloc(size);
        if (!pdfPtr) throw new Error("Memória insuficiente para recuperar o PDF compilado.");
        try {
          wasm.tectonic_get_output(namePtr, nameBytes.length, pdfPtr, size);
          const bytes = new Uint8Array(wasm.memory.buffer, pdfPtr, size).slice();
          if (bytes[0] === 0x25 && bytes[1] === 0x50 && bytes[2] === 0x44 && bytes[3] === 0x46) {
            return new Blob([bytes], { type: "application/pdf" });
          }
        } finally {
          wasm.free(pdfPtr);
        }
      } finally {
        wasm.free(namePtr);
      }
    }
    throw new Error(`A compilação Tectonic não produziu um PDF. Saídas: ${outputList || "nenhuma"}.`);
  }

  window.compilePosterTectonicWasm = compile;
})();

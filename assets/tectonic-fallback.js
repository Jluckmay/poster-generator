/* Browser fallback compiler built from nl5887/tectonic-wasm (MIT). */
(function () {
  "use strict";

  function resolveTectonicBase() {
    try {
      if (document.currentScript && document.currentScript.src) {
        return new URL("tectonic/", document.currentScript.src);
      }
    } catch (_) {}
    try {
      const el = document.querySelector('script[src*="tectonic-fallback"]');
      if (el && el.src) {
        return new URL("tectonic/", el.src);
      }
    } catch (_) {}
    return new URL("assets/tectonic/", window.location.href);
  }

  const BASE = resolveTectonicBase();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let compilerPromise;

  function readCString(bytes, start, end) {
    let stop = start;
    while (stop < end && bytes[stop] !== 0) stop++;
    return decoder.decode(bytes.subarray(start, stop));
  }

  async function parseTarGzip(gzipBytes) {
    if (typeof DecompressionStream !== "function") {
      throw new Error("Este navegador não oferece descompressão gzip necessária ao compilador local.");
    }
    const stream = new Blob([gzipBytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    const buffer = await new Response(stream).arrayBuffer();
    const tar = new Uint8Array(buffer);
    const files = [];
    for (let offset = 0; offset + 512 <= tar.length;) {
      const header = tar.subarray(offset, offset + 512);
      if (header.every(byte => byte === 0)) break;
      const name = readCString(header, 0, 100);
      const prefix = readCString(header, 345, 500);
      const rawPath = prefix ? `${prefix}/${name}` : name;
      const path = rawPath.replace(/^\.\//, "");
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
          if (fd === 1 || fd === 2) stdout += value;
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
        const wasmUrl = new URL("tectonic_wasm.wasm", BASE);
        const bundleUrl = new URL("tectonic-bundle.tar.gz", BASE);
        const [wasmResponse, bundleResponse] = await Promise.all([
          fetch(wasmUrl),
          fetch(bundleUrl)
        ]);
        if (!wasmResponse.ok) {
          throw new Error(`Falha ao buscar ${wasmUrl.href} (HTTP ${wasmResponse.status})`);
        }
        if (!bundleResponse.ok) {
          throw new Error(`Falha ao buscar ${bundleUrl.href} (HTTP ${bundleResponse.status})`);
        }
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
    if (!file) throw new Error("Arquivo de imagem inválido.");
    const extension = String(file.name || "").split(".").pop().toLowerCase();
    const accepted = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"]);
    if (!(file.type && file.type.startsWith("image/")) && !accepted.has(extension)) {
      throw new Error(`Arquivo de imagem inválido: ${file.name}`);
    }
    const source = file.type && file.type.startsWith("image/") ? file : new Blob([file], { type: extension === "svg" ? "image/svg+xml" : "application/octet-stream" });
    const canvas = document.createElement("canvas");
    try {
      const bitmap = await createImageBitmap(source);
      canvas.width = Math.max(1, bitmap.width);
      canvas.height = Math.max(1, bitmap.height);
      canvas.getContext("2d", { alpha: true }).drawImage(bitmap, 0, 0);
      bitmap.close();
    } catch (_) {
      const url = URL.createObjectURL(source);
      try {
        const image = new Image();
        await new Promise((resolve, reject) => {
          image.onload = resolve;
          image.onerror = () => reject(new Error(`Não foi possível abrir a imagem ${file.name}.`));
          image.src = url;
        });
        canvas.width = Math.max(1, image.naturalWidth);
        canvas.height = Math.max(1, image.naturalHeight);
        canvas.getContext("2d", { alpha: true }).drawImage(image, 0, 0);
      } finally {
        URL.revokeObjectURL(url);
      }
    }
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
    let clean = String(text || "").replace(/\\(?:begin|end)\{tikzpicture\}/gi, "");
    let value = escapeTex(clean).replace(/\*\*(.+?)\*\*/g, (_, part) => {
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
    const columns = "|>{\\raggedright\\arraybackslash}X|" + "Y|".repeat(Math.max(0, count - 1));
    return `\\begingroup\\fontsize{18pt}{24pt}\\selectfont\\setlength{\\tabcolsep}{14pt}\\renewcommand{\\arraystretch}{1.75}
\\arrayrulecolor{tableLine}
\\begin{center}\\begin{tabularx}{\\linewidth}{${columns}}\\hline
\\rowcolor{tableHead}
${rows.map(row => `${Array.from({ length: count }, (_, i) => row[i] || "").join(" & ")} \\\\ \\hline`).join("\n")}
\\end{tabularx}\\end{center}\\endgroup`;
  }

  function renderPipeline(text, accent) {
    if (/\\(?:draw|node|begin|end|path|fill|clip|coordinate)\b/.test(text) || text.trim().startsWith("\\")) {
      return inlineTex(text);
    }
    const nodes = [...text.matchAll(/\[([^\[\]]+)\]/g)].map(match => match[1].trim());
    const parsed = nodes.length >= 2 ? nodes : text.split(/\s*(?:->|\u2192|=>)\s*/).map(part => part.trim().replace(/^\[|\]$/g, "")).filter(Boolean);
    if (parsed.length < 2) return inlineTex(text);
    if (parsed.length === 4) {
      const b = node => `\\fcolorbox{posteraccent}{white}{\\parbox{0.41\\linewidth}{\\centering\\bfseries\\strut ${inlineTex(node)}}}`;
      const arr = `\\,\\textcolor{posteraccent}{$\\rightarrow$}\\,`;
      return `\\begingroup\\setlength{\\fboxsep}{7pt}\\setlength{\\fboxrule}{1.6pt}
\\begin{center}\\fcolorbox{diagFrame}{white}{\\parbox{0.96\\linewidth}{\\vspace{6pt}\\centering
${b(parsed[0])}${arr}${b(parsed[1])}\\par\\vspace{6pt}
${b(parsed[2])}${arr}${b(parsed[3])}
\\vspace{6pt}}}\\end{center}\\endgroup`;
    } else if (parsed.length >= 5) {
      const items = parsed.map((node, i) => {
        const box = `\\centerline{\\fcolorbox{posteraccent}{white}{\\parbox{0.86\\linewidth}{\\centering\\bfseries\\strut ${inlineTex(node)}}}}`;
        const arrow = i < parsed.length - 1 ? `\\vspace{2pt}\\centerline{\\color{posteraccent}{\\Large $\\downarrow$}}\\vspace{2pt}` : "";
        return box + "\n" + arrow;
      }).join("\n");
      return `\\begingroup\\setlength{\\fboxsep}{8pt}\\setlength{\\fboxrule}{1.4pt}
\\begin{center}\\fcolorbox{diagFrame}{white}{\\parbox{0.96\\linewidth}{\\vspace{6pt}
${items}
\\vspace{4pt}}}\\end{center}\\endgroup`;
    } else {
      const box = node => `\\fcolorbox{posteraccent}{white}{\\strut\\parbox{0.24\\linewidth}{\\centering\\bfseries ${inlineTex(node)}}}`;
      return `\\begingroup\\setlength{\\fboxsep}{6pt}\\setlength{\\fboxrule}{1.4pt}
\\begin{center}\\fcolorbox{diagFrame}{white}{\\parbox{0.96\\linewidth}{\\vspace{4pt}\\centering ${parsed.map((node, i) => `${box(node)}${i < parsed.length - 1 ? `\\,\\textcolor{posteraccent}{$\\rightarrow$}\\,` : ""}`).join("")}\\vspace{4pt}}}\\end{center}\\endgroup`;
    }
  }

  function preprocessBlocks(str) {
    const lines = str.trim().split("\n");
    const out = [];
    let inTable = false;
    for (let i = 0; i < lines.length; i++) {
      const ln = lines[i];
      const s = ln.trim();
      const next = lines[i + 1] ? lines[i + 1].trim() : "";
      const isTblStart = !inTable && s.includes("|") && /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$/.test(next);
      if (isTblStart) {
        if (out.length && out[out.length - 1].trim()) out.push("");
        inTable = true;
        out.push(ln);
        continue;
      }
      if (inTable) {
        if (s.includes("|")) {
          out.push(ln);
          continue;
        } else {
          inTable = false;
          if (s) out.push("");
        }
      }
      const isPipeline = !s.startsWith("\\") && !/\\(?:draw|node|begin|end|path|fill|clip|coordinate)\b/.test(s) && /(?:->|\u2192|=>)/.test(s) && (s.includes("[") || s.split(/\s*(?:->|\u2192|=>)\s*/).filter(Boolean).length >= 2);
      if (isPipeline) {
        if (out.length && out[out.length - 1].trim()) out.push("");
        out.push(ln);
        out.push("");
        continue;
      }
      out.push(ln);
    }
    return out.join("\n");
  }

  function renderContent(text, accent) {
    const blocks = preprocessBlocks(String(text || "")).split(/\n\s*\n/).filter(Boolean);
    return blocks.map(block => {
      const lines = block.split("\n").map(line => line.trim()).filter(Boolean);
      if (lines.length > 1 && lines[0].includes("|") && /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$/.test(lines[1])) return renderTable(lines);
      if (/\\begin\{tikzpicture\}/i.test(block)) {
        const nodeMatches = [...block.matchAll(/\\node\b.*?\{([^}]+)\}/gi)];
        if (nodeMatches.length >= 2) {
          const nodes = nodeMatches.map(m => m[1].replace(/\\textbf\{([^}]+)\}/g, "$1").trim());
          return renderPipeline(nodes.map(n => `[${n}]`).join(" -> "), accent);
        }
        return "";
      }
      const flow = lines.length === 1 ? lines[0] : block;
      if (/(?:->|\u2192|=>)/.test(flow) && !flow.startsWith("\\") && !/\\(?:draw|node|begin|end|path|fill|clip|coordinate)\b/.test(flow) && (flow.includes("[") || lines.length === 1)) return renderPipeline(flow, accent);
      if (lines.every(line => /^[-*\u2022\u2013]\s+/.test(line))) {
        return `\\begin{itemize}\\setlength{\\itemsep}{0.15em}${lines.map(line => `\\item ${inlineTex(line.replace(/^[-*\u2022\u2013]\s+/, ""))}`).join("\n")}\\end{itemize}`;
      }
      const cleanLines = lines.filter(line => !/\\(?:begin|end)\{tikzpicture\}/i.test(line) && !/\\(?:draw|node)\b/i.test(line));
      if (cleanLines.length === 0) return "";
      return cleanLines.map(line => `\\noindent ${inlineTex(line)}\\par`).join("\n");
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
    const tplId = data.template || "classic";
    const colors = data.colors || {};
    const accent = (colors.accent || data.accent || `#${(template.colors || ["1F3A5F"])[0]}`).replace(/^#/, "");
    const background = (colors.bg || template.bg || "FFFFFF").replace(/^#/, "");
    const bodyColor = (colors.body || "1A1A1A").replace(/^#/, "");
    const [width, height] = dimensions(data, theme);
    const points = ({ a0: 27, "90x120": 27, "60x90": 22, a1: 22, a2: 18 })[data.paper] || 25;
    const count = Math.max(1, Math.min(4, Number(data.columns) || 2));
    const margin = Math.max(1.8, Math.min(3.0, width * 0.028));
    const logo = (id, maxWidth) => imageNames.get(id)
      ? `\\includegraphics[height=0.065\\textheight,width=${maxWidth}\\linewidth,keepaspectratio]{${imageNames.get(id)}}` : "";

    // Header layout: if uzh, left-aligned title & authors, right-docked logos
    let headerTex = "";
    if (tplId === "uzh") {
      const headerLogos = (data.logos_header || []).map(id => logo(id, 0.45)).filter(Boolean).join(" \\quad ");
      const affilItems = [data.email || "", ...String(data.affiliations || "").split(/\n/).map(s => s.trim())].filter(Boolean);
      const affilText = affilItems.map(escapeTex).join(" \\\\ ");
      headerTex = `\\noindent
\\begin{minipage}[t]{0.62\\linewidth}
  {\\color{posteraccent}\\bfseries\\fontsize{${Math.round(points * 2.1)}pt}{${Math.round(points * 2.4)}pt}\\selectfont ${escapeTex(data.title || "Poster")}\\par\\vspace{0.4em}}
  {\\fontsize{${Math.round(points * 1.25)}pt}{${Math.round(points * 1.5)}pt}\\selectfont \\textbf{${escapeTex(data.authors || "")}}\\par\\vspace{0.3em}}
  {\\fontsize{${Math.round(points * 0.95)}pt}{${Math.round(points * 1.2)}pt}\\selectfont ${affilText}\\par}
\\end{minipage}%
\\hfill
\\begin{minipage}[t]{0.36\\linewidth}
  \\raggedleft
  ${headerLogos}
\\end{minipage}
\\vspace{0.6em}\\par
{\\color{posteraccent}\\rule{\\linewidth}{3.5pt}}\\vspace{0.8em}`;
    } else {
      const isDarkHeader = tplId === "classic" || tplId === "bold" || tplId === "corner" || tplId === "tudelft";
      const logos = (data.logos_header || []).map(id => logo(id, 0.18)).filter(Boolean);
      const affilItems = [data.email || "", ...String(data.affiliations || "").split(/\n/).map(s => s.trim())].filter(Boolean);
      const affilTex = affilItems.map(escapeTex).join(" \\\\ ");
      const subColor = isDarkHeader ? "white" : "posterbody";
      let instLine = "";
      if (logos.length >= 2) {
        instLine = `\\noindent\\begin{minipage}[c]{0.18\\linewidth}\\raggedright ${logos[0]}\\end{minipage}\\hfill\\begin{minipage}[c]{0.60\\linewidth}\\centering{\\color{${subColor}}\\fontsize{${Math.round(points * 0.95)}pt}{${Math.round(points * 1.2)}pt}\\selectfont ${affilTex}}\\end{minipage}\\hfill\\begin{minipage}[c]{0.18\\linewidth}\\raggedleft ${logos[1]}\\end{minipage}`;
      } else if (logos.length === 1) {
        instLine = `\\noindent\\begin{minipage}[c]{0.18\\linewidth}\\raggedright ${logos[0]}\\end{minipage}\\hfill\\begin{minipage}[c]{0.60\\linewidth}\\centering{\\color{${subColor}}\\fontsize{${Math.round(points * 0.95)}pt}{${Math.round(points * 1.2)}pt}\\selectfont ${affilTex}}\\end{minipage}\\hfill\\begin{minipage}[c]{0.18\\linewidth}\\null\\end{minipage}`;
      } else {
        instLine = `{\\centering{\\color{${subColor}}\\fontsize{${Math.round(points * 0.95)}pt}{${Math.round(points * 1.2)}pt}\\selectfont ${affilTex}}\\par}`;
      }
      if (isDarkHeader) {
        headerTex = `\\noindent\\colorbox{posteraccent}{%
  \\parbox{\\dimexpr\\linewidth-2\\fboxsep\\relax}{%
    \\vspace{0.4em}%
    {\\centering{\\color{white}\\bfseries\\fontsize{${Math.round(points * 2.0)}pt}{${Math.round(points * 2.3)}pt}\\selectfont ${escapeTex(data.title || "Poster")}\\par}}%
    \\vspace{0.3em}{\\centering{\\color{white}\\fontsize{${Math.round(points * 1.2)}pt}{${Math.round(points * 1.45)}pt}\\selectfont \\textbf{${escapeTex(data.authors || "")}}\\par}}%
    \\vspace{0.2em}${instLine}%
    \\vspace{0.4em}%
  }%
}\\par\\vspace{0.8em}`;
      } else {
        headerTex = `{\\centering{\\color{posteraccent}\\bfseries\\fontsize{${Math.round(points * 2.0)}pt}{${Math.round(points * 2.3)}pt}\\selectfont ${escapeTex(data.title || "Poster")}\\par}
\\vspace{0.3em}{\\fontsize{${Math.round(points * 1.2)}pt}{${Math.round(points * 1.45)}pt}\\selectfont \\textbf{${escapeTex(data.authors || "")}}\\par}
\\vspace{0.2em}${instLine}\\par}
\\vspace{0.8em}`;
      }
    }

    const footerLogos = (data.logos_footer || []).map(id => logo(id, 0.16)).filter(Boolean);
    let footer = "";
    if (footerLogos.length === 1) {
      footer = `\\vfill\\noindent{\\color{posteraccent}\\rule{\\linewidth}{2.5pt}}\\par\\vspace{0.4em}\\noindent\\hfill ${footerLogos[0]}\\hfill\\null`;
    } else if (footerLogos.length > 1) {
      footer = `\\vfill\\noindent{\\color{posteraccent}\\rule{\\linewidth}{2.5pt}}\\par\\vspace{0.4em}\\noindent ${footerLogos.join("\\hfill ")}`;
    }

    const sections = data.sections || [];
    const buckets = Array.from({ length: count }, () => []);
    if (count === 1) {
      buckets[0] = sections;
    } else if (count === 2) {
      const splitIdx = Math.max(1, Math.min(sections.length - 1, Math.floor(sections.length / 2)));
      buckets[0] = sections.slice(0, splitIdx);
      buckets[1] = sections.slice(splitIdx);
    } else {
      const perColumn = Math.ceil(sections.length / count);
      for (let c = 0; c < count; c++) {
        buckets[c] = sections.slice(c * perColumn, (c + 1) * perColumn);
      }
    }
    const columnGap = "1.2em";
    const columnWidth = `\\dimexpr(\\linewidth-${(count - 1) * 1.2}em)/${count}\\relax`;

    let secCounter = 0;
    const columns = buckets.map(bucket => `\\begin{minipage}[t]{${columnWidth}}
${bucket.map(section => {
      const rawTitle = (section.title || section.id || "Section").trim();
      const cleanTitle = rawTitle.replace(/^\s*\d+[\.\-\)]\s*/, "");
      const isRef = section.id === "references" || /refer[eê]nc/i.test(rawTitle);
      let displayTitle = cleanTitle;
      if ((tplId === "dcc" || tplId === "uzh") && !isRef) {
        secCounter++;
        displayTitle = `${secCounter}. ${cleanTitle}`;
      }
      const content = renderContent(section.content || "", `#${accent}`);
      const validImages = (section.images || []).filter(img => imageNames.get(img.path));
      let images = "";
      if (validImages.length > 0) {
        const rows = [];
        const step = validImages.length === 3 ? 3 : 2;
        for (let i = 0; i < validImages.length; i += step) {
          const row = validImages.slice(i, i + step);
          const w = row.length === 3 ? "0.31" : (row.length === 2 ? "0.48" : "0.85");
          const cells = row.map(img => {
            const fileName = imageNames.get(img.path);
            const cap = img.caption ? `\\\\{\\small\\itshape ${escapeTex(img.caption)}}` : "";
            return `\\begin{minipage}[t]{${w}\\linewidth}\\centering\\includegraphics[width=\\linewidth,height=0.18\\textheight,keepaspectratio]{${fileName}}${cap}\\end{minipage}`;
          });
          rows.push(`\\begin{center}\n${cells.join("\\hfill ")}\n\\end{center}`);
        }
        images = `\\par\\vspace{0.2em}\n${rows.join("\n")}`;
      }

      if (tplId === "uzh") {
        return `\\noindent\\begin{minipage}{\\linewidth}
\\vspace{0.35em}
\\colorbox{cardBg}{%
  \\parbox{\\dimexpr\\linewidth-2\\fboxsep\\relax}{%
    \\vspace{0.35em}%
    \\hbox{%
      \\textcolor{posteraccent}{\\vrule width 5pt}%
      \\hspace{14pt}%
      \\begin{minipage}{\\dimexpr\\linewidth-5pt-28pt\\relax}
        \\vspace{0.15em}%
        {\\color{posteraccent}\\bfseries\\fontsize{${Math.round(points * 1.35)}pt}{${Math.round(points * 1.65)}pt}\\selectfont \\MakeUppercase{${escapeTex(displayTitle)}}}\\par\\vspace{0.35em}
        {\\color{posterbody}\\fontsize{${Math.round(points * 0.98)}pt}{${Math.round(points * 1.35)}pt}\\selectfont
          ${content}
          ${images}
        }\\par\\vspace{0.2em}
      \\end{minipage}%
    }%
    \\vspace{0.35em}%
  }%
}\\vspace{0.8em}
\\end{minipage}`;
      }

      return `\\noindent\\begin{minipage}{\\linewidth}
\\fcolorbox{posteraccent}{white}{\\parbox{\\dimexpr\\linewidth-2\\fboxsep-2\\fboxrule\\relax}{
  \\vspace{0.25em}
  {\\color{posteraccent}\\bfseries\\fontsize{${Math.round(points * 1.3)}pt}{${Math.round(points * 1.55)}pt}\\selectfont \\MakeUppercase{${escapeTex(displayTitle)}}}\\par\\vspace{0.2em}
  {\\color{posteraccent}\\rule{\\linewidth}{1.4pt}}\\par\\vspace{0.35em}
  {\\color{posterbody}\\fontsize{${points}pt}{${Math.round(points * 1.32)}pt}\\selectfont
    ${content}
    ${images}
  }\\par\\vspace{0.2em}
}}\\vspace{0.8em}
\\end{minipage}`;
    }).join("\n")}
\\end{minipage}`).join(`\\hspace{${columnGap}}`);

    return `\\documentclass{article}
\\usepackage[paperwidth=${width}cm,paperheight=${height}cm,margin=${margin}cm]{geometry}
\\usepackage[table]{xcolor}
\\makeatletter\\providecommand\\insert@pcolumn{\\insert@column}\\makeatother
\\usepackage{fontspec,graphicx,tabularx,array}
\\newcolumntype{Y}{>{\\centering\\arraybackslash}X}
\\setmainfont{lmroman10-regular.otf}[BoldFont=lmroman10-bold.otf, ItalicFont=lmroman10-italic.otf, BoldItalicFont=lmroman10-bolditalic.otf]
\\pagestyle{empty}\\setlength{\\parindent}{0pt}\\setlength{\\parskip}{0.25em}
\\setlength{\\columnsep}{1.2em}
\\setlength{\\fboxsep}{10pt}
\\setlength{\\fboxrule}{1.6pt}
\\definecolor{posteraccent}{HTML}{${accent}}\\definecolor{posterbg}{HTML}{${background}}\\definecolor{posterbody}{HTML}{${bodyColor}}
\\definecolor{tableHead}{HTML}{F1F5F9}\\definecolor{tableLine}{HTML}{334155}\\definecolor{diagFrame}{HTML}{CBD5E1}
\\definecolor{cardBg}{HTML}{F8FAFC}
\\pagecolor{posterbg}
\\begin{document}\\color{posterbody}
${headerTex}
\\noindent${columns}\\par
${footer}
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
      if (code !== 0) {
        const log = host.getLog();
        const snippet = log ? log.slice(-350) : "sem logs";
        throw new Error(`Tectonic falhou na compilação (código ${code}): ${snippet}`);
      }
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

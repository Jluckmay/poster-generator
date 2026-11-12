# Tectonic WASM assets

These prebuilt assets are vendored from [nl5887/tectonic-wasm](https://github.com/nl5887/tectonic-wasm), upstream `main` output:

- `tectonic_wasm.wasm` — Tectonic/XeTeX WebAssembly module.
- `tectonic-bundle.tar.gz` — prebundled TeX formats, packages, and fonts used by the offline compiler.

The upstream wrapper and Tectonic are MIT licensed. Files inside the TeX bundle retain their respective upstream licenses. The application loads these local copies only when PDF generation needs the browser fallback.

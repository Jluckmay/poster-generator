"""Script para gerar executável standalone do poster-generator usando PyInstaller."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()


def build() -> None:
    icon_path = ROOT / "assets" / "icons" / "favicon.ico"
    sep = ";" if os.name == "nt" else ":"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        "poster-generator",
        "--onefile",
        "--icon",
        str(icon_path),
        "--add-data",
        f"{ROOT / 'index.html'}{sep}.",
        "--add-data",
        f"{ROOT / 'assets'}{sep}assets",
        "--add-data",
        f"{ROOT / 'examples'}{sep}examples",
        str(ROOT / "desktop.py"),
    ]
    print("Executando compilação do executável...")
    res = subprocess.run(cmd, cwd=str(ROOT))
    if res.returncode == 0:
        exe_ext = ".exe" if os.name == "nt" else ""
        out_file = ROOT / "dist" / f"poster-generator{exe_ext}"
        print(f"\n[OK] Executavel gerado com sucesso em: {out_file}")
    else:
        print(f"\n[ERRO] Falha na compilacao do executavel (codigo {res.returncode}).")
        sys.exit(res.returncode)


if __name__ == "__main__":
    build()

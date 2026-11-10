"""Desktop Launcher for poster-generator (Standalone Executable)."""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Garante que o diretório raiz esteja no sys.path
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE_DIR = Path(sys._MEIPASS).resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from server import app


def _open_browser(port: int) -> None:
    time.sleep(1.2)
    webbrowser.open(f"http://127.0.0.1:{port}")


def main() -> None:
    port = int(os.environ.get("PORT", "5000"))
    threading.Thread(target=_open_browser, args=(port,), daemon=True).start()
    print("=" * 64)
    print("  poster-generator | Academic Poster Compiler")
    print("=" * 64)
    print(f"  [+] Servidor local ativo em: http://127.0.0.1:{port}")
    print("  [+] Abrindo navegador padrao automaticamente...")
    print("  [+] Pressione Ctrl+C nesta janela para encerrar.")
    print("=" * 64)
    try:
        app.run(host="127.0.0.1", port=port, debug=False)
    except KeyboardInterrupt:
        print("\nEncerrando poster-generator. Ate logo!")


if __name__ == "__main__":
    main()


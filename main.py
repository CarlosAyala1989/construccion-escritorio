"""
Punto de Entrada Principal — Plataforma de Gobernanza Documental (Escritorio).
Levanta Eel y expone las funciones del controller a la UI/UX.
"""

import os
import sys

# Add project root to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import eel

# Import controller to register all @eel.expose functions
from src import controller
from src.app_paths import DATA_DIR, WEB_DIR, ensure_runtime_dirs

# ─── Initialize Eel ────────────────────────────────────

def main():
    print("=" * 50)
    print("  Gobernanza Documental — Cliente de Escritorio")
    print("=" * 50)

    ensure_runtime_dirs()
    controller.start_background_sync()

    # Init Eel
    eel.init(WEB_DIR)

    print("[MAIN] Iniciando interfaz gráfica...")
    print(f"[MAIN] Carpeta de datos: {DATA_DIR}")
    print(f"[MAIN] Carpeta de vigilancia: {os.path.join(DATA_DIR, 'watch_folder')}")
    print(f"[MAIN] Carpeta temporal: {os.path.join(DATA_DIR, 'temp_workspace')}")

    # Try Chrome/Chromium first, fall back to default browser
    try:
        try:
            eel.start(
                "index.html",
                size=(1100, 750),
                mode="chrome",
                port=8765,
                shutdown_delay=5.0,
            )
        except EnvironmentError:
            print("[MAIN] Chrome no disponible, usando navegador predeterminado...")
            try:
                eel.start(
                    "index.html",
                    size=(1100, 750),
                    mode="default",
                    port=8765,
                    shutdown_delay=5.0,
                )
            except Exception as e:
                print(f"[MAIN] Error al iniciar la UI: {e}")
                print("[MAIN] Abriendo en modo sin interfaz...")
                eel.start(
                    "index.html",
                    mode=None,
                    port=8765,
                    shutdown_delay=5.0,
                    block=False,
                )
                print("[MAIN] Servidor disponible en http://localhost:8765/index.html")
                try:
                    while True:
                        eel.sleep(1.0)
                except KeyboardInterrupt:
                    print("\n[MAIN] Cerrando aplicación...")
    finally:
        controller.stop_background_sync()


if __name__ == "__main__":
    main()

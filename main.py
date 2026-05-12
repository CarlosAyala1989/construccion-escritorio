"""
Punto de Entrada Principal — Plataforma de Gobernanza Documental (Escritorio).
Levanta Eel y expone las funciones del controller a la UI.
"""

import os
import sys

# Add project root to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import eel

# Import controller to register all @eel.expose functions
import src.controller  # noqa: F401

# ─── Initialize Eel ────────────────────────────────────
WEB_DIR = os.path.join(BASE_DIR, "web")

def main():
    print("=" * 50)
    print("  Gobernanza Documental — Cliente de Escritorio")
    print("=" * 50)

    # Check essential directories
    data_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(os.path.join(data_dir, "temp_workspace"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "watch_folder"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "processed"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "cloud_output"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "templates"), exist_ok=True)

    # Init Eel
    eel.init(WEB_DIR)

    print("[MAIN] Iniciando interfaz gráfica...")
    print(f"[MAIN] Carpeta de vigilancia: {os.path.join(data_dir, 'watch_folder')}")
    print(f"[MAIN] Carpeta temporal: {os.path.join(data_dir, 'temp_workspace')}")

    # Try Chrome/Chromium first, fall back to default browser
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


if __name__ == "__main__":
    main()

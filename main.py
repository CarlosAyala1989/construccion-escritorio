"""
Punto de Entrada Principal — Plataforma de Gobernanza Documental (Escritorio).
Levanta Eel y expone las funciones del controller a la UI/UX.
"""

import os
import sys
import logging

EEL_PORT = 8765
EEL_WINDOW_SIZE = (1100, 750)
EEL_SHUTDOWN_DELAY_SECONDS = 5.0
EEL_LOOP_INTERVAL_SECONDS = 1.0
APP_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Agrega la raíz del proyecto a la ruta de búsqueda.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import eel

# Importa el controlador para registrar todas las funciones @eel.expose.
from src import controller
from src.app_paths import DATA_DIR, WEB_DIR, ensure_runtime_dirs

LOGGER = logging.getLogger(__name__)

# ─── Inicialización de Eel ────────────────────────────

# RF-13/RF-17 — Inicializa la interfaz y el ciclo de sincronización del escritorio.
def main():
    logging.basicConfig(level=logging.INFO, format=APP_LOG_FORMAT)
    LOGGER.info("Iniciando Gobernanza Documental — Cliente de Escritorio")

    ensure_runtime_dirs()
    controller.start_background_sync()

    # Inicializa Eel.
    eel.init(WEB_DIR)

    LOGGER.info("Iniciando interfaz gráfica.")
    LOGGER.info("Carpeta de datos: %s", DATA_DIR)
    LOGGER.info("Carpeta de vigilancia: %s", os.path.join(DATA_DIR, "watch_folder"))
    LOGGER.info("Carpeta temporal: %s", os.path.join(DATA_DIR, "temp_workspace"))

    # Intenta usar Chrome/Chromium y, si no está disponible, usa el navegador predeterminado.
    try:
        try:
            eel.start(
                "index.html",
                size=EEL_WINDOW_SIZE,
                mode="chrome",
                port=EEL_PORT,
                shutdown_delay=EEL_SHUTDOWN_DELAY_SECONDS,
            )
        except EnvironmentError:
            LOGGER.info("Chrome no está disponible; se usará el navegador predeterminado.")
            try:
                eel.start(
                    "index.html",
                    size=EEL_WINDOW_SIZE,
                    mode="default",
                    port=EEL_PORT,
                    shutdown_delay=EEL_SHUTDOWN_DELAY_SECONDS,
                )
            except Exception:
                LOGGER.exception("No se pudo iniciar la interfaz gráfica; se usará modo sin interfaz.")
                eel.start(
                    "index.html",
                    mode=None,
                    port=EEL_PORT,
                    shutdown_delay=EEL_SHUTDOWN_DELAY_SECONDS,
                    block=False,
                )
                LOGGER.info("Servidor disponible en http://localhost:%s/index.html", EEL_PORT)
                try:
                    while True:
                        eel.sleep(EEL_LOOP_INTERVAL_SECONDS)
                except KeyboardInterrupt:
                    LOGGER.info("Cerrando aplicación.")
    finally:
        controller.stop_background_sync()


if __name__ == "__main__":
    main()

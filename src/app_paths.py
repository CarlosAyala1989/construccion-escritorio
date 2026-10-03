"""
Rutas compartidas del sistema de archivos para desarrollo y versiones empaquetadas.

PyInstaller extrae los archivos incluidos a un directorio temporal durante la ejecución.
Los datos como SQLite, las colas, los escaneos y los archivos procesados deben guardarse
en una ubicación estable donde el usuario pueda escribir.
"""

import os
import sys

APP_NAME = "GobernanzaDocumental"


def is_frozen():
    return getattr(sys, "frozen", False)


def resource_dir():
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def user_data_dir():
    configured = os.getenv("GOBERNANZA_DATA_DIR")
    if configured:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(configured)))

    if not is_frozen():
        return os.path.join(resource_dir(), "data")

    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, APP_NAME)

    base = os.getenv("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_NAME)


BASE_DIR = resource_dir()
DATA_DIR = user_data_dir()
WEB_DIR = os.path.join(BASE_DIR, "web")
TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")
TEMP_WORKSPACE_DIR = os.path.join(DATA_DIR, "temp_workspace")
WATCH_DIR = os.path.join(DATA_DIR, "watch_folder")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
PENDING_REVIEW_DIR = os.path.join(DATA_DIR, "pending_review")
CLOUD_OUTPUT_DIR = os.path.join(DATA_DIR, "cloud_output")


def ensure_runtime_dirs():
    for path in [
        DATA_DIR,
        TEMPLATES_DIR,
        TEMP_WORKSPACE_DIR,
        WATCH_DIR,
        PROCESSED_DIR,
        PENDING_REVIEW_DIR,
        CLOUD_OUTPUT_DIR,
    ]:
        os.makedirs(path, exist_ok=True)

"""
Rutas compartidas del sistema de archivos para desarrollo y versiones empaquetadas.

PyInstaller extrae los archivos incluidos a un directorio temporal durante la ejecución.
Los datos como SQLite, las colas, los escaneos y los archivos procesados deben guardarse
en una ubicación estable donde el usuario pueda escribir.
"""

import os
import sys

APP_NAME = "GobernanzaDocumental"


# Comprueba frozen dentro de app paths.
def esta_empaquetada():
    return getattr(sys, "frozen", False)


# Resuelve el directorio de recursos tanto en desarrollo como en PyInstaller.
def directorio_recursos():
    if esta_empaquetada():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Resuelve la carpeta persistente de datos del usuario.
def directorio_datos_usuario():
    configured = os.getenv("GOBERNANZA_DATA_DIR")
    if configured:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(configured)))

    if not esta_empaquetada():
        return os.path.join(directorio_recursos(), "data")

    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, APP_NAME)

    base = os.getenv("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_NAME)


BASE_DIR = directorio_recursos()
DATA_DIR = directorio_datos_usuario()
WEB_DIR = os.path.join(BASE_DIR, "web")
TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")
TEMP_WORKSPACE_DIR = os.path.join(DATA_DIR, "temp_workspace")
WATCH_DIR = os.path.join(DATA_DIR, "watch_folder")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
PENDING_REVIEW_DIR = os.path.join(DATA_DIR, "pending_review")
CLOUD_OUTPUT_DIR = os.path.join(DATA_DIR, "cloud_output")


# Garantiza runtime dirs dentro de app paths.
def asegurar_directorios_ejecucion():
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

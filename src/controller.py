"""
Controller — Funciones expuestas a la UI vía Eel (@eel.expose).
Orquesta: autenticación, sesiones, procesamiento de documentos, y sincronización.
Patrón Observer: emite eventos a la UI durante el procesamiento.
"""

import os
import eel
import logging
import threading
import json
import shutil
import tempfile

from src.database.sqlite_manager import AuthenticationError, DatabaseManager
from src.core.ocr_engine import OCREngine
from src.core.vision_engine import VisionEngine
from src.core.crypto_engine import CryptoEngine
from src.core.file_structurer import FileStructurer
from src.core.pending_tray import PendingTray
from src.core.secure_file_writer import SECURE_FILE_MAGIC, SecureFileWriter
from src.core.native_file_dialog import select_document_files
from src.hardware.scanner import ScannerManager
from src.sync.cloud_uploader import CloudUploader, DEFAULT_COMPRESSION_THRESHOLD_MB
from src.app_paths import PROCESSED_DIR, PENDING_REVIEW_DIR, ensure_runtime_dirs
from src.capture_context import (
    CaptureContextError,
    DesktopSessionContext,
    find_assigned_workspace,
    require_active_capture_context,
    validate_selected_workspace,
)

LOGGER = logging.getLogger(__name__)
SYNC_INTERVAL_ENV = "GOBERNANZA_SYNC_INTERVAL_SECONDS"
MIN_SYNC_INTERVAL_SECONDS = 5
DEFAULT_SYNC_INTERVAL_SECONDS = 15

# ─── Servicios / contexto de ejecución ────────────────
db = DatabaseManager()
ocr = OCREngine()
vision = VisionEngine()
crypto = CryptoEngine()
scanner = ScannerManager()
capture_context = DesktopSessionContext()

ensure_runtime_dirs()
OUTPUT_DIR = PROCESSED_DIR
PENDING_DIR = PENDING_REVIEW_DIR


# RF-13 — Valida el intervalo de sincronización y usa un valor seguro de respaldo.
def _configured_sync_interval():
    try:
        configured_value = int(os.getenv(SYNC_INTERVAL_ENV, DEFAULT_SYNC_INTERVAL_SECONDS))
        return max(MIN_SYNC_INTERVAL_SECONDS, configured_value)
    except (TypeError, ValueError):
        LOGGER.warning("El intervalo de sincronización no es válido; se usará el valor predeterminado.")
        return DEFAULT_SYNC_INTERVAL_SECONDS


SYNC_INTERVAL_SECONDS = _configured_sync_interval()
_sync_thread = None
_sync_stop_event = threading.Event()
_sync_wakeup_event = threading.Event()
_sync_lock = threading.Lock()


# RF-13/RF-17 — Inicia una sola vez la sincronización automática de documentos y logs.
def start_background_sync():
    global _sync_thread
    if _sync_thread and _sync_thread.is_alive():
        return

    _sync_stop_event.clear()
    _sync_thread = threading.Thread(
        target=_background_sync_loop,
        name="docuzen-background-sync",
        daemon=True,
    )
    _sync_thread.start()


# RF-13/RF-17 — Solicita detener el sincronizador y desbloquea su espera actual.
def stop_background_sync():
    """Solicita una detención ordenada sin bloquear el cierre de la aplicación."""
    _sync_stop_event.set()
    _sync_wakeup_event.set()


# RF-13 — Despierta el sincronizador después de encolar trabajo nuevo.
def _request_background_sync():
    _sync_wakeup_event.set()


# RF-13/RF-17 — Reintenta documentos y bitácoras en segundo plano cuando hay conexión.
def _background_sync_loop():
    """Sube documentos protegidos y bitácoras cifradas al restablecerse la conexión."""
    was_online = False
    while not _sync_stop_event.is_set():
        online = db.is_online()
        if online:
            try:
                result = _sync_offline_backlog()
                if not was_online or result["documents"] or result["logs"]:
                    LOGGER.info(
                        "Sincronización automática: %s documento(s), %s log(s).",
                        result["documents"],
                        result["logs"],
                    )
            except Exception as error:
                LOGGER.exception("La sincronización automática queda pendiente: %s", error)

        was_online = online
        _sync_wakeup_event.wait(SYNC_INTERVAL_SECONDS)
        _sync_wakeup_event.clear()


# RF-03 — Devuelve un error uniforme si falta el contexto requerido para capturar.
def _capture_guard_failure():
    try:
        require_active_capture_context(db, capture_context)
        return None
    except CaptureContextError as error:
        return {"success": False, "error": str(error)}


# ─── Autenticación ────────────────────────────────────

# RF-03 — Valida al operador antes de establecer el contexto local de captura.
@eel.expose
def login(email, password, totp_code=""):
    """Autentica a un usuario de escritorio con contraseña y TOTP en MySQL."""
    try:
        user = db.authenticate_user(email, password, totp_code)
        capture_context.set_user(user)
        db.create_audit_log(
            user["id"], user["name"], "LOGIN",
            "Inicio de sesión desde escritorio", "SUCCESS"
        )
        return {"success": True, "user": user}
    except AuthenticationError as error:
        return {"success": False, "error": str(error)}
    except Exception as error:
        LOGGER.exception("Falló el inicio de sesión del cliente de escritorio.")
        return {"success": False, "error": f"Error de conexión: {str(error)}"}


# RF-03 — Cierra el contexto local y conserva trazabilidad de la sesión.
@eel.expose
def logout():
    """Cierra la sesión del usuario y siempre limpia el contexto local de captura."""
    if capture_context.session_id and scanner.is_paused and scanner.memory_queue:
        return {
            "success": False,
            "error": (
                "Reanuda la captura antes de cerrar sesión; hay archivos detectados "
                "durante la pausa que todavía deben cifrarse."
            ),
        }

    if capture_context.session_id:
        try:
            scanner.stop_watching()
            db.close_session(capture_context.session_id)
        except Exception as error:
            LOGGER.exception("Falló el cierre de sesión de captura: %s", error)

    if capture_context.user:
        db.create_audit_log(
            capture_context.user["id"], capture_context.user["name"], "LOGOUT",
            "Cierre de sesión", "SUCCESS"
        )

    capture_context.reset()
    return {"success": True}


@eel.expose
def get_current_user():
    """Devuelve el usuario que inició sesión actualmente."""
    return capture_context.user


# ─── Espacios de trabajo ──────────────────────────────

@eel.expose
def get_workspaces():
    """Devuelve los espacios de trabajo asignados al usuario actual."""
    if not capture_context.user:
        return []
    return db.get_user_workspaces(capture_context.user["id"])


# RF-03 — Valida permisos y bloqueos antes de cambiar el espacio seleccionado.
@eel.expose
def select_workspace(workspace_id, _workspace_name=None):
    """Selecciona un espacio asignado; no permite cambiarlo durante el escaneo."""
    if not workspace_id:
        return {"success": False, "error": "Debes seleccionar un espacio de trabajo válido."}

    try:
        assigned_workspace = find_assigned_workspace(db, capture_context, workspace_id)
        if not assigned_workspace:
            return {"success": False, "error": "Espacio de trabajo no encontrado o sin permisos vigentes."}

        capture_context.set_workspace(assigned_workspace)
        return {"success": True, "workspace": assigned_workspace}
    except CaptureContextError as error:
        return {"success": False, "error": str(error)}


# ─── Sesiones ─────────────────────────────────────────

# RF-03 — Inicia una sesión solo con espacio validado y revierte fallos de inicio.
@eel.expose
def start_session():
    """Inicia una sesión de escaneo solo tras volver a validar el espacio seleccionado."""
    if capture_context.has_active_session:
        return {"success": False, "error": "Ya existe una sesión de escaneo activa."}

    try:
        workspace = validate_selected_workspace(db, capture_context)
    except CaptureContextError as error:
        return {"success": False, "error": str(error)}

    try:
        session_id = db.create_session(
            capture_context.user["id"],
            workspace["id"],
            workspace["name"]
        )
        capture_context.start_session(session_id)

        scanner.on_file_callback = _on_file_detected
        scanner.start_watching()

        db.create_audit_log(
            capture_context.user["id"], capture_context.user["name"], "SESSION_STARTED",
            f"Sesión iniciada en espacio: {workspace['name']}",
            "SUCCESS", workspace["id"]
        )

        return {
            "success": True,
            "session_id": capture_context.session_id,
            "watch_folder": scanner.watch_folder,
        }
    except Exception as error:
        session_id = capture_context.session_id
        capture_context.end_session()
        if session_id:
            try:
                scanner.stop_watching()
                db.close_session(session_id)
            except Exception as cleanup_error:
                LOGGER.exception("Falló la reversión del inicio de sesión: %s", cleanup_error)

        LOGGER.exception("No se pudo iniciar la sesión de captura: %s", error)
        return {"success": False, "error": "No se pudo iniciar la sesión de escaneo."}


# RF-03 — Cierra la sesión de captura y reporta el resultado de su lote.
@eel.expose
def end_session():
    """Finaliza la sesión actual e inicia la sincronización en la nube."""
    if not capture_context.session_id:
        return {"success": False, "error": "No hay sesión activa."}
    if scanner.is_paused and scanner.memory_queue:
        return {
            "success": False,
            "error": (
                "Hay archivos detectados durante la pausa. Resuelve el fallo y "
                "reanuda la captura antes de cerrar para no dejarlos sin encolar."
            ),
        }

    session_id = capture_context.session_id
    workspace = capture_context.workspace

    scanner.stop_watching()
    db.close_session(session_id)

    # Procesa y sube todos los documentos pendientes.
    result = _process_all_pending()

    db.create_audit_log(
        capture_context.user["id"], capture_context.user["name"], "SESSION_ENDED",
        f"Sesión cerrada. Docs procesados: {result['processed']}, Errores: {result['errors']}",
        "SUCCESS" if result["errors"] == 0 else "FAILURE",
        workspace["id"] if workspace else None
    )

    # Sincroniza las bitácoras pendientes.
    synced = db.sync_pending_logs()

    capture_context.end_session()
    return {
        "success": True,
        "processed": result["processed"],
        "errors": result["errors"],
        "uploaded": result["uploaded"],
        "logs_synced": synced,
    }


# ─── Gestión de archivos ──────────────────────────────

# RF-04 — Importa archivos solo en una sesión y conserva rutas cifradas.
@eel.expose
def import_files(file_paths):
    """Importa archivos manualmente solo si el contexto de captura RF-03 es válido."""
    guard_failure = _capture_guard_failure()
    if guard_failure:
        return guard_failure

    imported = scanner.import_files(file_paths)
    for path in imported:
        _on_file_detected(path)

    return {"success": True, "count": len(imported)}


@eel.expose
def get_scanners():
    """Enumera los escáneres físicos disponibles."""
    return scanner.get_scanners()


# RF-04/RF-05 — Inicia escaneo condicionado por sesión y reporta fallos mecánicos.
@eel.expose
def scan_document(device_id=None):
    """Inicia el escaneo físico solo si el contexto de captura RF-03 es válido."""
    guard_failure = _capture_guard_failure()
    if guard_failure:
        return guard_failure

    try:
        path = scanner.scan_physical_document(device_id)
        if path:
            _on_file_detected(path)
            return {"success": True, "path": path}
        if not scanner.is_paused:
            scanner.pause_capture("El escáner no devolvió un folio válido.")
        db.create_audit_log(
            capture_context.user["id"],
            capture_context.user["name"],
            "CAPTURE_PAUSED",
            scanner.pause_reason or "Fallo del escáner.",
            "FAILURE",
            capture_context.workspace["id"],
        )
        return {
            "success": False,
            "error": "Fallo al escanear. Verifica que el escáner esté encendido y sin atascos.",
            "paused": scanner.is_paused,
            "pause_reason": scanner.pause_reason,
        }
    except Exception as error:
        LOGGER.exception("Falló la captura física del documento.")
        return {
            "success": False,
            "error": str(error),
            "paused": scanner.is_paused,
            "pause_reason": scanner.pause_reason,
        }


# RF-05 — Reanuda la captura y devuelve el estado del procesamiento de la cola.
@eel.expose
def resume_capture():
    """Reanuda una sesión pausada por un atasco o fallo mecánico del escáner."""
    guard_failure = _capture_guard_failure()
    if guard_failure:
        return guard_failure

    try:
        result = scanner.resume_capture()
        db.create_audit_log(
            capture_context.user["id"],
            capture_context.user["name"],
            "CAPTURE_RESUMED",
            f"Captura reanudada. Folios recuperados: {result['processed']}",
            "SUCCESS",
            capture_context.workspace["id"],
        )
        return {"success": not result["paused"], **result}
    except Exception as error:
        LOGGER.exception("Falló la reanudación de captura.")
        return {"success": False, "error": str(error), "paused": scanner.is_paused}


# RF-04 — Abre el selector nativo e importa archivos a la sesión cifrada.
@eel.expose
def pick_and_import_files():
    """Abre un selector nativo de archivos solo si el contexto de captura RF-03 es válido."""
    guard_failure = _capture_guard_failure()
    if guard_failure:
        return guard_failure

    try:
        files = select_document_files()

        if not files:
            return {"success": True, "count": 0, "message": "No se seleccionaron archivos."}

        imported = scanner.import_files(files)
        for path in imported:
            _on_file_detected(path)

        return {"success": True, "count": len(imported)}
    except Exception as error:
        LOGGER.exception("Falló la selección o importación de archivos.")
        return {"success": False, "error": f"Error al seleccionar archivos: {str(error)}"}


@eel.expose
def export_files():
    """Exporta los archivos procesados a un directorio elegido por el usuario."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        dest_dir = filedialog.askdirectory(
            title="Seleccionar carpeta de destino para exportar"
        )
        root.destroy()

        if not dest_dir:
            return {"success": True, "count": 0, "message": "No se seleccionó carpeta."}

        import shutil
        exported = 0
        for f in os.listdir(OUTPUT_DIR):
            src = os.path.join(OUTPUT_DIR, f)
            if os.path.isfile(src):
                dest = os.path.join(dest_dir, f)
                shutil.copy2(src, dest)
                exported += 1

        return {"success": True, "count": exported, "destination": dest_dir}
    except Exception as e:
        LOGGER.exception("Falló la exportación de archivos.")
        return {"success": False, "error": f"Error al exportar: {str(e)}"}


@eel.expose
def get_session_files():
    """Devuelve los archivos del espacio temporal actual."""
    return scanner.get_temp_files()


# RF-08 — Devuelve documentos pendientes de revisión manual.
@eel.expose
def get_pending_review():
    """Devuelve los documentos que requieren revisión manual."""
    return db.get_pending_review()


@eel.expose
def get_queue_items():
    """Devuelve todos los elementos de la cola de procesamiento."""
    return db.get_queue_items()


# RF-11 — Reevalúa el documento corregido antes de cambiar su estado de cola.
@eel.expose
def correct_document(doc_id, new_name):
    """
    Corrige manualmente el nombre de un documento pendiente de revisión.
    Vuelve a activar la protección de privacidad después de la corrección.
    """
    if not capture_context.user:
        return {"success": False, "error": "No autenticado."}

    item = db.get_queue_item(doc_id)
    if not item or item.get("status") != "PENDING_REVIEW":
        return {"success": False, "error": "Documento no encontrado."}

    old_path = item["file_path"]
    if not os.path.exists(old_path):
        return {"success": False, "error": "Archivo no encontrado en disco."}

    corrected_name = _normalize_corrected_pdf_name(new_name)
    if not corrected_name:
        return {
            "success": False,
            "error": "Ingresa un nombre PDF válido sin carpetas ni caracteres reservados.",
        }

    assigned_workspaces = db.get_user_workspaces(capture_context.user["id"])
    if not any(workspace.get("id") == item.get("workspace_id") for workspace in assigned_workspaces):
        return {"success": False, "error": "Ya no tienes acceso al espacio de este documento."}

    # RF-11: el nombre corregido solo afecta al archivo de salida. El folio original
    # cifrado se vuelve a leer y siempre pasa por OCR, visión y cifrado.
    result = _process_single_document(
        old_path,
        item["workspace_id"],
        corrected_name=corrected_name,
    )
    if result["success"]:
        db.update_queue_item(
            doc_id,
            status="PROCESSED",
            file_path=result["output_path"],
            original_name=corrected_name,
            encryption_type=result["encryption"]["type"],
            policy_id=result["encryption"].get("policy_id"),
            error_message=None,
        )
        try:
            os.remove(old_path)
        except OSError:
            LOGGER.warning("No se pudo retirar el folio reemplazado %s.", old_path, exc_info=True)
        _request_background_sync()
        return {"success": True, "result": result}

    db.update_queue_item(
        doc_id,
        status="PENDING_REVIEW",
        error_message=result.get("error", "Fallo en re-evaluación"),
    )
    return {"success": False, "error": result.get("error", "Fallo en re-evaluación")}


# ─── Estado / información ─────────────────────────────

@eel.expose
def get_app_status():
    """Devuelve el estado general de la aplicación."""
    online = db.is_online()
    return {
        "online": online,
        "user": capture_context.user,
        "workspace": capture_context.workspace,
        "session_active": capture_context.has_active_session,
        "session_id": capture_context.session_id,
        "watch_folder": scanner.watch_folder,
        "temp_folder": scanner.temp_folder,
        "capture_paused": scanner.is_paused,
        "pause_reason": scanner.pause_reason,
        "paused_files": len(scanner.memory_queue),
        "offline_documents": len(db.get_queue_items(status="PROCESSED")),
    }


# RF-13/RF-17 — Fuerza un ciclo de sincronización y devuelve sus conteos.
@eel.expose
def sync_now():
    """Inicia manualmente la misma sincronización de documentos y bitácoras que RF-13."""
    result = _sync_offline_backlog()
    return {"synced": result["logs"], "documents": result["documents"]}


@eel.expose
def get_config():
    """Devuelve la configuración del sistema."""
    return db.get_config()


# ─── Procesamiento interno ────────────────────────────

# RF-03/RF-04/RF-12 — Encola el folio únicamente dentro del contexto de captura vigente.
def _on_file_detected(file_path):
    """Encola un archivo detectado solo mientras el contexto de captura RF-03 siga válido."""
    guard_failure = _capture_guard_failure()
    if guard_failure:
        LOGGER.warning(
            "Archivo ignorado fuera del contexto de captura: %s",
            guard_failure["error"],
        )
        return

    workspace = capture_context.workspace

    # Añade el archivo a la cola.
    doc_id = db.add_to_queue(
        file_path,
        os.path.basename(file_path),
        workspace["id"],
        workspace["name"]
    )

    db.increment_session_doc_count(capture_context.session_id)

    # Notifica a la interfaz sin ocultar fallos de los observadores.
    try:
        eel.onFileDetected({
            "id": doc_id,
            "name": os.path.basename(file_path),
            "path": file_path,
        })
    except Exception as error:
        LOGGER.warning("No se pudo notificar a la interfaz del archivo detectado: %s", error)


# RF-04/RF-06/RF-07/RF-08/RF-09/RF-10/RF-15 — Procesa metadatos, seguridad y protección documental.
def _process_single_document(file_path, workspace_id=None, corrected_name=None):
    """Procesa un documento con OCR, visión, compresión opcional y cifrado."""
    workspace = db.get_workspace(workspace_id) if workspace_id else capture_context.workspace
    if not workspace:
        return {"success": False, "error": "No hay espacio de trabajo disponible."}

    all_policies = db.get_security_policies()
    policies = [
        policy for policy in all_policies
        if not policy.get("workspaceId") or policy.get("workspaceId") == workspace.get("id")
    ]
    config = db.get_config()
    nomenclatures = db.get_nomenclatures()
    source_extension = os.path.splitext(file_path)[1].lower()
    clear_path = None
    converted_pdf_path = None
    compressed_pdf_path = None
    output_path = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=source_extension or ".bin",
            prefix="docuzen-processing-",
            delete=False,
        ) as clear_file:
            clear_path = clear_file.name
            with open(file_path, "rb") as source_file:
                magic = source_file.read(len(SECURE_FILE_MAGIC))

            if magic == SECURE_FILE_MAGIC:
                clear_file.write(SecureFileWriter.read_secure(file_path))
            else:
                # Compatibilidad con colas creadas antes de RF-04.
                with open(file_path, "rb") as source_file:
                    shutil.copyfileobj(source_file, clear_file)

        text = ""
        if source_extension == ".pdf":
            text = ocr.extract_text_from_pdf(clear_path)
            processing_pdf_path = clear_path
        elif source_extension in [".png", ".jpg", ".jpeg", ".tiff", ".bmp"]:
            text = ocr.extract_text_from_image(clear_path)
            converted_pdf_path = _convert_image_to_temporary_pdf(clear_path)
            processing_pdf_path = converted_pdf_path
        else:
            return {
                "success": False,
                "error": "El formato del documento no es compatible.",
                "needs_review": True,
            }

        # RF-06/RF-07: los metadatos extraídos por OCR determinan las carpetas y el nombre.
        nomenclature_data = ocr.extract_nomenclature(text, nomenclatures)
        title_hierarchy = ocr.extract_title_hierarchy(text)
        structured_path = None
        if corrected_name:
            structured_path = os.path.join(OUTPUT_DIR, corrected_name)
        elif title_hierarchy:
            structured_path = FileStructurer.structure_title_hierarchy(
                title_hierarchy,
                OUTPUT_DIR,
            )
        elif nomenclature_data:
            separator = nomenclatures[0].get("separator", "_") if nomenclatures else "_"
            structured_path = FileStructurer.RenameAndStructure(
                nomenclature_data,
                OUTPUT_DIR,
                separator,
            )

        if nomenclatures and not structured_path:
            return {
                "success": False,
                "error": "La IA no pudo extraer la nomenclatura del documento.",
                "needs_review": True,
            }

        # RF-10: CryptoEngine siempre prioriza VISUAL, luego SEMANTIC y DEFAULT.
        semantic_policy = ocr.check_semantic_policies(text, policies)
        visual_policy = vision.check_document(clear_path, policies)
        encryption_result = crypto.resolve_password(workspace, semantic_policy, visual_policy)
        if not encryption_result["password"]:
            return {
                "success": False,
                "error": "El espacio no tiene una contraseña de protección disponible.",
                "needs_review": True,
            }

        # RF-15: la compresión debe ocurrir antes de proteger con contraseña. Un PDF
        # protegido no puede modificarse después sin volver a abrirlo explícitamente.
        compressed = False
        source_for_encryption = processing_pdf_path
        compression = CloudUploader(config)
        if config.get("compressionEnabled"):
            threshold = config.get(
                "compressionThresholdMb",
                DEFAULT_COMPRESSION_THRESHOLD_MB,
            )
            if compression.should_compress(processing_pdf_path, threshold):
                with tempfile.NamedTemporaryFile(
                    suffix=".pdf",
                    prefix="docuzen-compressed-",
                    delete=False,
                ) as compressed_file:
                    compressed_pdf_path = compressed_file.name
                if compression.compress_pdf(processing_pdf_path, compressed_pdf_path):
                    source_for_encryption = compressed_pdf_path
                    compressed = True

        if structured_path:
            output_path = structured_path
        else:
            output_name = os.path.splitext(os.path.basename(file_path))[0] + ".pdf"
            output_path = os.path.join(OUTPUT_DIR, output_name)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        output_path = crypto._prevent_collision(output_path)
        encrypted = crypto.encrypt_pdf(
            source_for_encryption,
            output_path,
            encryption_result["password"],
        )
        if not encrypted:
            if output_path and os.path.exists(output_path):
                os.remove(output_path)
            return {
                "success": False,
                "error": "No se pudo aplicar el cifrado obligatorio al PDF.",
                "needs_review": True,
            }

        try:
            eel.onDocumentProcessed({
                "name": os.path.basename(output_path),
                "encryption": encryption_result["type"],
                "source": encryption_result["source"],
                "compressed": compressed,
            })
        except Exception:
            LOGGER.debug("La interfaz no recibió la notificación de procesamiento.", exc_info=True)

        return {
            "success": True,
            "output_path": output_path,
            "encryption": encryption_result,
            "compressed": compressed,
            "filename": os.path.basename(output_path),
        }
    except Exception as error:
        LOGGER.exception("Falló el procesamiento del documento %s.", file_path)
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                LOGGER.warning("No se pudo retirar el resultado incompleto %s.", output_path, exc_info=True)
        return {
            "success": False,
            "error": f"No se pudo procesar el documento: {error}",
            "needs_review": True,
        }
    finally:
        for temporary_path in [compressed_pdf_path, converted_pdf_path, clear_path]:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    LOGGER.warning(
                        "No se pudo retirar el archivo temporal %s.",
                        temporary_path,
                        exc_info=True,
                    )


# RF-06 — Convierte imágenes a PDF temporal para continuar el procesamiento OCR.
def _convert_image_to_temporary_pdf(image_path):
    """Convierte una imagen importada a PDF antes del cifrado obligatorio del documento."""
    from PIL import Image

    with tempfile.NamedTemporaryFile(
        suffix=".pdf",
        prefix="docuzen-image-",
        delete=False,
    ) as pdf_file:
        output_path = pdf_file.name

    try:
        with Image.open(image_path) as source_image:
            source_image.convert("RGB").save(output_path, "PDF")
        return output_path
    except Exception:
        try:
            os.remove(output_path)
        except OSError:
            LOGGER.warning("No se pudo retirar el PDF temporal convertido %s.", output_path, exc_info=True)
        raise


def _normalize_corrected_pdf_name(new_name):
    """Acepta solo un nombre base de PDF seguro desde la interfaz de corrección manual."""
    candidate = str(new_name or "").strip()
    if not candidate or candidate != os.path.basename(candidate):
        return None
    if any(character in candidate for character in '<>:"/\\|?*'):
        return None
    if candidate in {".", ".."}:
        return None
    if not candidate.lower().endswith(".pdf"):
        candidate += ".pdf"
    return candidate


# RF-12/RF-13 — Procesa la cola protegida y sube los documentos sin perder reintentos.
def _process_all_pending():

    config = db.get_config()
    google_creds = db.get_google_credentials()
    # Combina las credenciales de Google con la configuración del cargador.
    merged_config = {**config, **google_creds}
    active_uploader = CloudUploader(merged_config)

    pending = db.get_queue_items(status="PENDING")
    processed = 0
    errors = 0
    uploaded = 0

    for item in pending:
        try:
            # Notifica el progreso.
            try:
                eel.onProcessingProgress({
                    "current": processed + errors + 1,
                    "total": len(pending),
                    "name": item["original_name"],
                })
            except Exception:
                LOGGER.debug("La interfaz no está disponible para recibir el progreso.", exc_info=True)

            result = _process_single_document(item["file_path"], item["workspace_id"])

            if result.get("success"):
                # RF-12: la salida protegida se convierte en el contenido persistente
                # para reintentos antes de intentar cualquier operación de red.
                db.update_queue_item(
                    item["id"],
                    status="PROCESSED",
                    file_path=result["output_path"],
                    encryption_type=result["encryption"]["type"],
                    policy_id=result["encryption"].get("policy_id"),
                    error_message=None,
                )
                processed_item = db.get_queue_item(item["id"])
                with _sync_lock:
                    upload_result = _upload_processed_item(processed_item, active_uploader, config)

                if upload_result.get("success"):
                    uploaded += 1
                    LOGGER.info(
                        "Documento subido: %s → %s",
                        item["original_name"],
                        upload_result.get("provider", "N/A"),
                    )
                else:
                    LOGGER.warning(
                        "Documento procesado pero aún no subido: %s — %s",
                        item["original_name"],
                        upload_result.get("error", ""),
                    )

                # La copia cifrada de captura deja de ser necesaria cuando el PDF
                # protegido queda guardado de forma persistente en la cola de reintentos.
                if item["file_path"] != result["output_path"]:
                    try:
                        os.remove(item["file_path"])
                    except OSError:
                        LOGGER.warning(
                            "No se pudo retirar el folio temporal %s.",
                            item["file_path"],
                            exc_info=True,
                        )

                db.create_audit_log(
                    capture_context.user["id"] if capture_context.user else None,
                    capture_context.user["name"] if capture_context.user else "Sistema",
                    "DOCUMENT_PROCESSED",
                    json.dumps({
                        "file": item["original_name"],
                        "encryption": result["encryption"]["type"],
                        "compressed": result.get("compressed", False),
                        "uploaded": upload_result.get("success", False),
                        "provider": upload_result.get("provider", "NONE"),
                        "sha256": upload_result.get("sha256"),
                    }),
                    "SUCCESS",
                    item.get("workspace_id")
                )
                processed += 1

            elif result.get("needs_review"):
                pending_path = item["file_path"]
                if not os.path.abspath(pending_path).startswith(os.path.abspath(PENDING_DIR) + os.sep):
                    moved_path = PendingTray.HandleOCRFailure(item["file_path"], PENDING_DIR)
                    if moved_path:
                        pending_path = moved_path
                db.update_queue_item(
                    item["id"],
                    status="PENDING_REVIEW",
                    file_path=pending_path,
                    error_message=result.get("error", "Revisión manual requerida")
                )
                errors += 1
            else:
                db.update_queue_item(
                    item["id"],
                    status="ERROR",
                    error_message=result.get("error", "Error desconocido")
                )
                errors += 1

        except Exception as e:
            LOGGER.exception("Falló el procesamiento del elemento de cola %s.", item.get("id"))
            db.update_queue_item(item["id"], status="ERROR", error_message=str(e))
            errors += 1

    _remove_empty_capture_directories()

    return {"processed": processed, "errors": errors, "uploaded": uploaded}


# RF-12/RF-13 — Reintenta la subida desde la copia protegida y conserva errores para reintento.
def _upload_processed_item(item, active_uploader, config):
    """Sube un elemento ya protegido de la cola sin volver a procesar datos sin cifrar."""
    if not item or item.get("status") != "PROCESSED":
        return {"success": False, "error": "Elemento de cola no disponible.", "provider": "NONE"}

    protected_path = item.get("file_path")
    if not protected_path or not os.path.exists(protected_path):
        db.update_queue_item(
            item["id"],
            status="ERROR",
            error_message="El PDF protegido pendiente ya no existe en disco.",
        )
        return {"success": False, "error": "Archivo protegido no encontrado.", "provider": "NONE"}

    workspace = db.get_workspace(item.get("workspace_id"))
    if not workspace:
        db.update_queue_item(
            item["id"],
            error_message="No se encontró el espacio de trabajo para sincronizar.",
        )
        return {"success": False, "error": "Espacio de trabajo no encontrado.", "provider": "NONE"}

    upload_result = active_uploader.upload(
        protected_path,
        workspace.get("cloudPath", ""),
        item.get("workspace_name") or workspace.get("name") or "default",
        workspace=workspace,
    )

    if upload_result.get("success"):
        db.update_queue_item(item["id"], status="UPLOADED", error_message=None)
        if config.get("deleteLocalAfterUpload"):
            try:
                os.remove(protected_path)
            except OSError:
                LOGGER.warning("No se pudo borrar el PDF local ya subido %s.", protected_path, exc_info=True)
    else:
        db.update_queue_item(
            item["id"],
            status="PROCESSED",
            error_message=upload_result.get("error", "Subida pendiente por falta de conexión."),
        )

    return upload_result


# RF-13/RF-17 — Sincroniza la cola de documentos y las bitácoras en un pase protegido.
def _sync_offline_backlog():
    if not db.is_online():
        return {"documents": 0, "logs": 0}

    if not _sync_lock.acquire(blocking=False):
        return {"documents": 0, "logs": 0}

    try:
        config = db.get_config()
        merged_config = {**config, **db.get_google_credentials()}
        active_uploader = CloudUploader(merged_config)
        uploaded = 0

        for item in db.get_queue_items(status="PROCESSED"):
            result = _upload_processed_item(item, active_uploader, config)
            if not result.get("success"):
                continue

            uploaded += 1
            db.create_audit_log(
                None,
                "Sincronización automática",
                "DOCUMENT_UPLOADED_AUTOMATICALLY",
                json.dumps({
                    "file": item.get("original_name"),
                    "destination": result.get("destination"),
                    "provider": result.get("provider", "NONE"),
                    "sha256": result.get("sha256"),
                }),
                "SUCCESS",
                item.get("workspace_id"),
            )

        logs_synced = db.sync_pending_logs()
        return {"documents": uploaded, "logs": logs_synced}
    finally:
        _sync_lock.release()


def _remove_empty_capture_directories():
    """Elimina solo directorios temporales vacíos; los folios cifrados con errores se conservan."""
    temp_root = scanner.temp_folder
    root_directory = os.path.dirname(temp_root) if os.path.basename(temp_root).startswith("session_") else temp_root
    if not os.path.isdir(root_directory):
        return

    for entry_name in os.listdir(root_directory):
        entry_path = os.path.join(root_directory, entry_name)
        if not os.path.isdir(entry_path):
            continue
        try:
            os.rmdir(entry_path)
        except OSError as error:
            LOGGER.debug("El directorio %s sigue ocupado o no pudo eliminarse: %s", entry_path, error)

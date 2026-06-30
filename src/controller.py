"""
Controller — Funciones expuestas a la UI vía Eel (@eel.expose).
Orquesta: autenticación, sesiones, procesamiento de documentos, y sincronización.
Patrón Observer: emite eventos a la UI durante el procesamiento.
"""

import os
import eel
import uuid
import threading
import json
from datetime import datetime

from src.database.sqlite_manager import AuthenticationError, DatabaseManager
from src.core.ocr_engine import OCREngine
from src.core.vision_engine import VisionEngine
from src.core.crypto_engine import CryptoEngine
from src.core.file_structurer import FileStructurer
from src.core.pending_tray import PendingTray
from src.core.secure_file_writer import SecureFileWriter
from src.hardware.scanner import ScannerManager
from src.sync.cloud_uploader import CloudUploader
from src.app_paths import PROCESSED_DIR, PENDING_REVIEW_DIR, ensure_runtime_dirs

# ─── Global State ──────────────────────────────────────
db = DatabaseManager()
ocr = OCREngine()
vision = VisionEngine()
crypto = CryptoEngine()
scanner = ScannerManager()
uploader = None  # Initialized after config load

current_user = None
current_workspace = None
current_session_id = None

ensure_runtime_dirs()
OUTPUT_DIR = PROCESSED_DIR
PENDING_DIR = PENDING_REVIEW_DIR


# ─── Authentication ────────────────────────────────────

@eel.expose
def login(email, password, totp_code=""):
    """Authenticate a desktop user with password and TOTP against MySQL."""
    global current_user
    try:
        user = db.authenticate_user(email, password, totp_code)
        current_user = user
        db.create_audit_log(
            user["id"], user["name"], "LOGIN",
            "Inicio de sesión desde escritorio", "SUCCESS"
        )
        return {"success": True, "user": user}
    except AuthenticationError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Error de conexión: {str(e)}"}


@eel.expose
def logout():
    """Log out current user."""
    global current_user, current_workspace, current_session_id

    # Stop active session if any
    if current_session_id:
        try:
            scanner.stop_watching()
            db.close_session(current_session_id)
        except Exception:
            pass

    if current_user:
        db.create_audit_log(
            current_user["id"], current_user["name"], "LOGOUT",
            "Cierre de sesión", "SUCCESS"
        )
    current_user = None
    current_workspace = None
    current_session_id = None
    return {"success": True}


@eel.expose
def get_current_user():
    """Get the current logged-in user."""
    return current_user


# ─── Workspaces ────────────────────────────────────────

@eel.expose
def get_workspaces():
    """Get workspaces assigned to the current user."""
    if not current_user:
        return []
    return db.get_user_workspaces(current_user["id"])


@eel.expose
def select_workspace(workspace_id, workspace_name):
    """Select a workspace for the current session."""
    global current_workspace
    workspaces = get_workspaces()
    for ws in workspaces:
        if ws["id"] == workspace_id:
            current_workspace = ws
            return {"success": True, "workspace": ws}
    return {"success": False, "error": "Espacio de trabajo no encontrado."}


# ─── Sessions ─────────────────────────────────────────

@eel.expose
def start_session():
    """Start a new scanning session. Requires workspace selection."""
    global current_session_id
    if not current_user:
        return {"success": False, "error": "Debes iniciar sesión primero."}
    if not current_workspace:
        return {"success": False, "error": "Debes seleccionar un espacio de trabajo primero."}

    current_session_id = db.create_session(
        current_user["id"],
        current_workspace["id"],
        current_workspace["name"]
    )

    # Start folder watcher
    scanner.on_file_callback = _on_file_detected
    scanner.start_watching()

    db.create_audit_log(
        current_user["id"], current_user["name"], "SESSION_STARTED",
        f"Sesión iniciada en espacio: {current_workspace['name']}",
        "SUCCESS", current_workspace["id"]
    )

    return {
        "success": True,
        "session_id": current_session_id,
        "watch_folder": scanner.watch_folder,
    }


@eel.expose
def end_session():
    """End the current session and trigger cloud sync."""
    global current_session_id
    if not current_session_id:
        return {"success": False, "error": "No hay sesión activa."}

    scanner.stop_watching()
    db.close_session(current_session_id)

    # Process and upload all pending documents
    result = _process_all_pending()

    db.create_audit_log(
        current_user["id"], current_user["name"], "SESSION_ENDED",
        f"Sesión cerrada. Docs procesados: {result['processed']}, Errores: {result['errors']}",
        "SUCCESS" if result["errors"] == 0 else "FAILURE",
        current_workspace["id"] if current_workspace else None
    )

    # Sync pending logs
    synced = db.sync_pending_logs()

    current_session_id = None
    return {
        "success": True,
        "processed": result["processed"],
        "errors": result["errors"],
        "uploaded": result["uploaded"],
        "logs_synced": synced,
    }


# ─── File Management ──────────────────────────────────

@eel.expose
def import_files(file_paths):
    """Import files manually into the session."""
    if not current_session_id:
        return {"success": False, "error": "Inicia una sesión primero."}

    imported = scanner.import_files(file_paths)
    for path in imported:
        _on_file_detected(path)

    return {"success": True, "count": len(imported)}


@eel.expose
def get_scanners():
    """List available physical scanners."""
    return scanner.get_scanners()

@eel.expose
def scan_document(device_id=None):
    """Trigger physical scan from a connected scanner."""
    if not current_session_id:
        return {"success": False, "error": "Inicia una sesión primero."}

    try:
        path = scanner.scan_physical_document(device_id)
        if path:
            _on_file_detected(path)
            return {"success": True, "path": path}
        else:
            return {"success": False, "error": "Fallo al escanear. Verifica que el escáner esté encendido y sin atascos."}
    except Exception as e:
        return {"success": False, "error": str(e)}

@eel.expose
def pick_and_import_files():
    """Open a native file dialog to select files and import them."""
    if not current_session_id:
        return {"success": False, "error": "Inicia una sesión primero."}

    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        files = filedialog.askopenfilenames(
            title="Seleccionar archivos para importar",
            filetypes=[
                ("Documentos", "*.pdf *.png *.jpg *.jpeg *.tiff *.bmp"),
                ("PDF", "*.pdf"),
                ("Imágenes", "*.png *.jpg *.jpeg *.tiff *.bmp"),
                ("Todos", "*.*"),
            ]
        )
        root.destroy()

        if not files:
            return {"success": True, "count": 0, "message": "No se seleccionaron archivos."}

        imported = scanner.import_files(list(files))
        for path in imported:
            _on_file_detected(path)

        return {"success": True, "count": len(imported)}
    except Exception as e:
        return {"success": False, "error": f"Error al seleccionar archivos: {str(e)}"}


@eel.expose
def export_files():
    """Export processed files to a user-chosen directory."""
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
        return {"success": False, "error": f"Error al exportar: {str(e)}"}


@eel.expose
def get_session_files():
    """Get files in the current temp workspace."""
    return scanner.get_temp_files()


@eel.expose
def get_pending_review():
    """Get documents that need manual review."""
    return db.get_pending_review()


@eel.expose
def get_queue_items():
    """Get all items in the processing queue."""
    return db.get_queue_items()


@eel.expose
def correct_document(doc_id, new_name):
    """
    Manually correct a document name (from pending review).
    Re-triggers the privacy shield after correction.
    """
    if not current_user:
        return {"success": False, "error": "No autenticado."}

    items = db.get_queue_items()
    item = None
    for i in items:
        if i["id"] == doc_id:
            item = i
            break

    if not item:
        return {"success": False, "error": "Documento no encontrado."}

    # Rename the file
    old_path = item["file_path"]
    if os.path.exists(old_path):
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        try:
            os.rename(old_path, new_path)
        except OSError as e:
            return {"success": False, "error": f"Error al renombrar: {str(e)}"}

        # Re-evaluate through privacy shield (mandatory)
        result = _process_single_document(new_path, item["workspace_id"])
        if result["success"]:
            db.update_queue_item(doc_id, status="PROCESSED", file_path=new_path)
            return {"success": True, "result": result}
        else:
            db.update_queue_item(doc_id, status="PENDING_REVIEW", error_message=result.get("error", ""))
            return {"success": False, "error": result.get("error", "Fallo en re-evaluación")}

    return {"success": False, "error": "Archivo no encontrado en disco."}


# ─── Status / Info ─────────────────────────────────────

@eel.expose
def get_app_status():
    """Get overall application status."""
    online = db.is_online()
    return {
        "online": online,
        "user": current_user,
        "workspace": current_workspace,
        "session_active": current_session_id is not None,
        "session_id": current_session_id,
        "watch_folder": scanner.watch_folder,
        "temp_folder": scanner.temp_folder,
    }


@eel.expose
def sync_now():
    """Manually trigger sync of pending logs."""
    synced = db.sync_pending_logs()
    return {"synced": synced}


@eel.expose
def get_config():
    """Get system configuration."""
    return db.get_config()


# ─── Internal Processing ──────────────────────────────

def _on_file_detected(file_path):
    """Callback when a new file is detected."""
    if not current_workspace:
        return

    # Add to queue
    doc_id = db.add_to_queue(
        file_path,
        os.path.basename(file_path),
        current_workspace["id"],
        current_workspace["name"]
    )

    if current_session_id:
        db.increment_session_doc_count(current_session_id)

    # Notify UI
    try:
        eel.onFileDetected({
            "id": doc_id,
            "name": os.path.basename(file_path),
            "path": file_path,
        })
    except Exception:
        pass


def _process_single_document(file_path, workspace_id=None):
    """Process a single document through the full pipeline."""
    workspace = current_workspace
    if workspace_id and workspace and workspace["id"] != workspace_id:
        # Find the correct workspace
        workspaces = get_workspaces()
        for ws in workspaces:
            if ws["id"] == workspace_id:
                workspace = ws
                break

    if not workspace:
        return {"success": False, "error": "No hay espacio de trabajo seleccionado."}

    all_policies = db.get_security_policies()
    policies = [
        policy for policy in all_policies
        if not policy.get("workspaceId") or policy.get("workspaceId") == workspace.get("id")
    ]
    config = db.get_config()
    nomenclatures = db.get_nomenclatures()

    # ─── Phase 2: OCR & Classification ─────────────
    # El archivo en temp_workspace está cifrado con AES-256. Lo desciframos temporalmente para procesamiento.
    temp_clear_path = file_path + ".clear"
    try:
        clear_bytes = SecureFileWriter.read_secure(file_path)
        with open(temp_clear_path, "wb") as f:
            f.write(clear_bytes)
    except Exception as e:
        # Fallback for manually added or old cleartext files
        import shutil
        shutil.copy2(file_path, temp_clear_path)

    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    if ext == ".pdf":
        text = ocr.extract_text_from_pdf(temp_clear_path)
    elif ext in [".png", ".jpg", ".jpeg", ".tiff", ".bmp"]:
        text = ocr.extract_text_from_image(temp_clear_path)

    # Try nomenclature extraction
    nomenclature_data = ocr.extract_nomenclature(text, nomenclatures)
    title_hierarchy = ocr.extract_title_hierarchy(text)
    structured_path = None
    if title_hierarchy:
        structured_path = FileStructurer.structure_title_hierarchy(
            title_hierarchy,
            OUTPUT_DIR,
        )
    elif nomenclature_data:
        sep = nomenclatures[0].get("separator", "_") if nomenclatures else "_"
        # Get the structured path (doesn't create the file, just the path)
        structured_path = FileStructurer.RenameAndStructure(nomenclature_data, OUTPUT_DIR, sep)

    # If nomenclature failed and we have nomenclature rules, mark for review
    if nomenclatures and not structured_path:
        # CP-031: HandleOCRFailure() mueve doc a PENDIENTES
        # Borramos el temporal en claro
        try:
            os.remove(temp_clear_path)
        except OSError:
            pass
        pending_path = PendingTray.HandleOCRFailure(file_path, PENDING_DIR)
        return {
            "success": False,
            "error": "La IA no pudo extraer la nomenclatura del documento.",
            "needs_review": True,
            "pending_path": pending_path
        }

    # ─── Phase 3: Privacy Shield ───────────────────
    semantic_policy = ocr.check_semantic_policies(text, policies)
    visual_policy = vision.check_document(temp_clear_path, policies)

    # Resolve encryption password (hierarchical)
    encryption_result = crypto.resolve_password(workspace, semantic_policy, visual_policy)

    # Determine output filename
    if structured_path:
        output_path = structured_path
    else:
        output_name = os.path.basename(file_path)
        output_path = os.path.join(OUTPUT_DIR, output_name)
        
    output_path = crypto._prevent_collision(output_path)

    # Encrypt if password available
    if encryption_result["password"]:
        success = crypto.encrypt_pdf(temp_clear_path, output_path, encryption_result["password"])
        if not success:
            import shutil
            shutil.copy2(temp_clear_path, output_path)
    else:
        import shutil
        shutil.copy2(temp_clear_path, output_path)
        
    # Limpiar archivo en claro temporal
    try:
        os.remove(temp_clear_path)
    except OSError:
        pass

    # ─── Phase 4: Compression (if enabled) ─────────
    compressed = False
    if config.get("compressionEnabled") and ext == ".pdf":
        threshold = config.get("compressionThresholdMb", 10)
        if uploader and uploader.should_compress(output_path, threshold):
            compressed_path = output_path + ".compressed"
            if uploader.compress_pdf(output_path, compressed_path):
                os.replace(compressed_path, output_path)
                compressed = True

    # Notify UI
    try:
        eel.onDocumentProcessed({
            "name": os.path.basename(output_path),
            "encryption": encryption_result["type"],
            "source": encryption_result["source"],
            "compressed": compressed,
        })
    except Exception:
        pass

    return {
        "success": True,
        "output_path": output_path,
        "encryption": encryption_result,
        "compressed": compressed,
        "filename": os.path.basename(output_path),
    }


def _process_all_pending():
    """Process all pending documents and upload to cloud."""
    global uploader

    config = db.get_config()
    google_creds = db.get_google_credentials()
    # Merge google creds into config for the uploader
    merged_config = {**config, **google_creds}
    uploader = CloudUploader(merged_config)

    pending = db.get_queue_items(status="PENDING")
    processed = 0
    errors = 0
    uploaded = 0

    for item in pending:
        try:
            # Notify progress
            try:
                eel.onProcessingProgress({
                    "current": processed + errors + 1,
                    "total": len(pending),
                    "name": item["original_name"],
                })
            except Exception:
                pass

            result = _process_single_document(item["file_path"], item["workspace_id"])

            if result.get("success"):
                # Upload to cloud — pass full workspace data for Drive credentials
                ws_name = item.get("workspace_name", "default")
                cloud_path = current_workspace.get("cloudPath", "") if current_workspace else ""
                upload_result = uploader.upload(
                    result["output_path"],
                    cloud_path,
                    ws_name,
                    workspace=current_workspace,
                )

                if upload_result.get("success"):
                    db.update_queue_item(item["id"], status="UPLOADED")
                    uploaded += 1
                    print(f"[PROCESS] ✅ Subido: {item['original_name']} → {upload_result.get('provider', 'N/A')}")

                    # Delete local if configured
                    if config.get("deleteLocalAfterUpload"):
                        try:
                            os.remove(result["output_path"])
                        except OSError:
                            pass
                else:
                    db.update_queue_item(item["id"], status="PROCESSED")
                    print(f"[PROCESS] ⚠️ Procesado pero no subido: {item['original_name']} — {upload_result.get('error', '')}")

                db.create_audit_log(
                    current_user["id"] if current_user else None,
                    current_user["name"] if current_user else "Sistema",
                    "DOCUMENT_PROCESSED",
                    json.dumps({
                        "file": item["original_name"],
                        "encryption": result["encryption"]["type"],
                        "compressed": result.get("compressed", False),
                        "uploaded": upload_result.get("success", False),
                        "provider": upload_result.get("provider", "NONE"),
                    }),
                    "SUCCESS",
                    item.get("workspace_id")
                )
                processed += 1

            elif result.get("needs_review"):
                db.update_queue_item(
                    item["id"],
                    status="PENDING_REVIEW",
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
            db.update_queue_item(item["id"], status="ERROR", error_message=str(e))
            errors += 1

    # Clean temp workspace
    scanner.clear_temp()

    return {"processed": processed, "errors": errors, "uploaded": uploaded}

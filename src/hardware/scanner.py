"""
Scanner / File Watcher — Captura e Ingesta de Datos.
Fase 1: vigilancia de carpetas y captura física con almacenamiento temporal cifrado.
"""

from io import BytesIO
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid

from src.app_paths import DATA_DIR, TEMP_WORKSPACE_DIR, WATCH_DIR, ensure_runtime_dirs
from src.core.secure_file_writer import SecureFileWriter

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

ensure_runtime_dirs()
TEMP_ROOT_DIR = TEMP_WORKSPACE_DIR
SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}
SCAN_RESOLUTION_DPI = 300
SESSION_DIRECTORY_PREFIX = "session_"
FILE_WRITE_SETTLE_SECONDS = 1
OBSERVER_JOIN_TIMEOUT_SECONDS = 2
SCANNER_RETRY_DELAY_SECONDS = 2
FIRST_DEVICE_INDEX = 1
SCANNER_DEVICE_TYPE = 1
FIRST_WIA_ITEM_INDEX = 1
PROCESS_SUCCESS_RETURN_CODE = 0
SCAN_IMAGE_FORMAT_ID = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"
SCAN_FILENAME_ID_LENGTH = 8
WIA_COLOR_MODE = 1
WIA_FILE_FORMAT_PDF = 4


class PDFHandler(FileSystemEventHandler):
    """Observa la carpeta de entrada y deriva los documentos terminados al escáner."""

    def __init__(self, callback):
        self.callback = callback

    # RF-04 — Filtra formatos compatibles y espera a que termine la escritura fuente.
    def on_created(self, event):
        if event.is_directory:
            return

        extension = os.path.splitext(event.src_path)[1].lower()
        if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
            return

        # El evento puede dispararse antes de que la aplicación origen termine de escribir.
        time.sleep(FILE_WRITE_SETTLE_SECONDS)
        if os.path.exists(event.src_path):
            self.callback(event.src_path)


class ScannerManager:
    """Gestiona ingesta y captura física dentro de un contexto temporal cifrado."""

    def __init__(self, on_file_callback=None):
        self._observer = None
        self._running = False
        self._capture_storage_active = False
        self._secure_session_id = None
        self._session_temp_dir = None
        self.is_paused = False
        self.pause_reason = None
        self.memory_queue = []
        self.on_file_callback = on_file_callback

    # RF-04 — Inicia la captura cifrada y devuelve si el monitoreo quedó activo.
    def start_watching(self):
        """Inicia la sesión de ingesta y crea su directorio temporal cifrado."""
        if self._running:
            return True

        self._begin_secure_capture_storage()
        self.is_paused = False
        self.pause_reason = None
        self.memory_queue = []
        self._ingest_existing_watch_files()

        if not HAS_WATCHDOG:
            logging.getLogger(__name__).warning(
                "watchdog no está disponible; el monitoreo de carpeta queda deshabilitado."
            )
            return False

        handler = PDFHandler(self._on_new_file)
        self._observer = Observer()
        self._observer.schedule(handler, WATCH_DIR, recursive=False)
        self._observer.daemon = True
        self._observer.start()
        self._running = True
        logging.getLogger(__name__).info("Monitoreando la carpeta de captura: %s", WATCH_DIR)
        logging.getLogger(__name__).debug(
            "Directorio temporal cifrado de la sesión: %s",
            self._session_temp_dir,
        )
        return True

    def _ingest_existing_watch_files(self):
        """Recupera archivos compatibles que quedaron en la carpeta vigilada tras una interrupción."""
        for file_name in sorted(os.listdir(WATCH_DIR)):
            file_path = os.path.join(WATCH_DIR, file_name)
            if not os.path.isfile(file_path):
                continue
            if os.path.splitext(file_name)[1].lower() not in SUPPORTED_DOCUMENT_EXTENSIONS:
                continue
            if not self._process_file_internal(file_path, remove_source=True):
                break

    # RF-04 — Detiene el watcher y conserva el lote cifrado para su procesamiento.
    def stop_watching(self):
        """Detiene la captura; conserva los folios cifrados para el procesamiento posterior."""
        if self._observer and self._running:
            self._observer.stop()
            self._observer.join(timeout=OBSERVER_JOIN_TIMEOUT_SECONDS)
            self._observer = None
            self._running = False
            logging.getLogger(__name__).info("Se detuvo el monitoreo de la carpeta.")

        if self._capture_storage_active:
            SecureFileWriter.deactivate_session(self._secure_session_id)
            self._capture_storage_active = False

    # RF-05 — Pausa la ingesta sin borrar folios y devuelve su estado al llamador.
    def pause_capture(self, reason=None):
        """Pausa la ingesta sin eliminar los folios ya capturados y cifrados."""
        self.is_paused = True
        self.pause_reason = str(reason or "Atasco o fallo mecánico del escáner.")
        logging.getLogger(__name__).warning("Captura pausada: %s", self.pause_reason)
        return {
            "paused": True,
            "reason": self.pause_reason,
            "queued": len(self.memory_queue),
        }

    # RF-05 — Reanuda la ingesta, procesa pendientes y devuelve el estado del lote.
    def resume_capture(self):
        """Reanuda la ingesta y procesa de forma segura los archivos detectados durante la pausa."""
        if not self._capture_storage_active:
            raise RuntimeError("No existe una sesión de captura activa para reanudar.")

        queued_paths = list(self.memory_queue)
        self.memory_queue = []
        self.is_paused = False
        self.pause_reason = None

        processed = 0
        for index, file_path in enumerate(queued_paths):
            if not os.path.exists(file_path):
                continue
            try:
                try:
                    remove_source = os.path.commonpath(
                        [os.path.abspath(WATCH_DIR), os.path.abspath(file_path)]
                    ) == os.path.abspath(WATCH_DIR)
                except ValueError:
                    remove_source = False
                encrypted_path = self._process_file_internal(
                    file_path,
                    remove_source=remove_source,
                )
                if not encrypted_path:
                    self.memory_queue.extend(queued_paths[index + 1:])
                    break
                processed += 1
            except Exception as error:
                self.pause_capture(error)
                if file_path not in self.memory_queue:
                    self.memory_queue.append(file_path)
                self.memory_queue.extend(queued_paths[index + 1:])
                break

        logging.getLogger(__name__).info(
            "Captura reanudada; archivos recuperados: %s",
            processed,
        )
        return {
            "paused": self.is_paused,
            "processed": processed,
            "queued": len(self.memory_queue),
            "reason": self.pause_reason,
        }

    # RF-04 — Crea una sesión aislada y activa el almacenamiento temporal cifrado.
    def _begin_secure_capture_storage(self):
        """Crea un directorio aislado y activa una clave AES-256 para la sesión de captura."""
        if self._capture_storage_active and self._session_temp_dir:
            return self._session_temp_dir

        secure_session_id = uuid.uuid4().hex
        session_temp_dir = os.path.join(
            TEMP_ROOT_DIR,
            f"{SESSION_DIRECTORY_PREFIX}{secure_session_id}",
        )

        os.makedirs(session_temp_dir, mode=0o700, exist_ok=False)
        try:
            SecureFileWriter.begin_session(secure_session_id)
        except Exception:
            try:
                shutil.rmtree(session_temp_dir)
            except OSError:
                logging.getLogger(__name__).warning(
                    "No se pudo retirar el temporal de una sesión fallida %s.",
                    session_temp_dir,
                    exc_info=True,
                )
            raise

        self._secure_session_id = secure_session_id
        self._session_temp_dir = session_temp_dir
        self._capture_storage_active = True
        return session_temp_dir

    # RF-04 — Falla temprano si no hay un directorio cifrado de captura activo.
    def _require_session_temp_dir(self):
        if not self._capture_storage_active or not self._session_temp_dir:
            raise RuntimeError(
                "No existe un directorio temporal cifrado activo. Inicia una sesión de captura primero."
            )
        return self._session_temp_dir

    def _secure_destination(self, source_name):
        session_temp_dir = self._require_session_temp_dir()
        destination = os.path.join(session_temp_dir, os.path.basename(source_name))
        return self._prevent_collision(destination)

    # RF-04 — Persiste el archivo fuente cifrado dentro de la sesión activa.
    def _secure_source_file(self, source_path):
        destination = self._secure_destination(source_path)
        SecureFileWriter.write_secure(source_path, destination)
        return destination

    # RF-04/RF-05 — Encola durante pausas o procesa el archivo detectado.
    def _on_new_file(self, file_path):
        """Procesa un documento detectado por el watcher."""
        if self.is_paused:
            self.memory_queue.append(file_path)
            logging.getLogger(__name__).debug(
                "Archivo en cola durante la pausa: %s",
                os.path.basename(file_path),
            )
            return

        self._process_file_internal(file_path, remove_source=True)

    # RF-04/RF-05 — Cifra el origen y pausa/reencola si el procesamiento falla.
    def _process_file_internal(self, file_path, remove_source=False):
        logging.getLogger(__name__).debug("Nuevo archivo detectado: %s", os.path.basename(file_path))

        try:
            encrypted_path = self._secure_source_file(file_path)
            if remove_source:
                try:
                    os.remove(file_path)
                except OSError as error:
                    logging.getLogger(__name__).warning(
                        "No se pudo retirar el original de la carpeta vigilada: %s",
                        error,
                    )
            if self.on_file_callback:
                self.on_file_callback(encrypted_path)
            return encrypted_path
        except Exception as error:
            logging.getLogger(__name__).exception("Falló el cifrado del archivo capturado.")
            self.pause_capture(error)
            if file_path not in self.memory_queue:
                self.memory_queue.append(file_path)
            return None

    # RF-04 — Importa fuentes, cifra las válidas y devuelve las rutas cifradas.
    def import_files(self, file_paths):
        """Importa archivos existentes y retorna únicamente las rutas cifradas de la sesión."""
        self._require_session_temp_dir()
        imported_paths = []

        for source_path in file_paths:
            if not os.path.exists(source_path):
                logging.getLogger(__name__).warning(
                    "No existe el archivo de importación: %s",
                    source_path,
                )
                continue

            try:
                encrypted_path = self._secure_source_file(source_path)
                imported_paths.append(encrypted_path)
                logging.getLogger(__name__).info(
                    "Archivo importado y cifrado: %s",
                    os.path.basename(encrypted_path),
                )
            except Exception as error:
                logging.getLogger(__name__).exception(
                    "Falló la importación del archivo %s.",
                    source_path,
                )

        return imported_paths

    # RF-04 — Devuelve los escáneres disponibles; registra fallos del controlador.
    def get_scanners(self):
        """Obtiene la lista de escáneres disponibles (SANE en Linux, WIA en Windows)."""
        scanners = []

        try:
            if sys.platform.startswith("linux"):
                result = subprocess.run(
                    ["scanimage", "-f", "%d|%v %m%n"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == PROCESS_SUCCESS_RETURN_CODE:
                    for line in result.stdout.strip().split("\n"):
                        if "|" in line:
                            device_id, device_name = line.split("|", 1)
                            scanners.append(
                                {
                                    "id": device_id.strip(),
                                    "name": device_name.strip(),
                                }
                            )

            elif sys.platform == "win32":
                import win32com.client

                device_manager = win32com.client.Dispatch("WIA.DeviceManager")
                for index in range(FIRST_DEVICE_INDEX, device_manager.DeviceInfos.Count + 1):
                    info = device_manager.DeviceInfos(index)
                    if info.Type != SCANNER_DEVICE_TYPE:
                        continue

                    device_name = f"Escáner {index}"
                    for property_index in range(FIRST_DEVICE_INDEX, info.Properties.Count + 1):
                        if info.Properties(property_index).Name == "Name":
                            device_name = info.Properties(property_index).Value
                            break

                    scanners.append({"id": info.DeviceID, "name": device_name})
        except Exception:
            logging.getLogger(__name__).exception("No se pudieron listar los escáneres disponibles.")

        return scanners

    # RF-04 — Escanea en memoria, cifra el PDF y devuelve su ruta en la sesión.
    def scan_physical_document(self, device_id=None):
        """Captura un folio y lo cifra sin crear una imagen/PDF temporal en texto claro."""
        self._require_session_temp_dir()
        if self.is_paused:
            raise RuntimeError(
                "La captura está pausada. Resuelve el atasco o fallo y reanuda la sesión."
            )

        from PIL import Image

        base_name = f"scan_{uuid.uuid4().hex[:SCAN_FILENAME_ID_LENGTH]}"
        scan_filename = f"{base_name}.pdf"
        scan_path = self._secure_destination(scan_filename)

        def secure_image_bytes_as_pdf(raw_image_bytes):
            if not raw_image_bytes:
                raise ValueError("El escáner no devolvió contenido de imagen.")

            with Image.open(BytesIO(raw_image_bytes)) as source_image:
                rgb_image = source_image.convert("RGB")
                pdf_buffer = BytesIO()
                rgb_image.save(pdf_buffer, "PDF")

            SecureFileWriter.write_secure_bytes(pdf_buffer.getvalue(), scan_path)
            logging.getLogger(__name__).info(
                "Escaneo convertido en memoria y almacenado cifrado: %s",
                os.path.basename(scan_path),
            )
            return scan_path

        try:
            if sys.platform.startswith("linux"):
                logging.getLogger(__name__).info(
                    "Iniciando escaneo nativo en Linux (dispositivo: %s).",
                    device_id or "Auto",
                )
                command = [
                    "scanimage",
                    "--format=png",
                    f"--resolution={SCAN_RESOLUTION_DPI}",
                ]
                if device_id:
                    command.extend(["-d", device_id])

                result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if result.returncode == PROCESS_SUCCESS_RETURN_CODE and result.stdout:
                    return secure_image_bytes_as_pdf(result.stdout)

                first_error = result.stderr.decode("utf-8", errors="replace").strip()
                logging.getLogger(__name__).warning(
                    "Falló el primer intento scanimage: %s; se reintentará.",
                    first_error,
                )
                time.sleep(SCANNER_RETRY_DELAY_SECONDS)

                result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if result.returncode == PROCESS_SUCCESS_RETURN_CODE and result.stdout:
                    return secure_image_bytes_as_pdf(result.stdout)

                second_error = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"SANE Error: {second_error or first_error}")

            if sys.platform == "win32":
                logging.getLogger(__name__).info("Iniciando escaneo nativo en Windows (WIA).")
                import win32com.client

                if device_id:
                    device_manager = win32com.client.Dispatch("WIA.DeviceManager")
                    target_info = None
                    for index in range(FIRST_DEVICE_INDEX, device_manager.DeviceInfos.Count + 1):
                        if device_manager.DeviceInfos(index).DeviceID == device_id:
                            target_info = device_manager.DeviceInfos(index)
                            break

                    if not target_info:
                        logging.getLogger(__name__).warning(
                            "No se encontró el dispositivo de escaneo %s.",
                            device_id,
                        )
                        return None

                    wia_device = target_info.Connect()
                    item = wia_device.Items(FIRST_WIA_ITEM_INDEX)
                    image = item.Transfer(SCAN_IMAGE_FORMAT_ID)
                else:
                    common_dialog = win32com.client.Dispatch("WIA.CommonDialog")
                    image = common_dialog.ShowAcquireImage(
                        SCANNER_DEVICE_TYPE,
                        WIA_FILE_FORMAT_PDF,
                        WIA_COLOR_MODE,
                        SCAN_IMAGE_FORMAT_ID,
                        False,
                        True,
                        False,
                    )

                if image:
                    raw_image_bytes = bytes(image.FileData.BinaryData)
                    return secure_image_bytes_as_pdf(raw_image_bytes)
                return None

            logging.getLogger(__name__).warning(
                "Sistema operativo no compatible con escaneo nativo: %s",
                sys.platform,
            )
            return None
        except Exception as error:
            logging.getLogger(__name__).exception("Falló el escaneo físico.")
            self.pause_capture(error)
            return None

    # RF-04 — Devuelve los archivos cifrados de la sesión de captura activa.
    def get_temp_files(self):
        """Lista los folios cifrados pertenecientes a la sesión de captura actual."""
        files = []
        session_temp_dir = self._session_temp_dir
        if not session_temp_dir or not os.path.exists(session_temp_dir):
            return files

        for file_name in sorted(os.listdir(session_temp_dir)):
            full_path = os.path.join(session_temp_dir, file_name)
            if not os.path.isfile(full_path):
                continue

            extension = os.path.splitext(file_name)[1].lower()
            if extension in SUPPORTED_DOCUMENT_EXTENSIONS:
                files.append(
                    {
                        "name": file_name,
                        "path": full_path,
                        "size": os.path.getsize(full_path),
                        "ext": extension,
                    }
                )

        return files

    # RF-04 — Limpia temporales cifrados y restablece el estado de la sesión.
    def clear_temp(self):
        """Elimina los directorios temporales cifrados después del procesamiento del lote."""
        if os.path.exists(TEMP_ROOT_DIR):
            for entry_name in os.listdir(TEMP_ROOT_DIR):
                entry_path = os.path.join(TEMP_ROOT_DIR, entry_name)
                try:
                    if os.path.isdir(entry_path):
                        shutil.rmtree(entry_path)
                    else:
                        os.remove(entry_path)
                except OSError as error:
                    logging.getLogger(__name__).warning(
                        "No se pudo limpiar el temporal %s: %s",
                        entry_path,
                        error,
                    )

        SecureFileWriter.deactivate_session(self._secure_session_id)
        self._capture_storage_active = False
        self._secure_session_id = None
        self._session_temp_dir = None
        self.is_paused = False
        self.pause_reason = None
        self.memory_queue = []

    # RF-14 — Evita colisiones de folios cifrados con una variante disponible.
    def _prevent_collision(self, path):
        """Evita colisiones de nombres dentro del directorio cifrado."""
        if not os.path.exists(path):
            return path

        base, extension = os.path.splitext(path)
        version = FIRST_COLLISION_VERSION
        while os.path.exists(f"{base}_v{version}{extension}"):
            version += 1
        return f"{base}_v{version}{extension}"

    @property
    def watch_folder(self):
        return WATCH_DIR

    @property
    def temp_folder(self):
        return self._session_temp_dir or TEMP_ROOT_DIR

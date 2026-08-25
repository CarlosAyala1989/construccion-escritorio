"""
Scanner / File Watcher — Captura e Ingesta de Datos.
Fase 1: vigilancia de carpetas y captura física con almacenamiento temporal cifrado.
"""

from io import BytesIO
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


class PDFHandler(FileSystemEventHandler):
    """Observa la carpeta de entrada y deriva documentos terminados al scanner."""

    def __init__(self, callback):
        self.callback = callback

    def on_created(self, event):
        if event.is_directory:
            return

        extension = os.path.splitext(event.src_path)[1].lower()
        if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
            return

        # El evento puede dispararse antes de que la aplicación origen termine de escribir.
        time.sleep(1)
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
        self.on_file_callback = on_file_callback

    def start_watching(self):
        """Inicia la sesión de ingesta y crea su directorio temporal cifrado."""
        if self._running:
            return True

        self._begin_secure_capture_storage()

        if not HAS_WATCHDOG:
            print("[SCANNER] watchdog no disponible; monitoreo de carpeta deshabilitado")
            return False

        handler = PDFHandler(self._on_new_file)
        self._observer = Observer()
        self._observer.schedule(handler, WATCH_DIR, recursive=False)
        self._observer.daemon = True
        self._observer.start()
        self._running = True
        print(f"[SCANNER] Watching folder: {WATCH_DIR}")
        print(f"[RF-04] Directorio temporal cifrado: {self._session_temp_dir}")
        return True

    def stop_watching(self):
        """Detiene la captura; conserva los folios cifrados para el procesamiento posterior."""
        if self._observer and self._running:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
            self._running = False
            print("[SCANNER] Stopped watching folder")

        if self._capture_storage_active:
            SecureFileWriter.deactivate_session(self._secure_session_id)
            self._capture_storage_active = False

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
            shutil.rmtree(session_temp_dir, ignore_errors=True)
            raise

        self._secure_session_id = secure_session_id
        self._session_temp_dir = session_temp_dir
        self._capture_storage_active = True
        return session_temp_dir

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

    def _secure_source_file(self, source_path):
        destination = self._secure_destination(source_path)
        SecureFileWriter.write_secure(source_path, destination)
        return destination

    def _on_new_file(self, file_path):
        """Procesa un documento detectado por el watcher."""
        if self.is_paused:
            self.memory_queue.append(file_path)
            print(f"[SCANNER] En memoria (pausado): {os.path.basename(file_path)}")
            return

        self._process_file_internal(file_path)

    def _process_file_internal(self, file_path):
        print(f"[SCANNER] New file detected: {os.path.basename(file_path)}")

        try:
            encrypted_path = self._secure_source_file(file_path)
            if self.on_file_callback:
                self.on_file_callback(encrypted_path)
        except Exception as error:
            print(f"[SCANNER] Failed to encrypt captured file: {error}")

    def import_files(self, file_paths):
        """Importa archivos existentes y retorna únicamente las rutas cifradas de la sesión."""
        self._require_session_temp_dir()
        imported_paths = []

        for source_path in file_paths:
            if not os.path.exists(source_path):
                print(f"[SCANNER] Archivo de importación inexistente: {source_path}")
                continue

            try:
                encrypted_path = self._secure_source_file(source_path)
                imported_paths.append(encrypted_path)
                print(f"[SCANNER] Imported/Encrypted: {os.path.basename(encrypted_path)}")
            except Exception as error:
                print(f"[SCANNER] Import failed for {source_path}: {error}")

        return imported_paths

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
                if result.returncode == 0:
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
                for index in range(1, device_manager.DeviceInfos.Count + 1):
                    info = device_manager.DeviceInfos(index)
                    if info.Type != 1:
                        continue

                    device_name = f"Escáner {index}"
                    for property_index in range(1, info.Properties.Count + 1):
                        if info.Properties(property_index).Name == "Name":
                            device_name = info.Properties(property_index).Value
                            break

                    scanners.append({"id": info.DeviceID, "name": device_name})
        except Exception as error:
            print(f"[SCANNER] Error listando escáneres: {error}")

        return scanners

    def scan_physical_document(self, device_id=None):
        """Captura un folio y lo cifra sin crear una imagen/PDF temporal en texto claro."""
        self._require_session_temp_dir()

        from PIL import Image

        base_name = f"scan_{uuid.uuid4().hex[:8]}"
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
            print(
                "[SCANNER] Escaneo convertido en memoria y almacenado cifrado: "
                f"{os.path.basename(scan_path)}"
            )
            return scan_path

        try:
            if sys.platform.startswith("linux"):
                print(
                    "[SCANNER] Iniciando escaneo nativo en Linux "
                    f"(Dispositivo: {device_id or 'Auto'})..."
                )
                command = [
                    "scanimage",
                    "--format=png",
                    f"--resolution={SCAN_RESOLUTION_DPI}",
                ]
                if device_id:
                    command.extend(["-d", device_id])

                result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if result.returncode == 0 and result.stdout:
                    return secure_image_bytes_as_pdf(result.stdout)

                first_error = result.stderr.decode("utf-8", errors="replace").strip()
                print(f"[SCANNER] scanimage falló (intento 1): {first_error}. Reintentando...")
                time.sleep(2)

                result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if result.returncode == 0 and result.stdout:
                    return secure_image_bytes_as_pdf(result.stdout)

                second_error = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"SANE Error: {second_error or first_error}")

            if sys.platform == "win32":
                print("[SCANNER] Iniciando escaneo nativo en Windows (WIA)...")
                import win32com.client

                if device_id:
                    device_manager = win32com.client.Dispatch("WIA.DeviceManager")
                    target_info = None
                    for index in range(1, device_manager.DeviceInfos.Count + 1):
                        if device_manager.DeviceInfos(index).DeviceID == device_id:
                            target_info = device_manager.DeviceInfos(index)
                            break

                    if not target_info:
                        print(f"[SCANNER] No se encontró el dispositivo {device_id}")
                        return None

                    wia_device = target_info.Connect()
                    item = wia_device.Items(1)
                    image = item.Transfer("{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}")
                else:
                    common_dialog = win32com.client.Dispatch("WIA.CommonDialog")
                    image = common_dialog.ShowAcquireImage(
                        1,
                        4,
                        1,
                        "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}",
                        False,
                        True,
                        False,
                    )

                if image:
                    raw_image_bytes = bytes(image.FileData.BinaryData)
                    return secure_image_bytes_as_pdf(raw_image_bytes)
                return None

            print(f"[SCANNER] OS no soportado para escaneo nativo: {sys.platform}")
            return None
        except Exception as error:
            print(f"[SCANNER] Excepción durante el escaneo: {error}")
            return None

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
                    print(f"[RF-04] No se pudo limpiar {entry_path}: {error}")

        SecureFileWriter.deactivate_session(self._secure_session_id)
        self._capture_storage_active = False
        self._secure_session_id = None
        self._session_temp_dir = None

    def _prevent_collision(self, path):
        """Evita colisiones de nombres dentro del directorio cifrado."""
        if not os.path.exists(path):
            return path

        base, extension = os.path.splitext(path)
        version = 2
        while os.path.exists(f"{base}_v{version}{extension}"):
            version += 1
        return f"{base}_v{version}{extension}"

    @property
    def watch_folder(self):
        return WATCH_DIR

    @property
    def temp_folder(self):
        return self._session_temp_dir or TEMP_ROOT_DIR

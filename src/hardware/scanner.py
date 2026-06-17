"""
Scanner / File Watcher — Captura e Ingesta de Datos.
Fase 1: Vigilancia de carpetas para archivos depositados manualmente.
En Linux usa watchdog; en Windows usaría TWAIN/WIA.
"""

import os
import shutil
import time
import threading
from src.core.secure_file_writer import SecureFileWriter
from src.app_paths import DATA_DIR, TEMP_WORKSPACE_DIR, WATCH_DIR, ensure_runtime_dirs

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

ensure_runtime_dirs()
TEMP_DIR = TEMP_WORKSPACE_DIR


class PDFHandler(FileSystemEventHandler):
    """Watches a folder for new PDF files."""

    def __init__(self, callback):
        self.callback = callback

    def on_created(self, event):
        if event.is_directory:
            return
        ext = os.path.splitext(event.src_path)[1].lower()
        if ext in [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"]:
            # Small delay to ensure file is fully written
            time.sleep(1)
            if os.path.exists(event.src_path):
                self.callback(event.src_path)


class ScannerManager:
    """
    Manages file ingestion from watch folder or manual file selection.
    Simulates TWAIN/WIA scanner interface on Linux using folder monitoring.
    """

    def __init__(self, on_file_callback=None):
        self._observer = None
        self._running = False
        self.on_file_callback = on_file_callback

    def start_watching(self):
        """Start watching the watch folder for new files."""
        if not HAS_WATCHDOG:
            print("[SCANNER] watchdog not available, folder monitoring disabled")
            return False

        if self._running:
            return True

        handler = PDFHandler(self._on_new_file)
        self._observer = Observer()
        self._observer.schedule(handler, WATCH_DIR, recursive=False)
        self._observer.daemon = True
        self._observer.start()
        self._running = True
        print(f"[SCANNER] Watching folder: {WATCH_DIR}")
        return True

    def stop_watching(self):
        """Stop folder monitoring."""
        if self._observer and self._running:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._running = False
            print("[SCANNER] Stopped watching folder")

    def _on_new_file(self, file_path):
        """Handle a newly detected file."""
        if self.is_paused:
            self.memory_queue.append(file_path)
            print(f"[SCANNER] En memoria (pausado): {os.path.basename(file_path)}")
            return
            
        self._process_file_internal(file_path)

    def _process_file_internal(self, file_path):
        print(f"[SCANNER] New file detected: {os.path.basename(file_path)}")

        # Copy to temp workspace
        dest = os.path.join(TEMP_DIR, os.path.basename(file_path))
        dest = self._prevent_collision(dest)

        try:
            SecureFileWriter.write_secure(file_path, dest)
            if self.on_file_callback:
                self.on_file_callback(dest)
        except Exception as e:
            print(f"[SCANNER] Failed to copy/encrypt file: {e}")

    def import_files(self, file_paths):
        """
        Manually import files into the temp workspace.
        Returns list of paths in temp workspace.
        """
        imported = []
        for src in file_paths:
            if not os.path.exists(src):
                continue
            dest = os.path.join(TEMP_DIR, os.path.basename(src))
            dest = self._prevent_collision(dest)
            try:
                SecureFileWriter.write_secure(src, dest)
                imported.append(dest)
                print(f"[SCANNER] Imported/Encrypted: {os.path.basename(dest)}")
            except Exception as e:
                print(f"[SCANNER] Import failed for {src}: {e}")

        return imported

    def get_scanners(self):
        """
        Obtiene la lista de escáneres disponibles (SANE en Linux, WIA en Windows).
        """
        scanners = []
        import sys
        try:
            if sys.platform.startswith("linux"):
                import subprocess
                # Listar dispositivos SANE (incluyendo Wi-Fi/AirScan)
                result = subprocess.run(["scanimage", "-f", "%d|%v %m%n"], capture_output=True, text=True)
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        if '|' in line:
                            parts = line.split('|', 1)
                            scanners.append({"id": parts[0].strip(), "name": parts[1].strip()})
            elif sys.platform == "win32":
                import win32com.client
                dev_mgr = win32com.client.Dispatch("WIA.DeviceManager")
                for i in range(1, dev_mgr.DeviceInfos.Count + 1):
                    info = dev_mgr.DeviceInfos(i)
                    if info.Type == 1:  # 1 = ScannerDeviceType
                        d_id = info.DeviceID
                        d_name = f"Escáner {i}"
                        for j in range(1, info.Properties.Count + 1):
                            if info.Properties(j).Name == "Name":
                                d_name = info.Properties(j).Value
                                break
                        scanners.append({"id": d_id, "name": d_name})
        except Exception as e:
            print(f"[SCANNER] Error listando escáneres: {e}")
            
        return scanners

    def scan_physical_document(self, device_id=None):
        """
        CP-054, CP-055, CP-056: Interoperabilidad TWAIN/WIA (y SANE en Linux).
        Escanea físicamente un documento desde hardware conectado y lo convierte a PDF.
        """
        import sys
        import subprocess
        import uuid
        from PIL import Image

        base_name = f"scan_{uuid.uuid4().hex[:8]}"
        scan_filename = f"{base_name}.pdf"
        scan_path = os.path.join(TEMP_DIR, scan_filename)
        scan_path = self._prevent_collision(scan_path)

        def _convert_and_secure(raw_img_path):
            pdf_raw_path = raw_img_path + ".pdf"
            img = Image.open(raw_img_path)
            img.convert("RGB").save(pdf_raw_path, "PDF")
            os.remove(raw_img_path)
            
            SecureFileWriter.write_secure(pdf_raw_path, scan_path)
            os.remove(pdf_raw_path)
            print(f"[SCANNER] Escaneo exitoso convertido a PDF: {os.path.basename(scan_path)}")
            return scan_path

        try:
            if sys.platform.startswith("linux"):
                print(f"[SCANNER] Iniciando escaneo nativo en Linux (Dispositivo: {device_id or 'Auto'})...")
                raw_path = os.path.join(DATA_DIR, f"{base_name}.png")
                
                cmd = ["scanimage", "--format=png", "--resolution=300", f"--output-file={raw_path}"]
                if device_id:
                    cmd.extend(["-d", device_id])
                    
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode == 0 and os.path.exists(raw_path):
                    return _convert_and_secure(raw_path)
                else:
                    # Retry once if it fails, airscan sometimes fails on first try
                    print(f"[SCANNER] scanimage falló (intento 1): {result.stderr}. Reintentando...")
                    import time
                    time.sleep(2)
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode == 0 and os.path.exists(raw_path):
                        return _convert_and_secure(raw_path)
                        
                    print(f"[SCANNER] scanimage falló de nuevo: {result.stderr}")
                    raise Exception(f"SANE Error: {result.stderr}")
            elif sys.platform == "win32":
                print(f"[SCANNER] Iniciando escaneo nativo en Windows (WIA)...")
                try:
                    import win32com.client
                    
                    if device_id:
                        # Conectar al dispositivo específico
                        dev_mgr = win32com.client.Dispatch("WIA.DeviceManager")
                        target_info = None
                        for i in range(1, dev_mgr.DeviceInfos.Count + 1):
                            if dev_mgr.DeviceInfos(i).DeviceID == device_id:
                                target_info = dev_mgr.DeviceInfos(i)
                                break
                                
                        if not target_info:
                            print(f"[SCANNER] No se encontró el dispositivo {device_id}")
                            return None
                            
                        wia_dev = target_info.Connect()
                        # Formato PNG
                        item = wia_dev.Items(1)
                        image = item.Transfer("{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}")
                    else:
                        # Mostrar diálogo WIA
                        wia = win32com.client.Dispatch("WIA.CommonDialog")
                        image = wia.ShowAcquireImage(1, 4, 1, "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}", False, True, False)
                        
                    if image:
                        raw_path = os.path.join(DATA_DIR, f"{base_name}.png")
                        image.SaveFile(raw_path)
                        if os.path.exists(raw_path):
                            return _convert_and_secure(raw_path)
                except Exception as e:
                    print(f"[SCANNER] Windows WIA falló: {e}")
                    return None
            else:
                print(f"[SCANNER] OS no soportado para escaneo nativo: {sys.platform}")
                return None
        except Exception as e:
            print(f"[SCANNER] Excepción durante el escaneo: {e}")
            return None
        return None

    def get_temp_files(self):
        """List all files currently in the temp workspace."""
        files = []
        if os.path.exists(TEMP_DIR):
            for f in sorted(os.listdir(TEMP_DIR)):
                full_path = os.path.join(TEMP_DIR, f)
                if os.path.isfile(full_path):
                    ext = os.path.splitext(f)[1].lower()
                    if ext in [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"]:
                        files.append({
                            "name": f,
                            "path": full_path,
                            "size": os.path.getsize(full_path),
                            "ext": ext,
                        })
        return files

    def clear_temp(self):
        """Clear the temp workspace."""
        if os.path.exists(TEMP_DIR):
            for f in os.listdir(TEMP_DIR):
                full = os.path.join(TEMP_DIR, f)
                try:
                    os.remove(full)
                except OSError:
                    pass

    def _prevent_collision(self, path):
        """Prevent filename collision."""
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        v = 2
        while os.path.exists(f"{base}_v{v}{ext}"):
            v += 1
        return f"{base}_v{v}{ext}"

    @property
    def watch_folder(self):
        return WATCH_DIR

    @property
    def temp_folder(self):
        return TEMP_DIR

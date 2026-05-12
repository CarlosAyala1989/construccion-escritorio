"""
Scanner / File Watcher — Captura e Ingesta de Datos.
Fase 1: Vigilancia de carpetas para archivos depositados manualmente.
En Linux usa watchdog; en Windows usaría TWAIN/WIA.
"""

import os
import shutil
import time
import threading

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WATCH_DIR = os.path.join(BASE_DIR, "data", "watch_folder")
TEMP_DIR = os.path.join(BASE_DIR, "data", "temp_workspace")
os.makedirs(WATCH_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


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
        print(f"[SCANNER] New file detected: {os.path.basename(file_path)}")

        # Copy to temp workspace
        dest = os.path.join(TEMP_DIR, os.path.basename(file_path))
        dest = self._prevent_collision(dest)

        try:
            shutil.copy2(file_path, dest)
            if self.on_file_callback:
                self.on_file_callback(dest)
        except Exception as e:
            print(f"[SCANNER] Failed to copy file: {e}")

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
                shutil.copy2(src, dest)
                imported.append(dest)
                print(f"[SCANNER] Imported: {os.path.basename(dest)}")
            except Exception as e:
                print(f"[SCANNER] Import failed for {src}: {e}")

        return imported

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

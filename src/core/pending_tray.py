import logging
import os
import shutil

FIRST_COLLISION_VERSION = 2

class PendingTray:
    """Módulo para gestionar derivaciones a la Bandeja de Pendientes."""

    # RF-08 — Deriva el archivo a pendientes y devuelve la ruta resultante.
    @staticmethod
    def HandleOCRFailure(file_path, base_pending_dir):
        """
        CP-031: HandleOCRFailure() mueve doc a PENDIENTES.
        Mueve el documento físico a la carpeta local de pendientes.
        """
        os.makedirs(base_pending_dir, exist_ok=True)
        filename = os.path.basename(file_path)
        dest_path = os.path.join(base_pending_dir, filename)
        
        # Evita colisiones de nombres.
        base, ext = os.path.splitext(dest_path)
        version = FIRST_COLLISION_VERSION
        while os.path.exists(dest_path):
            dest_path = f"{base}_v{version}{ext}"
            version += 1
            
        try:
            # Copia y luego elimina para funcionar incluso entre sistemas de archivos.
            shutil.copy2(file_path, dest_path)
            os.remove(file_path)
            return dest_path
        except OSError:
            logging.getLogger(__name__).exception("No se pudo derivar el documento a pendientes.")
            return None

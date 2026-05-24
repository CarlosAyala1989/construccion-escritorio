import os
import shutil

class PendingTray:
    """Módulo para gestionar derivaciones a la Bandeja de Pendientes."""

    @staticmethod
    def HandleOCRFailure(file_path, base_pending_dir):
        """
        CP-031: HandleOCRFailure() mueve doc a PENDIENTES.
        Mueve el documento físico a la carpeta local de pendientes.
        """
        os.makedirs(base_pending_dir, exist_ok=True)
        filename = os.path.basename(file_path)
        dest_path = os.path.join(base_pending_dir, filename)
        
        # Prevent collisions
        base, ext = os.path.splitext(dest_path)
        v = 2
        while os.path.exists(dest_path):
            dest_path = f"{base}_v{v}{ext}"
            v += 1
            
        try:
            # We use copy then remove instead of move across filesystems just in case
            shutil.copy2(file_path, dest_path)
            os.remove(file_path)
            return dest_path
        except Exception as e:
            print(f"[PENDING TRAY] Error: {e}")
            return None

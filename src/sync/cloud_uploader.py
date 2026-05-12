"""
Cloud Uploader — Sincronización con la nube.
Fase 4: Optimización y Sincronización en la Nube.
Patrón Strategy para diferentes proveedores (Google Drive, Dropbox, Local).
"""

import os
import shutil

try:
    from PyPDF2 import PdfReader, PdfWriter
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False


class CloudUploader:
    """
    Handles document upload to cloud destinations.
    Uses Strategy pattern for different cloud providers.
    For now, implements local folder copy as the default strategy.
    """

    def __init__(self, config=None):
        self.config = config or {}

    def upload(self, file_path, cloud_path, workspace_name=None):
        """
        Upload a file to the cloud destination.
        For now: copies to a local 'cloud_output' folder simulating cloud.
        Returns dict with upload result.
        """
        provider = self.config.get("cloudProvider", "MANUAL")

        if provider == "GOOGLE_DRIVE":
            return self._upload_gdrive(file_path, cloud_path)
        elif provider == "DROPBOX":
            return self._upload_dropbox(file_path, cloud_path)
        else:
            return self._upload_local(file_path, cloud_path, workspace_name)

    def _upload_local(self, file_path, cloud_path, workspace_name=None):
        """Copy file to a local output directory simulating cloud upload."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        base_dir = os.path.dirname(base_dir)  # Go up to project root

        # Build output path
        output_base = os.path.join(base_dir, "data", "cloud_output")
        if workspace_name:
            output_dir = os.path.join(output_base, workspace_name)
        elif cloud_path:
            output_dir = os.path.join(output_base, cloud_path.replace("/", os.sep))
        else:
            output_dir = output_base

        os.makedirs(output_dir, exist_ok=True)

        dest = os.path.join(output_dir, os.path.basename(file_path))

        # Collision prevention
        if os.path.exists(dest):
            base, ext = os.path.splitext(dest)
            v = 2
            while os.path.exists(f"{base}_v{v}{ext}"):
                v += 1
            dest = f"{base}_v{v}{ext}"

        try:
            shutil.copy2(file_path, dest)
            return {
                "success": True,
                "destination": dest,
                "provider": "LOCAL",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "provider": "LOCAL",
            }

    def _upload_gdrive(self, file_path, cloud_path):
        """Google Drive upload (placeholder for future implementation)."""
        return {
            "success": False,
            "error": "Google Drive upload not yet implemented. Use manual upload.",
            "provider": "GOOGLE_DRIVE",
        }

    def _upload_dropbox(self, file_path, cloud_path):
        """Dropbox upload (placeholder for future implementation)."""
        return {
            "success": False,
            "error": "Dropbox upload not yet implemented. Use manual upload.",
            "provider": "DROPBOX",
        }

    def compress_pdf(self, input_path, output_path):
        """
        Compress a PDF by re-writing it (basic compression).
        Returns True if compressed successfully.
        """
        if not HAS_PYPDF2:
            return False
        try:
            reader = PdfReader(input_path)
            writer = PdfWriter()
            for page in reader.pages:
                page.compress_content_streams()
                writer.add_page(page)

            with open(output_path, "wb") as f:
                writer.write(f)

            return True
        except Exception as e:
            print(f"[UPLOAD] Compression failed: {e}")
            return False

    def should_compress(self, file_path, threshold_mb=10):
        """Check if file exceeds compression threshold."""
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        return size_mb > threshold_mb

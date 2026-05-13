"""
Cloud Uploader — Sincronización con la nube.
Fase 4: Optimización y Sincronización en la Nube.
Patrón Strategy para diferentes proveedores (Google Drive, Dropbox, Local).
Usa las credenciales (refresh_token + folder ID) almacenadas por el admin en la web.
"""

import os
import shutil
import json

try:
    from PyPDF2 import PdfReader, PdfWriter
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

try:
    import requests as http_requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Google OAuth2 token endpoint
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"


class CloudUploader:
    """
    Handles document upload to cloud destinations.
    Uses Strategy pattern for different cloud providers.
    """

    def __init__(self, config=None):
        self.config = config or {}

    def upload(self, file_path, cloud_path, workspace_name=None, workspace=None):
        """
        Upload a file to the cloud destination.
        `workspace` dict must contain cloudFolderId and cloudRefreshToken for Google Drive.
        """
        if not os.path.exists(file_path):
            return {"success": False, "error": f"Archivo no encontrado: {file_path}", "provider": "NONE"}

        # Determine provider from cloudPath
        if cloud_path.startswith("Google Drive:"):
            return self._upload_gdrive(file_path, workspace)
        elif cloud_path.startswith("Dropbox:"):
            return self._upload_dropbox(file_path, cloud_path)
        elif cloud_path.startswith("LOCAL:"):
            local_dest = cloud_path.replace("LOCAL:", "").strip()
            return self._upload_local_dest(file_path, local_dest, workspace_name)
        else:
            return self._upload_local(file_path, cloud_path, workspace_name)

    # ─── Google Drive Upload ─────────────────────────

    def _upload_gdrive(self, file_path, workspace):
        """Upload file to Google Drive using stored refresh token and folder ID."""
        if not HAS_REQUESTS:
            return {"success": False, "error": "Librería 'requests' no disponible", "provider": "GOOGLE_DRIVE"}

        if not workspace:
            return {"success": False, "error": "No hay workspace con credenciales de Drive", "provider": "GOOGLE_DRIVE"}

        folder_id = workspace.get("cloudFolderId")
        refresh_token = workspace.get("cloudRefreshToken")
        client_id = self.config.get("googleClientId", "")
        client_secret = self.config.get("googleClientSecret", "")

        if not folder_id:
            return {"success": False, "error": "No se configuró un folder ID de Google Drive en el workspace", "provider": "GOOGLE_DRIVE"}

        if not refresh_token:
            return {"success": False, "error": "No se configuró un refresh token de Google Drive. El administrador debe re-vincular la carpeta desde la web.", "provider": "GOOGLE_DRIVE"}

        # Step 1: Get a fresh access token using the refresh token
        access_token = self._refresh_access_token(refresh_token, client_id, client_secret)
        if not access_token:
            return {"success": False, "error": "No se pudo renovar el token de acceso de Google Drive. El admin debe re-autorizar.", "provider": "GOOGLE_DRIVE"}

        # Step 2: Upload the file to Drive via multipart upload
        try:
            filename = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)

            # Metadata part
            metadata = {
                "name": filename,
                "parents": [folder_id],
            }

            # Use multipart upload for files < 5MB, resumable for larger
            if file_size < 5 * 1024 * 1024:
                result = self._simple_upload(file_path, metadata, access_token)
            else:
                result = self._resumable_upload(file_path, metadata, access_token)

            if result.get("id"):
                print(f"[UPLOAD] ✅ Subido a Google Drive: {filename} (ID: {result['id']})")
                return {
                    "success": True,
                    "destination": f"Google Drive: {filename}",
                    "drive_file_id": result["id"],
                    "provider": "GOOGLE_DRIVE",
                }
            else:
                return {
                    "success": False,
                    "error": f"Respuesta inesperada de Drive: {json.dumps(result)}",
                    "provider": "GOOGLE_DRIVE",
                }

        except Exception as e:
            print(f"[UPLOAD] ❌ Error subiendo a Google Drive: {e}")
            return {"success": False, "error": str(e), "provider": "GOOGLE_DRIVE"}

    def _refresh_access_token(self, refresh_token, client_id, client_secret):
        """Exchange a refresh token for a new access token."""
        try:
            resp = http_requests.post(GOOGLE_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            })

            if resp.status_code == 200:
                data = resp.json()
                return data.get("access_token")
            else:
                print(f"[UPLOAD] Token refresh failed ({resp.status_code}): {resp.text}")
                return None
        except Exception as e:
            print(f"[UPLOAD] Token refresh error: {e}")
            return None

    def _simple_upload(self, file_path, metadata, access_token):
        """Multipart upload for small files (<5MB)."""
        import io

        boundary = "gobernanza_boundary_upload"
        filename = os.path.basename(file_path)

        # Determine MIME type
        ext = os.path.splitext(filename)[1].lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tiff": "image/tiff",
            ".bmp": "image/bmp",
        }
        mime_type = mime_map.get(ext, "application/octet-stream")

        # Build multipart body
        meta_json = json.dumps(metadata)
        with open(file_path, "rb") as f:
            file_data = f.read()

        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode())
        body.write(b"Content-Type: application/json; charset=UTF-8\r\n\r\n")
        body.write(meta_json.encode())
        body.write(f"\r\n--{boundary}\r\n".encode())
        body.write(f"Content-Type: {mime_type}\r\n\r\n".encode())
        body.write(file_data)
        body.write(f"\r\n--{boundary}--\r\n".encode())

        resp = http_requests.post(
            f"{GOOGLE_UPLOAD_URL}?uploadType=multipart",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            data=body.getvalue(),
        )

        if resp.status_code in (200, 201):
            return resp.json()
        else:
            print(f"[UPLOAD] Simple upload failed ({resp.status_code}): {resp.text}")
            return {"error": resp.text}

    def _resumable_upload(self, file_path, metadata, access_token):
        """Resumable upload for large files (>5MB)."""
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }
        mime_type = mime_map.get(ext, "application/octet-stream")

        # Step 1: Initiate the upload
        init_resp = http_requests.post(
            f"{GOOGLE_UPLOAD_URL}?uploadType=resumable",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=metadata,
        )

        if init_resp.status_code != 200:
            return {"error": f"Resumable init failed: {init_resp.text}"}

        upload_url = init_resp.headers.get("Location")
        if not upload_url:
            return {"error": "No upload URL returned"}

        # Step 2: Upload the file
        file_size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            resp = http_requests.put(
                upload_url,
                headers={
                    "Content-Type": mime_type,
                    "Content-Length": str(file_size),
                },
                data=f,
            )

        if resp.status_code in (200, 201):
            return resp.json()
        else:
            return {"error": f"Resumable upload failed: {resp.text}"}

    # ─── Local Destination Upload ─────────────────────

    def _upload_local_dest(self, file_path, dest_path, workspace_name=None):
        """Copy file to a specific local directory path."""
        # Expand ~ home directory
        dest_path = os.path.expanduser(dest_path)

        if workspace_name:
            output_dir = os.path.join(dest_path, workspace_name)
        else:
            output_dir = dest_path

        os.makedirs(output_dir, exist_ok=True)
        dest = os.path.join(output_dir, os.path.basename(file_path))
        dest = self._prevent_collision(dest)

        try:
            shutil.copy2(file_path, dest)
            print(f"[UPLOAD] ✅ Copiado a local: {dest}")
            return {"success": True, "destination": dest, "provider": "LOCAL"}
        except Exception as e:
            return {"success": False, "error": str(e), "provider": "LOCAL"}

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
        dest = self._prevent_collision(dest)

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

    def _upload_dropbox(self, file_path, cloud_path):
        """Dropbox upload (placeholder for future implementation)."""
        return {
            "success": False,
            "error": "Dropbox upload not yet implemented. Use manual upload.",
            "provider": "DROPBOX",
        }

    # ─── Utilities ───────────────────────────────────

    def _prevent_collision(self, path):
        """Prevent filename collision."""
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        v = 2
        while os.path.exists(f"{base}_v{v}{ext}"):
            v += 1
        return f"{base}_v{v}{ext}"

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

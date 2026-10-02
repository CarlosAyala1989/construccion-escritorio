"""
Cloud Uploader — Sincronización con la nube.
Fase 4: Optimización y Sincronización en la Nube.
Patrón Strategy para diferentes proveedores (Google Drive, Dropbox, Local).
Usa las credenciales (refresh_token + folder ID) almacenadas por el admin en la web.
"""

import hashlib
import json
import os
import shutil
from src.app_paths import CLOUD_OUTPUT_DIR, PROCESSED_DIR, ensure_runtime_dirs

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
GOOGLE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
GOOGLE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DRIVE_SHA256_PROPERTY = "sha256"


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
            sha256 = self._calculate_sha256(file_path)
            relative_path = self._processed_relative_path(file_path)
            relative_folder = os.path.dirname(relative_path)
            folder_parts = [
                part
                for part in relative_folder.split(os.sep)
                if part and part not in {".", ".."}
            ]
            target_folder_id = self._ensure_gdrive_folders(
                folder_id,
                folder_parts,
                access_token,
            )
            # Metadata part
            metadata = {
                "name": filename,
                "parents": [target_folder_id],
                "appProperties": {DRIVE_SHA256_PROPERTY: sha256},
            }

            # Use multipart upload for files < 5MB, resumable for larger
            if file_size < 5 * 1024 * 1024:
                result = self._simple_upload(file_path, metadata, access_token)
            else:
                result = self._resumable_upload(file_path, metadata, access_token)

            if result.get("id"):
                stored_filename = result.get("name") or filename
                print(f"[UPLOAD] ✅ Subido a Google Drive: {stored_filename} (ID: {result['id']})")
                drive_path = "/".join(folder_parts + [stored_filename])
                return {
                    "success": True,
                    "destination": f"Google Drive: {drive_path}",
                    "drive_file_id": result["id"],
                    "sha256": sha256,
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

    def _ensure_gdrive_folders(self, root_folder_id, folder_parts, access_token):
        """Find or create each folder below the workspace root."""
        current_folder_id = root_folder_id
        for folder_name in folder_parts:
            existing_id = self._find_gdrive_folder(
                current_folder_id,
                folder_name,
                access_token,
            )
            current_folder_id = existing_id or self._create_gdrive_folder(
                current_folder_id,
                folder_name,
                access_token,
            )
        return current_folder_id

    def _find_gdrive_folder(self, parent_id, folder_name, access_token):
        escaped_parent = self._escape_drive_query_value(parent_id)
        escaped_name = self._escape_drive_query_value(folder_name)
        query = (
            f"'{escaped_parent}' in parents and name = '{escaped_name}' "
            f"and mimeType = '{GOOGLE_FOLDER_MIME_TYPE}' and trashed = false"
        )
        response = http_requests.get(
            GOOGLE_FILES_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "q": query,
                "fields": "files(id,name)",
                "pageSize": 1,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"No se pudo buscar la carpeta '{folder_name}' en Drive: "
                f"{response.text}"
            )

        files = response.json().get("files", [])
        return files[0].get("id") if files else None

    def _create_gdrive_folder(self, parent_id, folder_name, access_token):
        response = http_requests.post(
            GOOGLE_FILES_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"supportsAllDrives": "true"},
            json={
                "name": folder_name,
                "mimeType": GOOGLE_FOLDER_MIME_TYPE,
                "parents": [parent_id],
            },
            timeout=30,
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"No se pudo crear la carpeta '{folder_name}' en Drive: "
                f"{response.text}"
            )

        folder_id = response.json().get("id")
        if not folder_id:
            raise RuntimeError(
                f"Drive no devolvió un ID para la carpeta '{folder_name}'"
            )
        return folder_id

    @staticmethod
    def _escape_drive_query_value(value):
        return str(value).replace("\\", "\\\\").replace("'", "\\'")

    def _resolve_gdrive_collision_name(self, parent_id, filename, access_token):
        """Return filename or the first available _vN variant in Drive."""
        escaped_parent = self._escape_drive_query_value(parent_id)
        page_token = None
        existing_names = set()

        while True:
            params = {
                "q": f"'{escaped_parent}' in parents and trashed = false",
                "fields": "nextPageToken,files(name)",
                "pageSize": 1000,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token

            response = http_requests.get(
                GOOGLE_FILES_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
                timeout=30,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    "No se pudo verificar colisiones de nombre en Google Drive: "
                    f"{response.text}"
                )

            payload = response.json()
            existing_names.update(
                item.get("name")
                for item in payload.get("files", [])
                if item.get("name")
            )
            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        if filename not in existing_names:
            return filename

        base, extension = os.path.splitext(filename)
        version = 2
        candidate = f"{base}_v{version}{extension}"
        while candidate in existing_names:
            version += 1
            candidate = f"{base}_v{version}{extension}"
        return candidate

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
        metadata = dict(metadata)
        metadata["name"] = self._resolve_gdrive_collision_name(
            metadata["parents"][0],
            metadata["name"],
            access_token,
        )

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
            f"{GOOGLE_UPLOAD_URL}?uploadType=multipart&supportsAllDrives=true",
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
        metadata = dict(metadata)
        metadata["name"] = self._resolve_gdrive_collision_name(
            metadata["parents"][0],
            metadata["name"],
            access_token,
        )
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
            f"{GOOGLE_UPLOAD_URL}?uploadType=resumable&supportsAllDrives=true",
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

        relative_path = self._processed_relative_path(file_path)
        dest = os.path.join(output_dir, relative_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        dest = self._prevent_collision(dest)

        try:
            shutil.copy2(file_path, dest)
            print(f"[UPLOAD] ✅ Copiado a local: {dest}")
            return {"success": True, "destination": dest, "provider": "LOCAL"}
        except Exception as e:
            return {"success": False, "error": str(e), "provider": "LOCAL"}

    def _upload_local(self, file_path, cloud_path, workspace_name=None):
        """Copy file to a local output directory simulating cloud upload."""
        ensure_runtime_dirs()

        # Build output path
        output_base = CLOUD_OUTPUT_DIR
        if workspace_name:
            output_dir = os.path.join(output_base, workspace_name)
        elif cloud_path:
            output_dir = os.path.join(output_base, cloud_path.replace("/", os.sep))
        else:
            output_dir = output_base

        relative_path = self._processed_relative_path(file_path)
        dest = os.path.join(output_dir, relative_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
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

    @staticmethod
    def _calculate_sha256(file_path):
        """Calculate the SHA-256 fingerprint of the exact bytes sent to storage."""
        digest = hashlib.sha256()
        with open(file_path, "rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _processed_relative_path(file_path):
        """Return a safe path relative to the processed document directory."""
        root_path = os.path.abspath(PROCESSED_DIR)
        absolute_path = os.path.abspath(file_path)
        try:
            if os.path.commonpath([root_path, absolute_path]) != root_path:
                return os.path.basename(file_path)
        except ValueError:
            return os.path.basename(file_path)

        relative_path = os.path.relpath(absolute_path, root_path)
        parts = [
            part
            for part in relative_path.split(os.sep)
            if part and part not in {".", ".."}
        ]
        return os.path.join(*parts) if parts else os.path.basename(file_path)

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

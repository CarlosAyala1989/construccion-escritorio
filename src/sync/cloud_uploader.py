"""
Cloud Uploader — Sincronización con la nube.
Fase 4: Optimización y Sincronización en la Nube.
Patrón Strategy para diferentes proveedores (Google Drive, Dropbox, Local).
Usa las credenciales (refresh_token + folder ID) almacenadas por el admin en la web.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from src.app_paths import CLOUD_OUTPUT_DIR, PROCESSED_DIR, asegurar_directorios_ejecucion

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

# Punto de acceso de tokens OAuth2 de Google.
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
GOOGLE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DRIVE_SHA256_PROPERTY = "sha256"
DRIVE_OPERATION_PROPERTY = "docuzenOperationId"
GOOGLE_API_TIMEOUT_SECONDS = 30
DRIVE_RESUMABLE_CHUNK_BYTES = 8 * 1024 * 1024
DRIVE_RESUMABLE_MAX_RECOVERIES = 4
HTTP_OK = 200
HTTP_CREATED = 201
SMALL_UPLOAD_MAX_BYTES = 5 * 1024 * 1024
DRIVE_PAGE_SIZE = 1000
GOOGLE_FOLDER_SEARCH_PAGE_SIZE = 1
SHA256_CHUNK_SIZE = 1024 * 1024
FIRST_COLLISION_VERSION = 2
DEFAULT_COMPRESSION_THRESHOLD_MB = 10
BYTES_PER_MEGABYTE = 1024 * 1024
OPERATION_MARKER_DIRECTORY = ".docuzen-operations"
OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class CargadorNube:
    """
    Gestiona la carga de documentos en destinos de nube.
    Usa el patrón Strategy para admitir distintos proveedores.
    """

    def __init__(self, config=None):
        self.config = config or {}
        self._local_operation_lock = threading.RLock()

    # RF-13 — Valida el origen y delega la subida según el proveedor configurado.
    def upload(
        self,
        file_path,
        cloud_path,
        workspace_name=None,
        workspace=None,
        operation_id=None,
    ):
        """
        Carga un archivo en el destino de nube.
        Para Google Drive, `workspace` debe incluir cloudFolderId y cloudRefreshToken.
        """
        if not os.path.isfile(file_path):
            return {"success": False, "error": f"Archivo no encontrado: {file_path}", "provider": "NONE"}
        if operation_id is not None and not OPERATION_ID_PATTERN.fullmatch(str(operation_id)):
            return {
                "success": False,
                "error": "El identificador estable de la operación no es válido.",
                "provider": "NONE",
            }

        # Determina el proveedor a partir de cloudPath.
        if cloud_path.startswith("Google Drive:"):
            return self._subir_drive(file_path, workspace, operation_id=operation_id)
        elif cloud_path.startswith("Dropbox:"):
            return self._subir_dropbox(file_path, cloud_path)
        elif cloud_path.startswith("LOCAL:"):
            local_dest = cloud_path.replace("LOCAL:", "").strip()
            with self._local_operation_lock:
                return self._subir_destino_local(
                    file_path,
                    local_dest,
                    workspace_name,
                    operation_id=operation_id,
                )
        else:
            with self._local_operation_lock:
                return self._subir_local(
                    file_path,
                    cloud_path,
                    workspace_name,
                    operation_id=operation_id,
                )

    # ─── Carga en Google Drive ───────────────────────

    # RF-13 — Renueva credenciales, organiza carpetas y devuelve el resultado de Drive.
    def _subir_drive(self, file_path, workspace, operation_id=None):
        """Carga un archivo en Google Drive con el token y el ID de carpeta guardados."""
        if not HAS_REQUESTS:
            return {"success": False, "error": "Librería 'requests' no disponible", "provider": "GOOGLE_DRIVE"}

        if not workspace:
            return {
                "success": False,
                "error": "No hay workspace con credenciales de Drive",
                "provider": "GOOGLE_DRIVE",
            }

        folder_id = workspace.get("cloudFolderId")
        refresh_token = workspace.get("cloudRefreshToken")
        client_id = self.config.get("googleClientId", "")
        client_secret = self.config.get("googleClientSecret", "")

        if not folder_id:
            return {
                "success": False,
                "error": "No se configuró un folder ID de Google Drive en el workspace",
                "provider": "GOOGLE_DRIVE",
            }

        if not refresh_token:
            return {
                "success": False,
                "error": (
                    "No se configuró un refresh token de Google Drive. "
                    "El administrador debe re-vincular la carpeta desde la web."
                ),
                "provider": "GOOGLE_DRIVE",
            }

        # Paso 1: obtiene un token de acceso vigente a partir del token de renovación.
        access_token = self._actualizar_token_acceso(refresh_token, client_id, client_secret)
        if not access_token:
            return {
                "success": False,
                "error": (
                    "No se pudo renovar el token de acceso de Google Drive. "
                    "El admin debe re-autorizar."
                ),
                "provider": "GOOGLE_DRIVE",
            }

        # Paso 2: carga el archivo en Drive mediante una solicitud multipart.
        try:
            filename = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            sha256 = self._calcular_sha256(file_path)
            relative_path = self._ruta_relativa_procesado(file_path)
            relative_folder = os.path.dirname(relative_path)
            folder_parts = [
                part
                for part in relative_folder.split(os.sep)
                if part and part not in {".", ".."}
            ]
            target_folder_id = self._asegurar_carpetas_drive(
                folder_id,
                folder_parts,
                access_token,
            )
            if operation_id:
                existing = self._buscar_archivo_por_operacion_drive(
                    target_folder_id,
                    operation_id,
                    access_token,
                )
                if existing:
                    drive_path = "/".join(folder_parts + [existing.get("name") or filename])
                    return {
                        "success": True,
                        "destination": f"Google Drive: {drive_path}",
                        "drive_file_id": existing["id"],
                        "sha256": sha256,
                        "provider": "GOOGLE_DRIVE",
                        "duplicate": True,
                        "operation_id": operation_id,
                    }
            # Prepara los metadatos del archivo.
            metadata = {
                "name": filename,
                "parents": [target_folder_id],
                "appProperties": {DRIVE_SHA256_PROPERTY: sha256},
            }
            if operation_id:
                metadata["appProperties"][DRIVE_OPERATION_PROPERTY] = operation_id

            # Usa carga multipart para archivos pequeños y reanudable para los grandes.
            if file_size < SMALL_UPLOAD_MAX_BYTES:
                result = self._subida_simple(file_path, metadata, access_token)
            else:
                result = self._subida_reanudable(file_path, metadata, access_token)

            if result.get("id"):
                stored_filename = result.get("name") or filename
                logging.getLogger(__name__).info(
                    "Archivo subido a Google Drive: %s (ID: %s)",
                    stored_filename,
                    result["id"],
                )
                drive_path = "/".join(folder_parts + [stored_filename])
                return {
                    "success": True,
                    "destination": f"Google Drive: {drive_path}",
                    "drive_file_id": result["id"],
                    "sha256": sha256,
                    "provider": "GOOGLE_DRIVE",
                    "duplicate": False,
                    "operation_id": operation_id,
                }
            else:
                return {
                    "success": False,
                    "error": f"Respuesta inesperada de Drive: {json.dumps(result)}",
                    "provider": "GOOGLE_DRIVE",
                }

        except Exception as error:
            logging.getLogger(__name__).exception("Falló la subida del archivo a Google Drive.")
            return {"success": False, "error": str(error), "provider": "GOOGLE_DRIVE"}

    def _asegurar_carpetas_drive(self, root_folder_id, folder_parts, access_token):
        """Busca o crea cada carpeta debajo de la carpeta raíz del espacio."""
        current_folder_id = root_folder_id
        for folder_name in folder_parts:
            existing_id = self._buscar_carpeta_drive(
                current_folder_id,
                folder_name,
                access_token,
            )
            current_folder_id = existing_id or self._crear_carpeta_drive(
                current_folder_id,
                folder_name,
                access_token,
            )
        return current_folder_id

    def _buscar_archivo_por_operacion_drive(self, parent_id, operation_id, access_token):
        """Recupera el resultado remoto de una operación ya confirmada por Drive."""
        escaped_parent = self._escapar_valor_consulta_drive(parent_id)
        escaped_operation = self._escapar_valor_consulta_drive(operation_id)
        query = (
            f"'{escaped_parent}' in parents and "
            f"appProperties has {{ key='{DRIVE_OPERATION_PROPERTY}' and "
            f"value='{escaped_operation}' }} and trashed = false"
        )
        response = http_requests.get(
            GOOGLE_FILES_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "q": query,
                "fields": "files(id,name,appProperties)",
                "pageSize": 1,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
            timeout=GOOGLE_API_TIMEOUT_SECONDS,
        )
        if response.status_code != HTTP_OK:
            raise RuntimeError(
                "No se pudo comprobar la idempotencia de la carga en Google Drive."
            )
        files = response.json().get("files", [])
        return files[0] if files else None

    # RF-13 — Busca una carpeta hija existente para mantener la estructura remota.
    def _buscar_carpeta_drive(self, parent_id, folder_name, access_token):
        escaped_parent = self._escapar_valor_consulta_drive(parent_id)
        escaped_name = self._escapar_valor_consulta_drive(folder_name)
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
                "pageSize": GOOGLE_FOLDER_SEARCH_PAGE_SIZE,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
            timeout=GOOGLE_API_TIMEOUT_SECONDS,
        )
        if response.status_code != HTTP_OK:
            raise RuntimeError(
                f"No se pudo buscar la carpeta '{folder_name}' en Drive: "
                f"{response.text}"
            )

        files = response.json().get("files", [])
        return files[0].get("id") if files else None

    # RF-13 — Crea una carpeta hija y valida que Drive devuelva su identificador.
    def _crear_carpeta_drive(self, parent_id, folder_name, access_token):
        response = http_requests.post(
            GOOGLE_FILES_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"supportsAllDrives": "true"},
            json={
                "name": folder_name,
                "mimeType": GOOGLE_FOLDER_MIME_TYPE,
                "parents": [parent_id],
            },
            timeout=GOOGLE_API_TIMEOUT_SECONDS,
        )
        if response.status_code not in (HTTP_OK, HTTP_CREATED):
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

    # Escapa Drive query value según las reglas del componente.
    @staticmethod
    def _escapar_valor_consulta_drive(value):
        return str(value).replace("\\", "\\\\").replace("'", "\\'")

    # RF-14
    def _resolver_nombre_colision_drive(self, parent_id, filename, access_token):
        """Devuelve el nombre original o la primera variante _vN disponible en Drive."""
        escaped_parent = self._escapar_valor_consulta_drive(parent_id)
        page_token = None
        existing_names = set()

        while True:
            params = {
                "q": f"'{escaped_parent}' in parents and trashed = false",
                "fields": "nextPageToken,files(name)",
                "pageSize": DRIVE_PAGE_SIZE,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token

            response = http_requests.get(
                GOOGLE_FILES_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
                timeout=GOOGLE_API_TIMEOUT_SECONDS,
            )
            if response.status_code != HTTP_OK:
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
        version = FIRST_COLLISION_VERSION
        candidate = f"{base}_v{version}{extension}"
        while candidate in existing_names:
            version += 1
            candidate = f"{base}_v{version}{extension}"
        return candidate

    # RF-13 — Renueva el token OAuth y registra de forma segura los fallos de red.
    def _actualizar_token_acceso(self, refresh_token, client_id, client_secret):
        """Intercambia un token de renovación por un nuevo token de acceso."""
        try:
            resp = http_requests.post(GOOGLE_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            })

            if resp.status_code == HTTP_OK:
                data = resp.json()
                return data.get("access_token")
            else:
                logging.getLogger(__name__).warning(
                    "Falló la renovación del token de Drive (HTTP %s): %s",
                    resp.status_code,
                    resp.text,
                )
                return None
        except Exception:
            logging.getLogger(__name__).exception("Falló la renovación del token de Drive.")
            return None

    # RF-13 — Sube archivos pequeños y devuelve metadatos o un error estructurado.
    def _subida_simple(self, file_path, metadata, access_token):
        """Carga archivos pequeños mediante una solicitud multipart."""
        import io

        boundary = "gobernanza_boundary_upload"
        filename = os.path.basename(file_path)
        metadata = dict(metadata)
        metadata["name"] = self._resolver_nombre_colision_drive(
            metadata["parents"][0],
            metadata["name"],
            access_token,
        )

        # Determina el tipo MIME.
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

        # Construye el cuerpo multipart.
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

        if resp.status_code in (HTTP_OK, HTTP_CREATED):
            return resp.json()
        else:
            logging.getLogger(__name__).warning(
                "Falló la subida simple a Drive (HTTP %s): %s",
                resp.status_code,
                resp.text,
            )
            return {"error": resp.text}

    # RF-13 — Sube archivos grandes mediante la sesión reanudable de Google Drive.
    def _subida_reanudable(self, file_path, metadata, access_token):
        """Carga por fragmentos y recupera el offset confirmado por Drive."""
        filename = os.path.basename(file_path)
        metadata = dict(metadata)
        metadata["name"] = self._resolver_nombre_colision_drive(
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

        file_size = os.path.getsize(file_path)
        upload_url = self._iniciar_sesion_reanudable(
            metadata, access_token, mime_type, file_size
        )
        if not upload_url:
            return {"error": "No se pudo iniciar la carga reanudable."}

        offset = 0
        recoveries = 0
        restarted_expired_session = False
        operation_id = metadata.get("appProperties", {}).get(DRIVE_OPERATION_PROPERTY)
        parent_id = metadata.get("parents", [None])[0]

        with open(file_path, "rb") as source:
            while offset < file_size:
                source.seek(offset)
                chunk = source.read(min(DRIVE_RESUMABLE_CHUNK_BYTES, file_size - offset))
                end = offset + len(chunk) - 1
                try:
                    response = http_requests.put(
                        upload_url,
                        headers={
                            "Content-Type": mime_type,
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {offset}-{end}/{file_size}",
                        },
                        data=chunk,
                        timeout=GOOGLE_API_TIMEOUT_SECONDS,
                    )
                except Exception:
                    response = None

                if response is not None and response.status_code in (HTTP_OK, HTTP_CREATED):
                    return response.json()
                if response is not None and response.status_code == 308:
                    confirmed_offset = self._offset_confirmado_drive(response, file_size)
                    recoveries = 0 if confirmed_offset > offset else recoveries + 1
                    if recoveries > DRIVE_RESUMABLE_MAX_RECOVERIES:
                        return {"error": "Drive no confirmó progreso en la carga reanudable."}
                    offset = confirmed_offset
                    continue

                expired = response is not None and response.status_code in (404, 410)
                if expired and not restarted_expired_session:
                    if operation_id and parent_id:
                        existing = self._buscar_archivo_por_operacion_drive(
                            parent_id, operation_id, access_token
                        )
                        if existing:
                            return existing
                    upload_url = self._iniciar_sesion_reanudable(
                        metadata, access_token, mime_type, file_size
                    )
                    if not upload_url:
                        return {"error": "La sesión caducó y no pudo reiniciarse."}
                    restarted_expired_session = True
                    offset = 0
                    continue

                recoveries += 1
                if recoveries > DRIVE_RESUMABLE_MAX_RECOVERIES:
                    return {"error": "La carga reanudable excedió los intentos de recuperación."}
                status = self._consultar_sesion_reanudable(upload_url, file_size)
                if status.get("complete"):
                    return status["payload"]
                if status.get("expired"):
                    if restarted_expired_session:
                        return {"error": "La sesión reanudable caducó nuevamente."}
                    if operation_id and parent_id:
                        existing = self._buscar_archivo_por_operacion_drive(
                            parent_id, operation_id, access_token
                        )
                        if existing:
                            return existing
                    upload_url = self._iniciar_sesion_reanudable(
                        metadata, access_token, mime_type, file_size
                    )
                    if not upload_url:
                        return {"error": "La sesión caducó y no pudo reiniciarse."}
                    restarted_expired_session = True
                    offset = 0
                    continue
                if "offset" not in status:
                    return {"error": "No se pudo recuperar el estado de la carga reanudable."}
                offset = status["offset"]

        return {"error": "Drive no confirmó la carga reanudable."}

    def _iniciar_sesion_reanudable(self, metadata, access_token, mime_type, file_size):
        response = http_requests.post(
            f"{GOOGLE_UPLOAD_URL}?uploadType=resumable&supportsAllDrives=true",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": mime_type,
                "X-Upload-Content-Length": str(file_size),
            },
            json=metadata,
            timeout=GOOGLE_API_TIMEOUT_SECONDS,
        )
        if response.status_code != HTTP_OK:
            return None
        return response.headers.get("Location")

    def _consultar_sesion_reanudable(self, upload_url, file_size):
        """Consulta la URL opaca sin registrarla ni devolverla al llamador."""
        try:
            response = http_requests.put(
                upload_url,
                headers={
                    "Content-Length": "0",
                    "Content-Range": f"bytes */{file_size}",
                },
                data=b"",
                timeout=GOOGLE_API_TIMEOUT_SECONDS,
            )
        except Exception:
            return {}
        if response.status_code in (HTTP_OK, HTTP_CREATED):
            return {"complete": True, "payload": response.json()}
        if response.status_code == 308:
            return {"offset": self._offset_confirmado_drive(response, file_size)}
        if response.status_code in (404, 410):
            return {"expired": True}
        return {}

    @staticmethod
    def _offset_confirmado_drive(response, file_size):
        range_header = response.headers.get("Range", "")
        match = re.fullmatch(r"bytes=0-(\d+)", range_header)
        if not match:
            return 0
        return min(int(match.group(1)) + 1, file_size)

    # ─── Carga en destino local ──────────────────────

    # RF-13 — Copia el archivo al destino local y devuelve el resultado estructurado.
    def _subir_destino_local(
        self,
        file_path,
        dest_path,
        workspace_name=None,
        operation_id=None,
    ):
        """Copia el archivo en una ruta de destino local específica."""
        # Expande ~ como la ruta del directorio personal.
        dest_path = os.path.expanduser(dest_path)

        if workspace_name:
            output_dir = os.path.join(dest_path, workspace_name)
        else:
            output_dir = dest_path

        relative_path = self._ruta_relativa_procesado(file_path)
        requested_dest = os.path.join(output_dir, relative_path)
        os.makedirs(os.path.dirname(requested_dest), exist_ok=True)
        source_sha256 = self._calcular_sha256(file_path)
        try:
            dest, duplicate = self._reservar_destino_operacion(
                output_dir,
                requested_dest,
                operation_id,
                source_sha256,
            )
        except OSError as error:
            return {"success": False, "error": str(error), "provider": "LOCAL"}
        if duplicate:
            return {
                "success": True,
                "destination": dest,
                "provider": "LOCAL",
                "sha256": source_sha256,
                "duplicate": True,
                "operation_id": operation_id,
            }

        try:
            shutil.copy2(file_path, dest)
            if self._calcular_sha256(dest) != source_sha256:
                raise OSError("La copia local no coincide con la huella del archivo fuente.")
            self._confirmar_destino_operacion(
                output_dir,
                operation_id,
                dest,
                source_sha256,
            )
            logging.getLogger(__name__).info("Archivo copiado al destino local: %s", dest)
            return {
                "success": True,
                "destination": dest,
                "provider": "LOCAL",
                "sha256": source_sha256,
                "duplicate": False,
                "operation_id": operation_id,
            }
        except OSError as error:
            logging.getLogger(__name__).exception("No se pudo copiar el archivo al destino local.")
            return {"success": False, "error": str(error), "provider": "LOCAL"}

    # RF-13 — Copia al directorio local de salida y devuelve un resultado reintentable.
    def _subir_local(
        self,
        file_path,
        cloud_path,
        workspace_name=None,
        operation_id=None,
    ):
        """Copia el archivo en una carpeta local que simula una carga a la nube."""
        asegurar_directorios_ejecucion()

        # Construye la ruta de salida.
        output_base = CLOUD_OUTPUT_DIR
        if workspace_name:
            output_dir = os.path.join(output_base, workspace_name)
        elif cloud_path:
            output_dir = os.path.join(output_base, cloud_path.replace("/", os.sep))
        else:
            output_dir = output_base

        relative_path = self._ruta_relativa_procesado(file_path)
        requested_dest = os.path.join(output_dir, relative_path)
        os.makedirs(os.path.dirname(requested_dest), exist_ok=True)
        source_sha256 = self._calcular_sha256(file_path)
        try:
            dest, duplicate = self._reservar_destino_operacion(
                output_dir,
                requested_dest,
                operation_id,
                source_sha256,
            )
        except OSError as error:
            return {"success": False, "error": str(error), "provider": "LOCAL"}
        if duplicate:
            return {
                "success": True,
                "destination": dest,
                "provider": "LOCAL",
                "sha256": source_sha256,
                "duplicate": True,
                "operation_id": operation_id,
            }

        try:
            shutil.copy2(file_path, dest)
            if self._calcular_sha256(dest) != source_sha256:
                raise OSError("La copia local no coincide con la huella del archivo fuente.")
            self._confirmar_destino_operacion(
                output_dir,
                operation_id,
                dest,
                source_sha256,
            )
            return {
                "success": True,
                "destination": dest,
                "provider": "LOCAL",
                "sha256": source_sha256,
                "duplicate": False,
                "operation_id": operation_id,
            }
        except OSError as error:
            logging.getLogger(__name__).exception("No se pudo copiar el archivo al directorio de salida.")
            return {
                "success": False,
                "error": str(error),
                "provider": "LOCAL",
            }

    def _subir_dropbox(self, file_path, cloud_path):
        """Carga en Dropbox (marcador para una implementación futura)."""
        return {
            "success": False,
            "error": "La carga a Dropbox aún no está implementada. Usa la carga manual.",
            "provider": "DROPBOX",
        }

    def _ruta_marcador_operacion(self, output_dir, operation_id):
        if not operation_id:
            return None
        marker_name = hashlib.sha256(operation_id.encode("utf-8")).hexdigest() + ".json"
        return os.path.join(output_dir, OPERATION_MARKER_DIRECTORY, marker_name)

    def _leer_marcador_operacion(self, marker_path):
        for _ in range(20):
            try:
                with open(marker_path, "r", encoding="utf-8") as marker:
                    return json.load(marker)
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.01)
        raise OSError("No se pudo leer la reserva durable de la operación.")

    def _reservar_destino_operacion(
        self,
        output_dir,
        requested_dest,
        operation_id,
        source_sha256,
    ):
        if not operation_id:
            return self._evitar_colision(requested_dest), False

        marker_path = self._ruta_marcador_operacion(output_dir, operation_id)
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        try:
            descriptor = os.open(
                marker_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            marker = self._leer_marcador_operacion(marker_path)
            destination = marker.get("destination", "")
            if marker.get("operation_id") != operation_id:
                raise OSError("La reserva de operación no coincide con su identificador.")
            if marker.get("sha256") != source_sha256:
                raise OSError("La operación ya existe para un contenido diferente.")
            if os.path.isfile(destination):
                if self._calcular_sha256(destination) != source_sha256:
                    raise OSError("El resultado reservado no conserva la integridad esperada.")
                self._confirmar_destino_operacion(
                    output_dir,
                    operation_id,
                    destination,
                    source_sha256,
                )
                return destination, True
            if marker.get("state") == "PENDING":
                for _ in range(50):
                    time.sleep(0.02)
                    if os.path.isfile(destination):
                        if self._calcular_sha256(destination) != source_sha256:
                            raise OSError(
                                "El resultado concurrente no conserva la integridad esperada."
                            )
                        self._confirmar_destino_operacion(
                            output_dir,
                            operation_id,
                            destination,
                            source_sha256,
                        )
                        return destination, True
            return destination, False

        destination = self._evitar_colision(requested_dest)
        marker = {
            "operation_id": operation_id,
            "sha256": source_sha256,
            "destination": destination,
            "state": "PENDING",
        }
        with os.fdopen(descriptor, "w", encoding="utf-8") as marker_file:
            json.dump(marker, marker_file, ensure_ascii=False, sort_keys=True)
            marker_file.flush()
            os.fsync(marker_file.fileno())
        return destination, False

    def _confirmar_destino_operacion(
        self,
        output_dir,
        operation_id,
        destination,
        source_sha256,
    ):
        if not operation_id:
            return
        marker_path = self._ruta_marcador_operacion(output_dir, operation_id)
        completed = {
            "operation_id": operation_id,
            "sha256": source_sha256,
            "destination": destination,
            "state": "COMPLETE",
        }
        temporary_path = f"{marker_path}.{uuid.uuid4().hex}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as marker:
            json.dump(completed, marker, ensure_ascii=False, sort_keys=True)
            marker.flush()
            os.fsync(marker.fileno())
        os.replace(temporary_path, marker_path)

    # ─── Utilidades ──────────────────────────────────

    # RF-13/RF-14 — Calcula SHA-256 en bloques para identificar el contenido transferido.
    @staticmethod
    def _calcular_sha256(file_path):
        """Calcula la huella SHA-256 de los bytes exactos enviados al almacenamiento."""
        digest = hashlib.sha256()
        with open(file_path, "rb") as file:
            for chunk in iter(lambda: file.read(SHA256_CHUNK_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _ruta_relativa_procesado(file_path):
        """Devuelve una ruta segura relativa al directorio de documentos procesados."""
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

    # RF-14 — Evita colisiones usando la primera variante de nombre disponible.
    def _evitar_colision(self, path):
        """Evita colisiones de nombres de archivo."""
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        version = FIRST_COLLISION_VERSION
        while os.path.exists(f"{base}_v{version}{ext}"):
            version += 1
        return f"{base}_v{version}{ext}"

    # RF-15 — Reescribe las páginas y devuelve si la compresión del PDF fue exitosa.
    def comprimir_pdf(self, input_path, output_path):
        """
        Comprime un PDF al volver a escribirlo (compresión básica).
        Devuelve True si la compresión finaliza correctamente.
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
        except Exception:
            logging.getLogger(__name__).exception("Falló la compresión del PDF.")
            return False

    # RF-15 — Compara el tamaño con el umbral de compresión configurable.
    def debe_comprimir(
        self,
        file_path,
        threshold_mb=DEFAULT_COMPRESSION_THRESHOLD_MB,
    ):
        """Comprueba si el archivo supera el umbral de compresión."""
        size_mb = os.path.getsize(file_path) / BYTES_PER_MEGABYTE
        return size_mb > threshold_mb

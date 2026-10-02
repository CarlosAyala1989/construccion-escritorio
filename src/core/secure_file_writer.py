"""Escritura cifrada de folios temporales para RF-04.

Cada sesión de captura deriva una clave AES-256 independiente desde la clave
protegida del dispositivo. Los archivos incluyen el identificador de la sesión
en una cabecera autenticada por AES-GCM, de modo que los pendientes sobreviven
a pausas y reinicios sin almacenar la clave de sesión junto al documento.
"""

import os
import tempfile
import hmac
import hashlib
from typing import Dict, Optional, Tuple

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from src.core.local_crypto import get_local_encryption_key


AES_KEY_BYTES = 32
GCM_NONCE_BYTES = 16
GCM_TAG_BYTES = 16
SESSION_ID_LENGTH_BYTES = 2
SECURE_FILE_MAGIC = b"DZSF"
SECURE_FILE_VERSION = 1


class SecureFileWriterError(Exception):
    """Error base de la capa de almacenamiento temporal cifrado."""


class SecureSessionError(SecureFileWriterError):
    """La operación requiere una sesión criptográfica válida."""


class SecureFileFormatError(SecureFileWriterError):
    """El archivo no cumple el formato cifrado esperado por DocuZen."""


class SecureFileWriter:
    """Gestiona archivos AES-256-GCM asociados a sesiones de captura.

    El estado criptográfico compartido permanece encapsulado en esta clase
    porque el scanner escribe los folios y el pipeline posterior los lee. Las
    claves derivadas se conservan en memoria durante la ejecución; pueden
    reconstruirse después de un reinicio desde el secreto local del dispositivo.
    """

    _active_session_id: Optional[str] = None
    _session_keys: Dict[str, bytes] = {}

    @classmethod
    def begin_session(cls, session_id: str) -> str:
        """Activa una sesión y crea su clave AES-256 si aún no existe."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise SecureSessionError("La sesión cifrada requiere un identificador válido.")

        if normalized_session_id not in cls._session_keys:
            cls._session_keys[normalized_session_id] = cls._derive_session_key(
                normalized_session_id
            )

        cls._active_session_id = normalized_session_id
        return normalized_session_id

    @classmethod
    def deactivate_session(cls, session_id: Optional[str] = None) -> None:
        """Desactiva nuevas escrituras sin eliminar las claves todavía necesarias."""
        if session_id is None or cls._active_session_id == session_id:
            cls._active_session_id = None

    @classmethod
    def write_secure(cls, source_path: str, dest_path: str) -> str:
        """Lee un archivo fuente y persiste únicamente su representación cifrada."""
        with open(source_path, "rb") as source_file:
            return cls.write_secure_bytes(source_file.read(), dest_path)

    @classmethod
    def write_secure_bytes(cls, clear_bytes: bytes, dest_path: str) -> str:
        """Cifra bytes en memoria y los escribe de forma atómica en ``dest_path``."""
        session_id, session_key = cls._require_active_session()
        if not isinstance(clear_bytes, (bytes, bytearray, memoryview)):
            raise TypeError("clear_bytes debe contener datos binarios.")

        session_id_bytes = session_id.encode("utf-8")
        max_session_id_length = (1 << (SESSION_ID_LENGTH_BYTES * 8)) - 1
        if len(session_id_bytes) > max_session_id_length:
            raise SecureSessionError("El identificador de sesión excede el tamaño permitido.")

        cipher = AES.new(session_key, AES.MODE_GCM, nonce=get_random_bytes(GCM_NONCE_BYTES))
        ciphertext, authentication_tag = cipher.encrypt_and_digest(bytes(clear_bytes))

        payload = b"".join(
            [
                SECURE_FILE_MAGIC,
                bytes([SECURE_FILE_VERSION]),
                len(session_id_bytes).to_bytes(SESSION_ID_LENGTH_BYTES, "big"),
                session_id_bytes,
                cipher.nonce,
                authentication_tag,
                ciphertext,
            ]
        )

        destination_dir = os.path.dirname(os.path.abspath(dest_path))
        os.makedirs(destination_dir, exist_ok=True)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination_dir,
                prefix=".docuzen-secure-",
                delete=False,
            ) as encrypted_temp_file:
                temp_path = encrypted_temp_file.name
                encrypted_temp_file.write(payload)
                encrypted_temp_file.flush()
                os.fsync(encrypted_temp_file.fileno())

            os.replace(temp_path, dest_path)
            temp_path = None
            try:
                os.chmod(dest_path, 0o600)
            except OSError:
                # Windows puede no aplicar permisos POSIX; el contenido sigue cifrado.
                pass
            return dest_path
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    @classmethod
    def read_secure(cls, file_path: str) -> bytes:
        """Descifra y autentica un folio temporal, devolviendo sus bytes en memoria."""
        with open(file_path, "rb") as encrypted_file:
            magic = encrypted_file.read(len(SECURE_FILE_MAGIC))
            if magic != SECURE_FILE_MAGIC:
                raise SecureFileFormatError(
                    "El archivo temporal no tiene la cabecera cifrada esperada."
                )

            version_bytes = encrypted_file.read(1)
            if len(version_bytes) != 1 or version_bytes[0] != SECURE_FILE_VERSION:
                raise SecureFileFormatError("Versión de archivo temporal no soportada.")

            session_length_bytes = encrypted_file.read(SESSION_ID_LENGTH_BYTES)
            if len(session_length_bytes) != SESSION_ID_LENGTH_BYTES:
                raise SecureFileFormatError("Cabecera de sesión incompleta.")

            session_id_length = int.from_bytes(session_length_bytes, "big")
            session_id_bytes = encrypted_file.read(session_id_length)
            if len(session_id_bytes) != session_id_length:
                raise SecureFileFormatError("Identificador de sesión incompleto.")

            try:
                session_id = session_id_bytes.decode("utf-8")
            except UnicodeDecodeError as error:
                raise SecureFileFormatError("Identificador de sesión inválido.") from error

            nonce = encrypted_file.read(GCM_NONCE_BYTES)
            authentication_tag = encrypted_file.read(GCM_TAG_BYTES)
            ciphertext = encrypted_file.read()

        if len(nonce) != GCM_NONCE_BYTES or len(authentication_tag) != GCM_TAG_BYTES:
            raise SecureFileFormatError("Cabecera criptográfica incompleta.")

        session_key = cls._session_keys.get(session_id)
        if session_key is None:
            # Las sesiones se derivan de la clave protegida del dispositivo para
            # que una corrección pendiente sobreviva al reinicio de la aplicación.
            session_key = cls._derive_session_key(session_id)
            cls._session_keys[session_id] = session_key

        cipher = AES.new(session_key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, authentication_tag)

    @classmethod
    def _require_active_session(cls) -> Tuple[str, bytes]:
        session_id = cls._active_session_id
        if not session_id:
            raise SecureSessionError(
                "No existe una sesión cifrada activa para almacenar el folio."
            )

        session_key = cls._session_keys.get(session_id)
        if session_key is None:
            raise SecureSessionError("La clave AES-256 de la sesión no está disponible.")

        return session_id, session_key

    @staticmethod
    def _derive_session_key(session_id: str) -> bytes:
        return hmac.new(
            get_local_encryption_key(),
            f"docuzen-capture:{session_id}".encode("utf-8"),
            hashlib.sha256,
        ).digest()

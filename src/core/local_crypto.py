"""Cifrado local autenticado para secretos y bitácoras offline.

La clave puede ser administrada mediante ``GOBERNANZA_LOCAL_ENCRYPTION_KEY``.
Cuando no se configura, se genera una clave de dispositivo con permisos
restringidos dentro del directorio de datos de la aplicación.
"""

import base64
import hashlib
import json
import os
import tempfile
import threading

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from src.app_paths import DATA_DIR, ensure_runtime_dirs


LOCAL_KEY_ENV = "GOBERNANZA_LOCAL_ENCRYPTION_KEY"
LOCAL_KEY_FILE = os.path.join(DATA_DIR, ".local-encryption.key")
ENCRYPTED_PAYLOAD_PREFIX = "DZENC1:"
AES_KEY_BYTES = 32
GCM_NONCE_BYTES = 12
_key_lock = threading.Lock()
_cached_key = None


class LocalCryptoError(Exception):
    """El contenido local no pudo cifrarse, autenticarse o descifrarse."""


def get_local_encryption_key():
    """Return the stable AES-256 device key, creating it atomically if needed."""
    global _cached_key
    if _cached_key is not None:
        return _cached_key

    with _key_lock:
        if _cached_key is not None:
            return _cached_key

        configured_key = os.getenv(LOCAL_KEY_ENV, "").strip()
        if configured_key:
            _cached_key = _normalize_configured_key(configured_key)
            return _cached_key

        ensure_runtime_dirs()
        try:
            with open(LOCAL_KEY_FILE, "rb") as key_file:
                stored_key = base64.urlsafe_b64decode(key_file.read().strip())
            if len(stored_key) != AES_KEY_BYTES:
                raise LocalCryptoError("La clave local almacenada no tiene una longitud válida.")
            _cached_key = stored_key
            return _cached_key
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as error:
            raise LocalCryptoError("No se pudo leer la clave de cifrado local.") from error

        generated_key = get_random_bytes(AES_KEY_BYTES)
        encoded_key = base64.urlsafe_b64encode(generated_key)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=DATA_DIR,
                prefix=".local-key-",
                delete=False,
            ) as temp_file:
                temp_path = temp_file.name
                temp_file.write(encoded_key)
                temp_file.flush()
                os.fsync(temp_file.fileno())

            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass

            try:
                os.link(temp_path, LOCAL_KEY_FILE)
            except FileExistsError:
                with open(LOCAL_KEY_FILE, "rb") as key_file:
                    generated_key = base64.urlsafe_b64decode(key_file.read().strip())
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)

            try:
                os.chmod(LOCAL_KEY_FILE, 0o600)
            except OSError:
                pass
        except (ValueError, OSError) as error:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise LocalCryptoError("No se pudo crear la clave de cifrado local.") from error

        if len(generated_key) != AES_KEY_BYTES:
            raise LocalCryptoError("La clave local almacenada no tiene una longitud válida.")

        _cached_key = generated_key
        return _cached_key


def encrypt_local_payload(payload):
    """Serialize and encrypt a JSON-compatible payload with AES-256-GCM."""
    try:
        clear_bytes = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        cipher = AES.new(
            get_local_encryption_key(),
            AES.MODE_GCM,
            nonce=get_random_bytes(GCM_NONCE_BYTES),
        )
        ciphertext, tag = cipher.encrypt_and_digest(clear_bytes)
        packed = cipher.nonce + tag + ciphertext
        return ENCRYPTED_PAYLOAD_PREFIX + base64.urlsafe_b64encode(packed).decode("ascii")
    except LocalCryptoError:
        raise
    except Exception as error:
        raise LocalCryptoError("No se pudo cifrar la información local.") from error


def decrypt_local_payload(value):
    """Decrypt a value produced by :func:`encrypt_local_payload`."""
    if not isinstance(value, str) or not value.startswith(ENCRYPTED_PAYLOAD_PREFIX):
        raise LocalCryptoError("El contenido no usa el formato cifrado local esperado.")

    try:
        packed = base64.urlsafe_b64decode(value[len(ENCRYPTED_PAYLOAD_PREFIX):])
        minimum_length = GCM_NONCE_BYTES + 16
        if len(packed) < minimum_length:
            raise ValueError("Contenido cifrado incompleto")
        nonce = packed[:GCM_NONCE_BYTES]
        tag = packed[GCM_NONCE_BYTES:minimum_length]
        ciphertext = packed[minimum_length:]
        cipher = AES.new(get_local_encryption_key(), AES.MODE_GCM, nonce=nonce)
        clear_bytes = cipher.decrypt_and_verify(ciphertext, tag)
        return json.loads(clear_bytes.decode("utf-8"))
    except LocalCryptoError:
        raise
    except Exception as error:
        raise LocalCryptoError("La información local cifrada no pudo autenticarse.") from error


def is_encrypted_local_payload(value):
    return isinstance(value, str) and value.startswith(ENCRYPTED_PAYLOAD_PREFIX)


def _normalize_configured_key(configured_key):
    """Accept a 32-byte base64 key or derive one from an administrator secret."""
    try:
        decoded = base64.urlsafe_b64decode(configured_key.encode("ascii"))
        if len(decoded) == AES_KEY_BYTES:
            return decoded
    except (ValueError, UnicodeEncodeError):
        pass

    return hashlib.sha256(configured_key.encode("utf-8")).digest()

"""Cifrado local autenticado para secretos y bitácoras sin conexión."""

# RF-16 — Protege bitácoras y secretos locales con cifrado autenticado.

import base64
import hashlib
import json
import logging
import os
import tempfile

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from src.app_paths import DATA_DIR, asegurar_directorios_ejecucion


LOCAL_KEY_ENV = "GOBERNANZA_LOCAL_ENCRYPTION_KEY"
LOCAL_KEY_FILE = os.path.join(DATA_DIR, ".local-encryption.key")
ENCRYPTED_PAYLOAD_PREFIX = "DZENC1:"
DPAPI_KEY_PREFIX = b"DPAPI1:"
AES_KEY_BYTES = 32
GCM_NONCE_BYTES = 12


class ErrorCifradoLocal(Exception):
    """El contenido local no pudo cifrarse, autenticarse o descifrarse."""


def obtener_clave_cifrado_local():
    """Devuelve la clave AES-256 y la protege con DPAPI en Windows."""
    configured_key = os.getenv(LOCAL_KEY_ENV, "").strip()
    if configured_key:
        return _normalizar_clave_configurada(configured_key)

    asegurar_directorios_ejecucion()
    try:
        with open(LOCAL_KEY_FILE, "rb") as key_file:
            stored_key, requires_migration = _decodificar_clave_almacenada(
                key_file.read().strip()
            )
        _validar_clave(stored_key)
        if requires_migration:
            _guardar_clave_atomica(stored_key, reemplazar=True)
        return stored_key
    except FileNotFoundError:
        pass
    except (ValueError, OSError) as error:
        raise ErrorCifradoLocal("No se pudo leer la clave de cifrado local.") from error

    generated_key = get_random_bytes(AES_KEY_BYTES)
    try:
        _guardar_clave_atomica(generated_key, reemplazar=False)
    except FileExistsError:
        with open(LOCAL_KEY_FILE, "rb") as key_file:
            generated_key, requires_migration = _decodificar_clave_almacenada(
                key_file.read().strip()
            )
        if requires_migration:
            _guardar_clave_atomica(generated_key, reemplazar=True)
    except (ValueError, OSError) as error:
        raise ErrorCifradoLocal("No se pudo crear la clave de cifrado local.") from error

    _validar_clave(generated_key)
    return generated_key


def _validar_clave(key):
    if len(key) != AES_KEY_BYTES:
        raise ErrorCifradoLocal("La clave local almacenada no tiene una longitud válida.")


def _proteger_clave_windows(key):
    """Protege una clave con DPAPI ligada al usuario de Windows actual."""
    try:
        import win32crypt

        protected = win32crypt.CryptProtectData(
            key,
            "Gobernanza Documental - clave local",
            None,
            None,
            None,
            0,
        )
        return DPAPI_KEY_PREFIX + base64.urlsafe_b64encode(protected)
    except Exception as error:
        raise ErrorCifradoLocal("Windows no pudo proteger la clave local con DPAPI.") from error


def _desproteger_clave_windows(stored_value):
    try:
        import win32crypt

        protected = base64.urlsafe_b64decode(stored_value[len(DPAPI_KEY_PREFIX):])
        return win32crypt.CryptUnprotectData(protected, None, None, None, 0)[1]
    except Exception as error:
        raise ErrorCifradoLocal("Windows no pudo recuperar la clave local protegida.") from error


def _codificar_clave_almacenada(key):
    if os.name == "nt":
        return _proteger_clave_windows(key)
    return base64.urlsafe_b64encode(key)


def _decodificar_clave_almacenada(stored_value):
    if stored_value.startswith(DPAPI_KEY_PREFIX):
        if os.name != "nt":
            raise ErrorCifradoLocal("Una clave DPAPI solo puede abrirse en Windows.")
        return _desproteger_clave_windows(stored_value), False

    try:
        key = base64.urlsafe_b64decode(stored_value)
    except (ValueError, TypeError) as error:
        raise ErrorCifradoLocal("La clave local almacenada no es válida.") from error
    return key, os.name == "nt"


def _guardar_clave_atomica(key, reemplazar):
    encoded_key = _codificar_clave_almacenada(key)
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
            logging.getLogger(__name__).debug(
                "No se pudieron restringir los permisos de la clave temporal.",
                exc_info=True,
            )

        if reemplazar:
            os.replace(temp_path, LOCAL_KEY_FILE)
            temp_path = None
        else:
            os.link(temp_path, LOCAL_KEY_FILE)

        try:
            os.chmod(LOCAL_KEY_FILE, 0o600)
        except OSError:
            logging.getLogger(__name__).debug(
                "No se pudieron restringir los permisos de la clave almacenada.",
                exc_info=True,
            )
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def cifrar_contenido_local(payload):
    """Serializa y cifra con AES-256-GCM un contenido compatible con JSON."""
    try:
        clear_bytes = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        cipher = AES.new(
            obtener_clave_cifrado_local(),
            AES.MODE_GCM,
            nonce=get_random_bytes(GCM_NONCE_BYTES),
        )
        ciphertext, tag = cipher.encrypt_and_digest(clear_bytes)
        packed = cipher.nonce + tag + ciphertext
        return ENCRYPTED_PAYLOAD_PREFIX + base64.urlsafe_b64encode(packed).decode("ascii")
    except ErrorCifradoLocal:
        raise
    except Exception as error:
        raise ErrorCifradoLocal("No se pudo cifrar la información local.") from error


def descifrar_contenido_local(value):
    """Descifra un valor generado por :func:`cifrar_contenido_local`."""
    if not isinstance(value, str) or not value.startswith(ENCRYPTED_PAYLOAD_PREFIX):
        raise ErrorCifradoLocal("El contenido no usa el formato cifrado local esperado.")

    try:
        packed = base64.urlsafe_b64decode(value[len(ENCRYPTED_PAYLOAD_PREFIX):])
        minimum_length = GCM_NONCE_BYTES + 16
        if len(packed) < minimum_length:
            raise ValueError("Contenido cifrado incompleto")
        nonce = packed[:GCM_NONCE_BYTES]
        tag = packed[GCM_NONCE_BYTES:minimum_length]
        ciphertext = packed[minimum_length:]
        cipher = AES.new(obtener_clave_cifrado_local(), AES.MODE_GCM, nonce=nonce)
        clear_bytes = cipher.decrypt_and_verify(ciphertext, tag)
        return json.loads(clear_bytes.decode("utf-8"))
    except ErrorCifradoLocal:
        raise
    except Exception as error:
        raise ErrorCifradoLocal("La información local cifrada no pudo autenticarse.") from error


def es_contenido_local_cifrado(value):
    return isinstance(value, str) and value.startswith(ENCRYPTED_PAYLOAD_PREFIX)


def _normalizar_clave_configurada(configured_key):
    """Acepta una clave Base64 de 32 bytes o la deriva de un secreto administrativo."""
    try:
        decoded = base64.urlsafe_b64decode(configured_key.encode("ascii"))
        if len(decoded) == AES_KEY_BYTES:
            return decoded
    except (ValueError, UnicodeEncodeError):
        pass

    return hashlib.sha256(configured_key.encode("utf-8")).digest()

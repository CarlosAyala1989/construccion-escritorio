"""Envelope AES-256-GCM compatible con la aplicación web para secretos MySQL."""

import base64
import json
import os
import re

from Crypto.Cipher import AES


PREFIX = "dzen:v1"
KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
ENV_KEYS = "DOCUZEN_SECRET_KEYS"
ENV_ACTIVE_KEY = "DOCUZEN_SECRET_ACTIVE_KEY_ID"


def construir_aad_secreto(table, field, row_id):
    return f"docuzen:mysql:{table}:{field}:{row_id}"


def _b64url_decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _load_keyring():
    active_key_id = os.getenv(ENV_ACTIVE_KEY, "").strip()
    if not KEY_ID_PATTERN.fullmatch(active_key_id):
        raise ValueError(f"{ENV_ACTIVE_KEY} no está configurada correctamente.")
    try:
        configured = json.loads(os.getenv(ENV_KEYS, ""))
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"{ENV_KEYS} debe ser un objeto JSON de claves Base64.") from error
    if not isinstance(configured, dict):
        raise ValueError(f"{ENV_KEYS} debe ser un objeto JSON de claves Base64.")

    keys = {}
    for key_id, encoded in configured.items():
        if not KEY_ID_PATTERN.fullmatch(str(key_id)) or not isinstance(encoded, str):
            continue
        try:
            key = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ValueError(f"La clave {key_id} no es Base64 válida.") from error
        if len(key) != 32:
            raise ValueError(f"La clave {key_id} debe contener exactamente 32 bytes.")
        keys[key_id] = key
    if active_key_id not in keys:
        raise ValueError(f"La clave activa {active_key_id} no existe en {ENV_KEYS}.")
    return active_key_id, keys


def es_secreto_cifrado(value):
    return isinstance(value, str) and value.startswith(f"{PREFIX}:")


def descifrar_secreto_mysql(value, aad):
    """Lee envelopes v1 y, durante la migración, conserva compatibilidad con texto plano."""
    if value is None:
        return None
    if not es_secreto_cifrado(value):
        return value
    parts = value.split(":")
    if len(parts) != 5 or ":".join(parts[:2]) != PREFIX:
        raise ValueError("El envelope de secreto MySQL no es válido.")
    _, _, key_id, nonce_encoded, payload_encoded = parts
    _, keys = _load_keyring()
    if key_id not in keys:
        raise ValueError(f"No se encontró la clave {key_id} requerida para descifrar.")
    nonce = _b64url_decode(nonce_encoded)
    payload = _b64url_decode(payload_encoded)
    if len(nonce) != 12 or len(payload) < 16:
        raise ValueError("El envelope de secreto MySQL está truncado.")
    ciphertext, tag = payload[:-16], payload[-16:]
    cipher = AES.new(keys[key_id], AES.MODE_GCM, nonce=nonce)
    cipher.update(aad.encode("utf-8"))
    return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")


def descifrar_campo_secreto(table, field, row_id, value):
    return descifrar_secreto_mysql(value, construir_aad_secreto(table, field, row_id))

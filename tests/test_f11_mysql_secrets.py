"""Pruebas del envelope MySQL y de la transición desde texto plano."""

import base64
import json
import os
import unittest
from unittest.mock import patch

from Crypto.Cipher import AES

from src.database.mysql_secrets import construir_aad_secreto, descifrar_secreto_mysql


class PruebasSecretosMysqlF11(unittest.TestCase):
    def setUp(self):
        self.key = bytes([42]) * 32
        self.environment = patch.dict(
            os.environ,
            {
                "DOCUZEN_SECRET_KEYS": json.dumps({"qa2026": base64.b64encode(self.key).decode()}),
                "DOCUZEN_SECRET_ACTIVE_KEY_ID": "qa2026",
            },
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def test_descifra_envelope_compatible_y_rechaza_aad_distinto(self):
        aad = construir_aad_secreto("Config", "cloudCredentials", "config-1")
        nonce = bytes(range(12))
        cipher = AES.new(self.key, AES.MODE_GCM, nonce=nonce)
        cipher.update(aad.encode())
        ciphertext, tag = cipher.encrypt_and_digest(b'{"clientId":"id","clientSecret":"secret"}')
        encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
        envelope = f"dzen:v1:qa2026:{encode(nonce)}:{encode(ciphertext + tag)}"
        self.assertIn("clientSecret", descifrar_secreto_mysql(envelope, aad))
        with self.assertRaises(ValueError):
            descifrar_secreto_mysql(envelope, construir_aad_secreto("Config", "cloudCredentials", "otra"))

    def test_lectura_temporal_de_texto_plano(self):
        self.assertEqual("heredado", descifrar_secreto_mysql("heredado", "aad"))


if __name__ == "__main__":
    unittest.main()

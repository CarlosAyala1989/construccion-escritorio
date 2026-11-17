import base64
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.core import local_crypto
from src.database import sqlite_manager


class SecretosLocalesTest(unittest.TestCase):
    def test_aes_gcm_rechaza_manipulacion(self):
        with mock.patch.dict(
            os.environ,
            {local_crypto.LOCAL_KEY_ENV: "clave-de-prueba-f09"},
            clear=False,
        ):
            encrypted = local_crypto.cifrar_contenido_local({"secret": "valor-sensible"})
            self.assertEqual(
                local_crypto.descifrar_contenido_local(encrypted),
                {"secret": "valor-sensible"},
            )
            replacement = "A" if encrypted[-1] != "A" else "B"
            with self.assertRaises(local_crypto.ErrorCifradoLocal):
                local_crypto.descifrar_contenido_local(encrypted[:-1] + replacement)

    @unittest.skipUnless(os.name == "nt", "DPAPI solo está disponible en Windows")
    def test_dpapi_protege_y_migra_clave_legacy(self):
        key = bytes(range(local_crypto.AES_KEY_BYTES))
        with tempfile.TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / ".local-encryption.key"
            key_file.write_bytes(base64.urlsafe_b64encode(key))

            with (
                mock.patch.dict(os.environ, {local_crypto.LOCAL_KEY_ENV: ""}, clear=False),
                mock.patch.object(local_crypto, "DATA_DIR", temp_dir),
                mock.patch.object(local_crypto, "LOCAL_KEY_FILE", str(key_file)),
                mock.patch.object(local_crypto, "asegurar_directorios_ejecucion"),
            ):
                self.assertEqual(local_crypto.obtener_clave_cifrado_local(), key)
                self.assertTrue(key_file.read_bytes().startswith(local_crypto.DPAPI_KEY_PREFIX))
                self.assertEqual(local_crypto.obtener_clave_cifrado_local(), key)

    def test_cache_y_password_cola_no_quedan_en_claro(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sqlite_path = str(Path(temp_dir) / "local_queue.db")
            secret = "secreto-cache-f09"
            payload = json.dumps({"cloudCredentials": secret})

            with (
                mock.patch.dict(
                    os.environ,
                    {local_crypto.LOCAL_KEY_ENV: "clave-de-prueba-f09"},
                    clear=False,
                ),
                mock.patch.object(sqlite_manager, "SQLITE_PATH", sqlite_path),
            ):
                manager = sqlite_manager.AdministradorBaseDatos()
                manager._guardar_cache("config", payload)
                item_id = manager.agregar_a_cola("doc.pdf", "doc.pdf")
                manager.actualizar_elemento_cola(
                    item_id,
                    encryption_password="password-documento-f09",
                )

                connection = sqlite3.connect(sqlite_path)
                raw_cache = connection.execute(
                    "SELECT value FROM cached_config WHERE key = 'config'"
                ).fetchone()[0]
                raw_password = connection.execute(
                    "SELECT encryption_password FROM local_queue WHERE id = ?",
                    (item_id,),
                ).fetchone()[0]
                connection.close()

                self.assertTrue(raw_cache.startswith("DZENC1:"))
                self.assertNotIn(secret, raw_cache)
                self.assertTrue(raw_password.startswith("DZENC1:"))
                self.assertNotIn("password-documento-f09", raw_password)
                self.assertEqual(
                    manager._obtener_cache("config"),
                    {"cloudCredentials": secret},
                )
                self.assertEqual(
                    manager.obtener_elemento_cola(item_id)["encryption_password"],
                    "password-documento-f09",
                )

    def test_inicializacion_migra_cache_legacy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sqlite_path = str(Path(temp_dir) / "local_queue.db")
            with (
                mock.patch.dict(
                    os.environ,
                    {local_crypto.LOCAL_KEY_ENV: "clave-de-prueba-f09"},
                    clear=False,
                ),
                mock.patch.object(sqlite_manager, "SQLITE_PATH", sqlite_path),
            ):
                manager = sqlite_manager.AdministradorBaseDatos()
                connection = sqlite3.connect(sqlite_path)
                connection.execute(
                    "INSERT INTO cached_config (key, value) VALUES (?, ?)",
                    ("config", '{"legacySecret":"visible"}'),
                )
                connection.commit()
                connection.close()

                manager = sqlite_manager.AdministradorBaseDatos()
                connection = sqlite3.connect(sqlite_path)
                raw = connection.execute(
                    "SELECT value FROM cached_config WHERE key = 'config'"
                ).fetchone()[0]
                connection.close()

                self.assertTrue(raw.startswith("DZENC1:"))
                self.assertNotIn("visible", raw)
                self.assertEqual(
                    manager._obtener_cache("config"),
                    {"legacySecret": "visible"},
                )


if __name__ == "__main__":
    unittest.main()

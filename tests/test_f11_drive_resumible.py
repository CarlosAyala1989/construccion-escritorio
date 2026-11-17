"""Pruebas de protocolo para la carga reanudable Google Drive F11."""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.sync import cloud_uploader
from src.sync.cloud_uploader import CargadorNube


class Respuesta:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class PruebasDriveResumibleF11(unittest.TestCase):
    def setUp(self):
        self.uploader = CargadorNube()
        self.uploader._resolver_nombre_colision_drive = lambda *_: "archivo.pdf"
        self.metadata = {
            "name": "archivo.pdf",
            "parents": ["folder-qa"],
            "appProperties": {"docuzenOperationId": "op-f11"},
        }

    def archivo(self, content=b"abcdefgh"):
        descriptor, path = tempfile.mkstemp(suffix=".pdf")
        os.close(descriptor)
        with open(path, "wb") as target:
            target.write(content)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def test_envia_fragmentos_y_respeta_range_308(self):
        puts = [
            Respuesta(308, headers={"Range": "bytes=0-3"}),
            Respuesta(200, {"id": "drive-1", "name": "archivo.pdf"}),
        ]
        with (
            patch.object(cloud_uploader, "DRIVE_RESUMABLE_CHUNK_BYTES", 4),
            patch.object(
                cloud_uploader.http_requests,
                "post",
                return_value=Respuesta(200, headers={"Location": "https://upload.invalid/session"}),
            ),
            patch.object(cloud_uploader.http_requests, "put", side_effect=puts) as put,
        ):
            result = self.uploader._subida_reanudable(self.archivo(), self.metadata, "token")

        self.assertEqual("drive-1", result["id"])
        self.assertEqual("bytes 0-3/8", put.call_args_list[0].kwargs["headers"]["Content-Range"])
        self.assertEqual("bytes 4-7/8", put.call_args_list[1].kwargs["headers"]["Content-Range"])

    def test_consulta_offset_despues_de_interrupcion(self):
        puts = [
            OSError("conexión interrumpida"),
            Respuesta(308, headers={"Range": "bytes=0-3"}),
            Respuesta(200, {"id": "drive-recuperado"}),
        ]
        with (
            patch.object(cloud_uploader, "DRIVE_RESUMABLE_CHUNK_BYTES", 4),
            patch.object(
                cloud_uploader.http_requests,
                "post",
                return_value=Respuesta(200, headers={"Location": "https://upload.invalid/session"}),
            ),
            patch.object(cloud_uploader.http_requests, "put", side_effect=puts) as put,
        ):
            result = self.uploader._subida_reanudable(self.archivo(), self.metadata, "token")

        self.assertEqual("drive-recuperado", result["id"])
        self.assertEqual("bytes */8", put.call_args_list[1].kwargs["headers"]["Content-Range"])
        self.assertEqual("bytes 4-7/8", put.call_args_list[2].kwargs["headers"]["Content-Range"])

    def test_reinicia_una_sesion_caducada_sin_exponer_url(self):
        posts = [
            Respuesta(200, headers={"Location": "https://upload.invalid/old-secret"}),
            Respuesta(200, headers={"Location": "https://upload.invalid/new-secret"}),
        ]
        puts = [Respuesta(410), Respuesta(200, {"id": "drive-restarted"})]
        with (
            patch.object(cloud_uploader, "DRIVE_RESUMABLE_CHUNK_BYTES", 8),
            patch.object(cloud_uploader.http_requests, "post", side_effect=posts) as post,
            patch.object(cloud_uploader.http_requests, "put", side_effect=puts),
            patch.object(self.uploader, "_buscar_archivo_por_operacion_drive", return_value=None),
        ):
            result = self.uploader._subida_reanudable(self.archivo(), self.metadata, "token")

        self.assertEqual("drive-restarted", result["id"])
        self.assertEqual(2, post.call_count)
        self.assertNotIn("upload.invalid", str(result))


if __name__ == "__main__":
    unittest.main()

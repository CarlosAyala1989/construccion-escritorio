import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.sync.cloud_uploader import CargadorNube


class PruebasIdempotenciaCargaF11(unittest.TestCase):
    def setUp(self):
        self.uploader = CargadorNube()

    def test_reintento_reutiliza_mismo_resultado_sin_duplicar(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as destination:
            source = Path(source_dir, "documento.pdf")
            source.write_bytes(b"%PDF-idempotente")
            first = self.uploader.upload(
                os.fspath(source),
                f"LOCAL: {destination}",
                operation_id="queue-001",
            )
            second = self.uploader.upload(
                os.fspath(source),
                f"LOCAL: {destination}",
                operation_id="queue-001",
            )

            self.assertTrue(first["success"])
            self.assertTrue(second["success"])
            self.assertFalse(first["duplicate"])
            self.assertTrue(second["duplicate"])
            self.assertEqual(first["destination"], second["destination"])
            self.assertEqual(1, len(list(Path(destination).glob("*.pdf"))))

    def test_operaciones_distintas_con_mismos_bytes_son_legitimas(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as destination:
            source = Path(source_dir, "documento.pdf")
            source.write_bytes(b"%PDF-mismo-contenido")
            first = self.uploader.upload(
                os.fspath(source),
                f"LOCAL: {destination}",
                operation_id="queue-uno",
            )
            second = self.uploader.upload(
                os.fspath(source),
                f"LOCAL: {destination}",
                operation_id="queue-dos",
            )

            self.assertTrue(first["success"])
            self.assertTrue(second["success"])
            self.assertNotEqual(first["destination"], second["destination"])
            self.assertEqual(2, len(list(Path(destination).glob("*.pdf"))))

    def test_doble_intento_concurrente_no_crea_dos_documentos(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as destination:
            source = Path(source_dir, "documento.pdf")
            source.write_bytes(b"%PDF-concurrente" * 1024)

            def upload():
                return self.uploader.upload(
                    os.fspath(source),
                    f"LOCAL: {destination}",
                    operation_id="queue-concurrente",
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: upload(), range(2)))

            self.assertTrue(all(result["success"] for result in results))
            self.assertEqual(1, len(list(Path(destination).glob("*.pdf"))))
            self.assertEqual({False, True}, {result["duplicate"] for result in results})

    def test_reserva_pendiente_se_recupera_tras_reinicio_simulado(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as destination:
            source = Path(source_dir, "documento.pdf")
            source.write_bytes(b"%PDF-recuperable")
            requested = os.path.join(destination, source.name)
            sha256 = self.uploader._calcular_sha256(os.fspath(source))
            reserved, duplicate = self.uploader._reservar_destino_operacion(
                destination,
                requested,
                "queue-restart",
                sha256,
            )
            self.assertFalse(duplicate)
            self.assertFalse(os.path.exists(reserved))

            recovered = CargadorNube().upload(
                os.fspath(source),
                f"LOCAL: {destination}",
                operation_id="queue-restart",
            )
            self.assertTrue(recovered["success"])
            self.assertEqual(reserved, recovered["destination"])
            self.assertTrue(os.path.isfile(reserved))

    def test_mismo_id_con_contenido_diferente_falla_cerrado(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as destination:
            source = Path(source_dir, "documento.pdf")
            source.write_bytes(b"primero")
            first = self.uploader.upload(
                os.fspath(source),
                f"LOCAL: {destination}",
                operation_id="queue-mismatch",
            )
            source.write_bytes(b"segundo")
            second = self.uploader.upload(
                os.fspath(source),
                f"LOCAL: {destination}",
                operation_id="queue-mismatch",
            )
            self.assertTrue(first["success"])
            self.assertFalse(second["success"])
            self.assertIn("contenido diferente", second["error"])


if __name__ == "__main__":
    unittest.main()

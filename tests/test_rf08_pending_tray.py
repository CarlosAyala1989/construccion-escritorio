"""Pruebas automatizadas de derivación a pendientes del requisito RF-08."""

import os
import tempfile
import time
import unittest

from src.core.pending_tray import PendingTray


class PendingTrayRF08Tests(unittest.TestCase):
    def test_unitaria_registra_y_devuelve_fallo_si_no_existe_el_origen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_source = os.path.join(temp_dir, "no-existe.pdf")
            pending_dir = os.path.join(temp_dir, "pendientes")

            with self.assertLogs("src.core.pending_tray", level="ERROR"):
                result = PendingTray.HandleOCRFailure(missing_source, pending_dir)

            self.assertIsNone(result)
            self.assertTrue(os.path.isdir(pending_dir))

    def test_integracion_mueve_el_archivo_y_conserva_su_contenido(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "origen", "folio.pdf")
            pending_dir = os.path.join(temp_dir, "pendientes")
            os.makedirs(os.path.dirname(source_path))
            with open(source_path, "wb") as source_file:
                source_file.write(b"contenido protegido")

            destination = PendingTray.HandleOCRFailure(source_path, pending_dir)

            self.assertEqual(destination, os.path.join(pending_dir, "folio.pdf"))
            self.assertFalse(os.path.exists(source_path))
            with open(destination, "rb") as pending_file:
                self.assertEqual(pending_file.read(), b"contenido protegido")

    def test_funcional_crea_la_bandeja_y_devuelve_la_ruta_resultante(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "entrada", "lectura-incompleta.pdf")
            pending_dir = os.path.join(temp_dir, "revision", "pendientes")
            os.makedirs(os.path.dirname(source_path))
            with open(source_path, "wb") as source_file:
                source_file.write(b"folio para revision")

            destination = PendingTray.HandleOCRFailure(source_path, pending_dir)

            self.assertEqual(os.path.basename(destination), "lectura-incompleta.pdf")
            self.assertTrue(os.path.isfile(destination))
            self.assertFalse(os.path.exists(source_path))

    def test_rendimiento_deriva_ciento_veinte_colisiones_sin_perder_archivos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pending_dir = os.path.join(temp_dir, "pendientes")
            source_dir = os.path.join(temp_dir, "origenes")
            destinations = []
            started_at = time.perf_counter()

            for index in range(120):
                item_dir = os.path.join(source_dir, str(index))
                os.makedirs(item_dir)
                source_path = os.path.join(item_dir, "folio.pdf")
                with open(source_path, "wb") as source_file:
                    source_file.write(str(index).encode("utf-8"))
                destinations.append(PendingTray.HandleOCRFailure(source_path, pending_dir))

            elapsed_seconds = time.perf_counter() - started_at

            self.assertEqual(len(set(destinations)), 120)
            self.assertTrue(all(os.path.isfile(destination) for destination in destinations))
            self.assertLess(elapsed_seconds, 10)

    def test_aceptacion_conserva_el_archivo_existente_y_deriva_a_v2(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pending_dir = os.path.join(temp_dir, "pendientes")
            os.makedirs(pending_dir)
            existing_path = os.path.join(pending_dir, "folio.pdf")
            with open(existing_path, "wb") as existing_file:
                existing_file.write(b"version anterior")

            source_path = os.path.join(temp_dir, "entrada", "folio.pdf")
            os.makedirs(os.path.dirname(source_path))
            with open(source_path, "wb") as source_file:
                source_file.write(b"nueva version")

            destination = PendingTray.HandleOCRFailure(source_path, pending_dir)

            self.assertEqual(destination, os.path.join(pending_dir, "folio_v2.pdf"))
            with open(existing_path, "rb") as existing_file:
                self.assertEqual(existing_file.read(), b"version anterior")
            with open(destination, "rb") as pending_file:
                self.assertEqual(pending_file.read(), b"nueva version")


if __name__ == "__main__":
    unittest.main()

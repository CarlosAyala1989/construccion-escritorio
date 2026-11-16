"""Pruebas automatizadas de renombrado y carpetas del requisito RF-07."""

import os
import tempfile
import time
import unittest

from src.core.file_structurer import EstructuradorArchivos


class PruebasEstructuradorArchivosRF07(unittest.TestCase):
    # Limpia caracteres inválidos e impide segmentos vacíos o ascendentes.
    def test_unitaria_limpia_caracteres_invalidos_y_valores_vacios(self):
        self.assertEqual(EstructuradorArchivos._limpiar_valor_ruta("../Plan:<2026>"), "Plan2026")
        self.assertIsNone(EstructuradorArchivos._limpiar_valor_ruta("... "))

    # Crea la jerarquía sin escribir prematuramente el PDF.
    def test_integracion_crea_la_jerarquia_y_no_escribe_el_pdf(self):
        with tempfile.TemporaryDirectory() as output_dir:
            result = EstructuradorArchivos.renombrar_y_estructurar(
                {"anio": "2026", "tipo": "Contrato", "folio": "001"},
                output_dir,
            )

            expected_path = os.path.join(
                output_dir,
                "2026",
                "Contrato",
                "2026_Contrato_001.pdf",
            )
            self.assertEqual(result, expected_path)
            self.assertTrue(os.path.isdir(os.path.dirname(expected_path)))
            self.assertFalse(os.path.exists(expected_path))

    # Construye el nombre y las carpetas a partir de la nomenclatura.
    def test_funcional_construye_nombre_y_carpetas_desde_metadatos(self):
        with tempfile.TemporaryDirectory() as output_dir:
            result = EstructuradorArchivos.renombrar_y_estructurar(
                {"entidad": "Gobernanza", "area": "Obras", "folio": "A-12"},
                output_dir,
                separator="-",
            )

            self.assertEqual(
                result,
                os.path.join(output_dir, "Gobernanza", "Obras", "Gobernanza-Obras-A-12.pdf"),
            )

    # Estructura doscientos cincuenta folios dentro del límite acordado.
    def test_rendimiento_estructura_doscientos_cincuenta_folios(self):
        with tempfile.TemporaryDirectory() as output_dir:
            started_at = time.perf_counter()

            results = [
                EstructuradorArchivos.renombrar_y_estructurar(
                    {"lote": "2026", "expediente": f"E{folio}", "documento": f"F{folio}"},
                    output_dir,
                )
                for folio in range(250)
            ]

            elapsed_seconds = time.perf_counter() - started_at

            self.assertEqual(len(results), 250)
            self.assertEqual(len(set(results)), 250)
            self.assertLess(elapsed_seconds, 10)

    # Impide que la nomenclatura construya rutas fuera de la carpeta base.
    def test_aceptacion_impide_que_metadatos_salgan_de_la_carpeta_base(self):
        with tempfile.TemporaryDirectory() as output_dir:
            result = EstructuradorArchivos.renombrar_y_estructurar(
                {"area": "../externo", "folio": "0001"},
                output_dir,
            )

            self.assertIsNotNone(result)
            self.assertEqual(os.path.commonpath([output_dir, result]), output_dir)
            self.assertEqual(os.path.basename(result), "externo_0001.pdf")


if __name__ == "__main__":
    unittest.main()

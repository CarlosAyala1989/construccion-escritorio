# Pruebas automatizadas de informe riesgo nomenclature.
import os
import tempfile
import unittest
from pathlib import Path

from src.core.file_structurer import EstructuradorArchivos
from src.core.ocr_engine import MotorOCR


EXPECTED_HIERARCHY = [
    "001-2022-XIV-MACREPOL-TACNA",
    "REGPOLTAC",
    "DIVOPUS-TAC",
    "DUE",
    "USE-SECCOMUL",
]


# Agrupa el comportamiento de informe riesgo nomenclatura tests y el estado de sus operaciones.
class PruebasNomenclaturaInformeRiesgo(unittest.TestCase):
    # Extrae la jerarquía aunque el título continúe en la línea siguiente.
    def test_extrae_jerarquia_titulo_envuelto(self):
        text = (
            "INFORME DE RIESGO N° 001-2022-XIV-MACREPOL-TACNA/REGPOLTAC\n"
            "/DIVOPUS-TAC /DUE/USE-SECCOMUL."
        )

        self.assertEqual(
            EXPECTED_HIERARCHY,
            MotorOCR().extraer_jerarquia_titulo(text),
        )

    # Crea carpetas y usa el último segmento como nombre del archivo.
    def test_crea_carpetas_y_usa_ultimo_segmento_como_nombre(self):
        with tempfile.TemporaryDirectory() as output_dir:
            output_path = EstructuradorArchivos.estructurar_jerarquia_titulo(
                EXPECTED_HIERARCHY,
                output_dir,
            )

            relative_path = Path(output_path).relative_to(output_dir)
            self.assertEqual(
                Path(
                    "001-2022-XIV-MACREPOL-TACNA",
                    "REGPOLTAC",
                    "DIVOPUS-TAC",
                    "DUE",
                    "USE-SECCOMUL.pdf",
                ),
                relative_path,
            )
            self.assertTrue(Path(output_path).parent.is_dir())


# Agrupa el comportamiento de informe riesgo real documento integration test y el estado de sus operaciones.
class PruebaIntegracionDocumentoRealInformeRiesgo(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("INFORME_RIESGO_TEST_PDF"),
        "Set INFORME_RIESGO_TEST_PDF to run the real document test.",
    )
    # Comprueba real PDF produces expected jerarquía mediante una prueba de regresión.
    def test_pdf_real_produce_jerarquia_esperada(self):
        engine = MotorOCR()
        text = engine.extraer_texto_pdf(
            os.environ["INFORME_RIESGO_TEST_PDF"],
        )
        hierarchy = engine.extraer_jerarquia_titulo(text)

        self.assertEqual(EXPECTED_HIERARCHY, hierarchy)
        with tempfile.TemporaryDirectory() as output_dir:
            output_path = EstructuradorArchivos.estructurar_jerarquia_titulo(
                hierarchy,
                output_dir,
            )
            relative_path = Path(output_path).relative_to(output_dir)
            self.assertEqual("USE-SECCOMUL.pdf", relative_path.name)
            self.assertEqual(EXPECTED_HIERARCHY[:-1], list(relative_path.parts[:-1]))


if __name__ == "__main__":
    unittest.main()

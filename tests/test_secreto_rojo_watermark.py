# Pruebas automatizadas de secreto rojo watermark.
import os
import unittest

from src.core.ocr_engine import MotorOCR


class PruebaIntegracionMarcaAguaSecretoRojo(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("SECRETO_ROJO_TEST_PDF"),
        "Set SECRETO_ROJO_TEST_PDF to run the red watermark test.",
    )
    # Comprueba el escenario real scanned documento detects roja diagonal marca de agua y sus resultados esperados.
    def test_documento_real_detecta_marca_agua_diagonal_roja(self):
        engine = MotorOCR()
        policy = {
            "id": "secreto-rojo-test",
            "type": "SEMANTIC",
            "target": "SECRETO",
        }

        text = engine.extraer_texto_pdf(
            os.environ["SECRETO_ROJO_TEST_PDF"],
        )

        self.assertIn("SECRETO", text.upper())
        self.assertEqual(policy, engine.verificar_politicas_semanticas(text, [policy]))


if __name__ == "__main__":
    unittest.main()

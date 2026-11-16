# Pruebas automatizadas de secreto watermark.
import os
import unittest

from src.core.ocr_engine import MotorOCR


class PruebaIntegracionMarcaAguaSecreto(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("SECRETO_TEST_PDF"),
        "Set SECRETO_TEST_PDF to run the real document integration test.",
    )
    # Comprueba el escenario real scanned documento detects diagonal SECRETO marca de agua y sus resultados esperados.
    def test_documento_real_detecta_marca_agua_secreto_diagonal(self):
        pdf_path = os.environ["SECRETO_TEST_PDF"]
        engine = MotorOCR()
        policy = {
            "id": "secreto-test",
            "type": "SEMANTIC",
            "target": "SECRETO",
        }

        text = engine.extraer_texto_pdf(pdf_path)
        matched_policy = engine.verificar_politicas_semanticas(text, [policy])

        self.assertIn("SECRETO", text.upper())
        self.assertEqual(policy, matched_policy)


if __name__ == "__main__":
    unittest.main()

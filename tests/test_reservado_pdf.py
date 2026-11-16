# Pruebas automatizadas de reservado pdf.
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.core.ocr_engine import MotorOCR


class PruebasExtraccionPDFHibrido(unittest.TestCase):
    # Combina el texto seleccionable con el OCR visual de la primera página.
    @patch("src.core.ocr_engine.HAS_PYPDF2", True)
    @patch("src.core.ocr_engine.PdfReader")
    def test_combina_texto_seleccionable_con_ocr_visual_primera_pagina(self, reader):
        page = Mock()
        page.extract_text.return_value = "INFORME DE RIESGO"
        reader.return_value = SimpleNamespace(pages=[page])
        engine = MotorOCR()

        with (
            patch("src.core.ocr_engine.os.path.isfile", return_value=True),
            patch.object(engine, "_aplicar_ocr_pdf", return_value="RESERVADO") as ocr,
        ):
            text = engine.extraer_texto_pdf("hybrid.pdf")

        self.assertIn("INFORME DE RIESGO", text)
        self.assertIn("RESERVADO", text)
        ocr.assert_called_once_with("hybrid.pdf", first_page=1, last_page=1)

    # Aplica OCR a todas las páginas cuando el PDF no contiene texto incrustado.
    @patch("src.core.ocr_engine.HAS_PYPDF2", True)
    @patch("src.core.ocr_engine.PdfReader")
    def test_mantiene_ocr_documento_completo_para_pdf_escaneado(self, reader):
        page = Mock()
        page.extract_text.return_value = ""
        reader.return_value = SimpleNamespace(pages=[page])
        engine = MotorOCR()

        with (
            patch("src.core.ocr_engine.os.path.isfile", return_value=True),
            patch.object(engine, "_aplicar_ocr_pdf", return_value="RESERVADO") as ocr,
        ):
            text = engine.extraer_texto_pdf("scanned.pdf")

        self.assertEqual("RESERVADO", text)
        ocr.assert_called_once_with("scanned.pdf")


class PruebaIntegracionDocumentoReservado(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("RESERVADO_TEST_PDF"),
        "Set RESERVADO_TEST_PDF to run the real document integration test.",
    )
    # Valida la detección de RESERVADO y la política semántica con un PDF real.
    def test_documento_real_detecta_reservado_y_coincide_politica(self):
        pdf_path = os.environ["RESERVADO_TEST_PDF"]
        engine = MotorOCR()
        policy = {
            "id": "reservado-test",
            "type": "SEMANTIC",
            "target": "RESERVADO",
        }

        text = engine.extraer_texto_pdf(pdf_path)
        matched_policy = engine.verificar_politicas_semanticas(text, [policy])

        self.assertIn("RESERVADO", text.upper())
        self.assertEqual(policy, matched_policy)


if __name__ == "__main__":
    unittest.main()

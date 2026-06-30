import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.core.ocr_engine import OCREngine


class HybridPdfExtractionTests(unittest.TestCase):
    @patch("src.core.ocr_engine.HAS_PYPDF2", True)
    @patch("src.core.ocr_engine.PdfReader")
    def test_combines_selectable_text_with_first_page_visual_ocr(self, reader):
        page = Mock()
        page.extract_text.return_value = "INFORME DE RIESGO"
        reader.return_value = SimpleNamespace(pages=[page])
        engine = OCREngine()

        with patch.object(engine, "_ocr_from_pdf", return_value="RESERVADO") as ocr:
            text = engine.extract_text_from_pdf("hybrid.pdf")

        self.assertIn("INFORME DE RIESGO", text)
        self.assertIn("RESERVADO", text)
        ocr.assert_called_once_with("hybrid.pdf", first_page=1, last_page=1)

    @patch("src.core.ocr_engine.HAS_PYPDF2", True)
    @patch("src.core.ocr_engine.PdfReader")
    def test_keeps_full_document_ocr_for_scanned_pdfs(self, reader):
        page = Mock()
        page.extract_text.return_value = ""
        reader.return_value = SimpleNamespace(pages=[page])
        engine = OCREngine()

        with patch.object(engine, "_ocr_from_pdf", return_value="RESERVADO") as ocr:
            text = engine.extract_text_from_pdf("scanned.pdf")

        self.assertEqual("RESERVADO", text)
        ocr.assert_called_once_with("scanned.pdf")


class ReservadoDocumentIntegrationTest(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("RESERVADO_TEST_PDF"),
        "Set RESERVADO_TEST_PDF to run the real document integration test.",
    )
    def test_real_document_detects_reservado_and_matches_policy(self):
        pdf_path = os.environ["RESERVADO_TEST_PDF"]
        engine = OCREngine()
        policy = {
            "id": "reservado-test",
            "type": "SEMANTIC",
            "target": "RESERVADO",
        }

        text = engine.extract_text_from_pdf(pdf_path)
        matched_policy = engine.check_semantic_policies(text, [policy])

        self.assertIn("RESERVADO", text.upper())
        self.assertEqual(policy, matched_policy)


if __name__ == "__main__":
    unittest.main()

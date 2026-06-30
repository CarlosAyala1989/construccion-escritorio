import os
import unittest

from src.core.ocr_engine import OCREngine


class SecretoWatermarkIntegrationTest(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("SECRETO_TEST_PDF"),
        "Set SECRETO_TEST_PDF to run the real document integration test.",
    )
    def test_real_scanned_document_detects_diagonal_secreto_watermark(self):
        pdf_path = os.environ["SECRETO_TEST_PDF"]
        engine = OCREngine()
        policy = {
            "id": "secreto-test",
            "type": "SEMANTIC",
            "target": "SECRETO",
        }

        text = engine.extract_text_from_pdf(pdf_path)
        matched_policy = engine.check_semantic_policies(text, [policy])

        self.assertIn("SECRETO", text.upper())
        self.assertEqual(policy, matched_policy)


if __name__ == "__main__":
    unittest.main()

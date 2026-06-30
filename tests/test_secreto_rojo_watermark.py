import os
import unittest

from src.core.ocr_engine import OCREngine


class SecretoRojoWatermarkIntegrationTest(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("SECRETO_ROJO_TEST_PDF"),
        "Set SECRETO_ROJO_TEST_PDF to run the red watermark test.",
    )
    def test_real_scanned_document_detects_red_diagonal_watermark(self):
        engine = OCREngine()
        policy = {
            "id": "secreto-rojo-test",
            "type": "SEMANTIC",
            "target": "SECRETO",
        }

        text = engine.extract_text_from_pdf(
            os.environ["SECRETO_ROJO_TEST_PDF"],
        )

        self.assertIn("SECRETO", text.upper())
        self.assertEqual(policy, engine.check_semantic_policies(text, [policy]))


if __name__ == "__main__":
    unittest.main()

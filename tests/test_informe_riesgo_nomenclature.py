import os
import tempfile
import unittest
from pathlib import Path

from src.core.file_structurer import FileStructurer
from src.core.ocr_engine import OCREngine


EXPECTED_HIERARCHY = [
    "001-2022-XIV-MACREPOL-TACNA",
    "REGPOLTAC",
    "DIVOPUS-TAC",
    "DUE",
    "USE-SECCOMUL",
]


class InformeRiesgoNomenclatureTests(unittest.TestCase):
    def test_extracts_wrapped_title_hierarchy(self):
        text = (
            "INFORME DE RIESGO N° 001-2022-XIV-MACREPOL-TACNA/REGPOLTAC\n"
            "/DIVOPUS-TAC /DUE/USE-SECCOMUL."
        )

        self.assertEqual(
            EXPECTED_HIERARCHY,
            OCREngine().extract_title_hierarchy(text),
        )

    def test_creates_folders_and_uses_last_segment_as_filename(self):
        with tempfile.TemporaryDirectory() as output_dir:
            output_path = FileStructurer.structure_title_hierarchy(
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


class InformeRiesgoRealDocumentIntegrationTest(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("INFORME_RIESGO_TEST_PDF"),
        "Set INFORME_RIESGO_TEST_PDF to run the real document test.",
    )
    def test_real_pdf_produces_expected_hierarchy(self):
        engine = OCREngine()
        text = engine.extract_text_from_pdf(
            os.environ["INFORME_RIESGO_TEST_PDF"],
        )
        hierarchy = engine.extract_title_hierarchy(text)

        self.assertEqual(EXPECTED_HIERARCHY, hierarchy)
        with tempfile.TemporaryDirectory() as output_dir:
            output_path = FileStructurer.structure_title_hierarchy(
                hierarchy,
                output_dir,
            )
            relative_path = Path(output_path).relative_to(output_dir)
            self.assertEqual("USE-SECCOMUL.pdf", relative_path.name)
            self.assertEqual(EXPECTED_HIERARCHY[:-1], list(relative_path.parts[:-1]))


if __name__ == "__main__":
    unittest.main()

"""Regresión F11: segmentación documental sin corrección global 0/O."""

import unittest
from unittest.mock import patch

from src.core.ocr_engine import DOCUMENT_OCR_PAGE_SEGMENTATION_MODE, MotorOCR


class PruebasOcrContextualF11(unittest.TestCase):
    def test_imagen_documental_conserva_texto_base_y_extrae_variante_estructurada(self):
        motor = MotorOCR()
        with (
            patch("src.core.ocr_engine.os.path.isfile", return_value=True),
            patch.object(
                motor,
                "_aplicar_ocr_imagen",
                side_effect=["TITULO FO9", "CODIGO: F09-SCAN-002"],
            ) as ocr,
        ):
            texto = motor.extraer_texto_imagen("fixture.png")

        self.assertEqual("TITULO FO9", texto)
        self.assertEqual("CODIGO: F09-SCAN-002", motor.last_structured_text)
        self.assertEqual(
            [
                unittest.mock.call("fixture.png"),
                unittest.mock.call(
                    "fixture.png",
                    page_segmentation_mode=DOCUMENT_OCR_PAGE_SEGMENTATION_MODE,
                ),
            ],
            ocr.call_args_list,
        )

    def test_no_reemplaza_ambiguos_en_texto_libre(self):
        motor = MotorOCR()
        with (
            patch("src.core.ocr_engine.os.path.isfile", return_value=True),
            patch.object(
                motor,
                "_aplicar_ocr_imagen",
                side_effect=["TITULO FO9\nCODIGO: FO9-SCAN-002", "CODIGO: F09-SCAN-002"],
            ),
        ):
            texto = motor.extraer_texto_imagen("fixture.png")

        self.assertIn("TITULO FO9", texto)
        self.assertIn("CODIGO: FO9-SCAN-002", texto)
        campos = motor.extraer_nomenclatura(
            texto,
            [{"fieldName": "CODIGO", "isRequired": True}],
        )
        self.assertEqual({"CODIGO": "F09-SCAN-002"}, campos)


if __name__ == "__main__":
    unittest.main()

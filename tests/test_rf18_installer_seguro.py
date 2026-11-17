import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstaladorSeguroTest(unittest.TestCase):
    def test_instalador_no_empaqueta_archivos_de_entorno(self):
        build_script = (ROOT / "scripts" / "build-online-installer-linux.sh").read_text(
            encoding="utf-8"
        )
        nsis = (ROOT / "installer" / "windows-online-installer.nsi").read_text(
            encoding="utf-8"
        )

        self.assertFalse((ROOT / "scripts" / "prepare-installer-env.py").exists())
        self.assertNotIn("app.env", build_script)
        self.assertNotIn("app.env", nsis)
        self.assertNotIn("prepare-installer-env", build_script)

    def test_descargas_quedan_fijadas_y_verificadas(self):
        bootstrap = (ROOT / "installer" / "bootstrap-windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("releases/latest", bootstrap)
        self.assertNotIn("tessdata_fast/main", bootstrap)
        self.assertIn("Get-FileHash -Algorithm SHA256", bootstrap)
        self.assertGreaterEqual(
            len(re.findall(r"-ExpectedSha256\s+\"[A-F0-9]{64}\"", bootstrap)),
            4,
        )

    def test_instalacion_falla_si_ocr_no_esta_disponible(self):
        bootstrap = (ROOT / "installer" / "bootstrap-windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("continuara sin OCR local", bootstrap)
        self.assertIn(
            'throw "No se pudo instalar Tesseract OCR desde una fuente verificada"',
            bootstrap,
        )


if __name__ == "__main__":
    unittest.main()

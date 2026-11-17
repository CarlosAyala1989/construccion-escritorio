import re
import unittest
from pathlib import Path

from src.core.ocr_engine import MotorOCR


RAIZ = Path(__file__).resolve().parents[1]
APLICACION_JS = RAIZ / "web" / "js" / "app.js"


class PruebasPrioridadPoliticasF10(unittest.TestCase):
    def test_f10_rc_01_prioridad_supera_especificidad_semantica(self):
        motor = MotorOCR()
        politica_frase_baja = {
            "id": "frase-baja",
            "type": "SEMANTIC",
            "target": "INFORME RESERVADO",
            "priority": 1,
        }
        politica_palabra_alta = {
            "id": "palabra-alta",
            "type": "SEMANTIC",
            "target": "RESERVADO",
            "priority": 50,
        }

        elegida = motor.verificar_politicas_semanticas(
            "Este es un INFORME RESERVADO para archivo.",
            [politica_frase_baja, politica_palabra_alta],
        )

        self.assertEqual("palabra-alta", elegida["id"])

    def test_desempate_es_determinista_por_especificidad_e_identificador(self):
        motor = MotorOCR()
        politicas = [
            {"id": "zeta", "type": "SEMANTIC", "target": "RESERVADO", "priority": 7},
            {"id": "beta", "type": "SEMANTIC", "target": "INFORME RESERVADO", "priority": 7},
            {"id": "alfa", "type": "SEMANTIC", "target": "INFORME RESERVADO", "priority": 7},
        ]

        resultados = {
            motor.verificar_politicas_semanticas(
                "INFORME RESERVADO",
                orden,
            )["id"]
            for orden in (politicas, list(reversed(politicas)), [politicas[1], politicas[0], politicas[2]])
        }

        self.assertEqual({"alfa"}, resultados)


class PruebasRenderSeguroF10(unittest.TestCase):
    def test_datos_externos_no_se_interpolan_en_inner_html(self):
        javascript = APLICACION_JS.read_text(encoding="utf-8")

        patrones_peligrosos = [
            r"\$\{ws\.(?:id|name|cloudPath)\}",
            r"\$\{f\.(?:name|ext)\}",
            r"\$\{s\.(?:id|name)\}",
            r"\$\{item\.(?:id|original_name|error_message|workspace_name|created_at)\}",
        ]
        for patron in patrones_peligrosos:
            self.assertIsNone(re.search(patron, javascript), patron)

        self.assertIn("textContent", javascript)
        self.assertIn("addEventListener", javascript)
        self.assertIn("createOption(scanner.id, scanner.name)", javascript)


if __name__ == "__main__":
    unittest.main()

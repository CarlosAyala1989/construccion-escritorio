"""Pruebas de regresión para el contrato dinámico entre Python y JavaScript."""

import ast
import re
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
CONTROLADOR = RAIZ / "src" / "controller.py"
APLICACION_JS = RAIZ / "web" / "js" / "app.js"
PUENTE_JS = RAIZ / "web" / "js" / "eel_bridge.js"

FUNCIONES_EEL_ESPERADAS = {
    "login",
    "logout",
    "get_current_user",
    "get_workspaces",
    "select_workspace",
    "start_session",
    "end_session",
    "import_files",
    "get_scanners",
    "scan_document",
    "resume_capture",
    "pick_and_import_files",
    "export_files",
    "get_session_files",
    "get_pending_review",
    "get_queue_items",
    "correct_document",
    "get_app_status",
    "sync_now",
    "get_config",
}

CALLBACKS_ESPERADOS = {
    "onFileDetected",
    "onDocumentProcessed",
    "onProcessingProgress",
}


class PruebasContratosEel(unittest.TestCase):
    def test_funciones_python_expuestas_conservan_nombres_compatibles(self):
        arbol = ast.parse(CONTROLADOR.read_text(encoding="utf-8"))
        expuestas = {
            nodo.name
            for nodo in arbol.body
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(
                isinstance(decorador, ast.Attribute)
                and isinstance(decorador.value, ast.Name)
                and decorador.value.id == "eel"
                and decorador.attr == "expose"
                for decorador in nodo.decorator_list
            )
        }

        self.assertEqual(FUNCIONES_EEL_ESPERADAS, expuestas)

    def test_llamadas_javascript_tienen_funcion_python_expuesta(self):
        javascript = "\n".join(
            archivo.read_text(encoding="utf-8")
            for archivo in (APLICACION_JS, RAIZ / "web" / "correction.html")
        )
        llamadas = set(re.findall(r"eel\.([A-Za-z_][A-Za-z0-9_]*)\(", javascript))

        self.assertTrue(llamadas)
        self.assertLessEqual(llamadas, FUNCIONES_EEL_ESPERADAS)

    def test_callbacks_javascript_coinciden_con_invocaciones_python(self):
        controlador = CONTROLADOR.read_text(encoding="utf-8")
        puente = PUENTE_JS.read_text(encoding="utf-8")
        invocados = set(re.findall(r"eel\.(on[A-Za-z0-9_]+)\(", controlador))
        expuestos = set(re.findall(r"eel\.expose\((on[A-Za-z0-9_]+)\)", puente))

        self.assertEqual(CALLBACKS_ESPERADOS, invocados)
        self.assertEqual(CALLBACKS_ESPERADOS, expuestos)


if __name__ == "__main__":
    unittest.main()

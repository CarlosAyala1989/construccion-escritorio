"""Regresiones F10 para las fronteras de autorización expuestas por Eel."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import controller


ERROR_LOGIN = "Debes iniciar sesión primero."
ERROR_SESSION = "Inicia una sesión primero."


class PruebasAutorizacionEelF10(unittest.TestCase):
    def setUp(self):
        controller.capture_context.restablecer()

    def tearDown(self):
        controller.capture_context.restablecer()

    def usuario_vigente(self, user):
        return {
            **user,
            "email": user.get("email", "operador@example.com"),
            "role": user.get("role", "EMPLOYEE"),
            "accessRole": "DESKTOP_SCANNER",
            "authorizationVersion": 1,
        }

    def test_funciones_protegidas_deniegan_sin_login_sin_consultar_servicios(self):
        with (
            patch.object(controller.db, "get_queue_items") as queue_items,
            patch.object(controller.db, "get_config") as get_config,
            patch.object(controller.db, "esta_en_linea") as online,
            patch.object(controller.scanner, "get_scanners") as get_scanners,
            patch.object(controller, "_seleccionar_directorio_exportacion") as select_directory,
            patch.object(controller, "_sincronizar_acumulado_sin_conexion") as synchronize,
        ):
            results = [
                controller.get_pending_review(),
                controller.get_queue_items(),
                controller.get_app_status(),
                controller.sync_now(),
                controller.get_config(),
                controller.get_scanners(),
                controller.export_files(),
            ]

        self.assertTrue(all(result == {"success": False, "error": ERROR_LOGIN} for result in results))
        queue_items.assert_not_called()
        get_config.assert_not_called()
        online.assert_not_called()
        get_scanners.assert_not_called()
        select_directory.assert_not_called()
        synchronize.assert_not_called()

    def test_hardware_y_exportacion_exigen_sesion_de_captura_activa(self):
        controller.capture_context.establecer_usuario({"id": "usuario-1", "name": "Operador"})

        with (
            patch.object(controller.db, "validar_sesion_usuario", side_effect=self.usuario_vigente),
            patch.object(controller.scanner, "get_scanners") as get_scanners,
            patch.object(controller, "_seleccionar_directorio_exportacion") as select_directory,
        ):
            scanner_result = controller.get_scanners()
            export_result = controller.export_files()

        self.assertEqual({"success": False, "error": ERROR_SESSION}, scanner_result)
        self.assertEqual({"success": False, "error": ERROR_SESSION}, export_result)
        get_scanners.assert_not_called()
        select_directory.assert_not_called()

    def test_consultas_autenticadas_se_limitan_al_espacio_vigente(self):
        workspace = {"id": "espacio-1", "name": "Obras"}
        other_item = {"id": "otro", "workspace_id": "espacio-2"}
        current_item = {"id": "actual", "workspace_id": "espacio-1"}
        controller.capture_context.establecer_usuario({"id": "usuario-1", "name": "Operador"})
        controller.capture_context.establecer_espacio_trabajo(workspace)

        with (
            patch.object(controller.db, "validar_sesion_usuario", side_effect=self.usuario_vigente),
            patch.object(controller.db, "obtener_espacios_usuario", return_value=[workspace]),
            patch.object(controller.db, "get_queue_items", return_value=[other_item, current_item]) as queue_items,
            patch.object(controller.db, "get_config", return_value={"idioma": "es"}),
            patch.object(controller, "_sincronizar_acumulado_sin_conexion", return_value={"logs": 2, "documents": 1}) as synchronize,
        ):
            pending = controller.get_pending_review()
            queue = controller.get_queue_items()
            config = controller.get_config()
            sync_result = controller.sync_now()

        self.assertEqual([current_item], pending)
        self.assertEqual([current_item], queue)
        self.assertEqual({"idioma": "es"}, config)
        self.assertEqual({"success": True, "synced": 2, "documents": 1}, sync_result)
        queue_items.assert_any_call(status="PENDING_REVIEW")
        queue_items.assert_any_call(status=None)
        synchronize.assert_called_once_with(workspace_id="espacio-1")

    def test_estado_y_escaneres_autenticados_conservan_contrato_ui(self):
        workspace = {"id": "espacio-1", "name": "Obras"}
        controller.capture_context.establecer_usuario({"id": "usuario-1", "name": "Operador"})
        controller.capture_context.establecer_espacio_trabajo(workspace)
        controller.capture_context.iniciar_sesion("captura-1")
        queue_items = [
            {"workspace_id": "espacio-1"},
            {"workspace_id": "espacio-2"},
        ]
        scanners = [{"id": "wia-1", "name": "Escáner"}]

        with (
            patch.object(controller.db, "validar_sesion_usuario", side_effect=self.usuario_vigente),
            patch.object(controller.db, "obtener_espacios_usuario", return_value=[workspace]),
            patch.object(controller.db, "esta_en_linea", return_value=True),
            patch.object(controller.db, "get_queue_items", return_value=queue_items),
            patch.object(controller.scanner, "get_scanners", return_value=scanners),
        ):
            status = controller.get_app_status()
            available_scanners = controller.get_scanners()

        self.assertTrue(status["online"])
        self.assertTrue(status["session_active"])
        self.assertEqual(1, status["offline_documents"])
        self.assertEqual(scanners, available_scanners)

    def test_exportacion_copia_solo_resultados_administrados_del_espacio_activo(self):
        workspace = {"id": "espacio-1", "name": "Obras"}
        controller.capture_context.establecer_usuario({"id": "usuario-1", "name": "Operador"})
        controller.capture_context.establecer_espacio_trabajo(workspace)
        controller.capture_context.iniciar_sesion("captura-1")

        with tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as destination_dir:
            current_path = Path(output_dir, "actual.pdf")
            other_path = Path(output_dir, "otro.pdf")
            outside_path = Path(destination_dir, "fuera.pdf")
            current_path.write_bytes(b"actual")
            other_path.write_bytes(b"otro")
            outside_path.write_bytes(b"fuera")
            items = [
                {"workspace_id": "espacio-1", "status": "PROCESSED", "file_path": os.fspath(current_path)},
                {"workspace_id": "espacio-2", "status": "PROCESSED", "file_path": os.fspath(other_path)},
                {"workspace_id": "espacio-1", "status": "PROCESSED", "file_path": os.fspath(outside_path)},
            ]

            with (
                patch.object(controller.db, "validar_sesion_usuario", side_effect=self.usuario_vigente),
                patch.object(controller.db, "obtener_espacios_usuario", return_value=[workspace]),
                patch.object(controller.db, "get_queue_items", return_value=items),
                patch.object(controller, "OUTPUT_DIR", output_dir),
                patch.object(controller, "_seleccionar_directorio_exportacion", return_value=destination_dir),
            ):
                result = controller.export_files()

            self.assertEqual(1, result["count"])
            self.assertEqual("espacio-1", result["workspace_id"])
            self.assertEqual(b"actual", Path(destination_dir, "actual.pdf").read_bytes())
            self.assertFalse(Path(destination_dir, "otro.pdf").exists())


if __name__ == "__main__":
    unittest.main()

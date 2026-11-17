"""Regresiones F11 para revocación inmediata en la aplicación de escritorio."""

import unittest
from unittest.mock import patch

from src import controller
from src.database.sqlite_manager import ErrorAutenticacion


class PruebasRevocacionEscritorioF11(unittest.TestCase):
    def setUp(self):
        controller.capture_context.restablecer()
        controller.capture_context.establecer_usuario(
            {
                "id": "operador-f11",
                "name": "Operador F11",
                "email": "operador-f11@example.com",
                "role": "EMPLOYEE",
                "accessRole": "DESKTOP_SCANNER",
                "authorizationVersion": 7,
            }
        )
        controller.capture_context.establecer_espacio_trabajo(
            {"id": "espacio-f11", "name": "Certificación F11"}
        )
        controller.capture_context.iniciar_sesion("sesion-f11")

    def tearDown(self):
        controller.capture_context.restablecer()

    def test_cambio_de_version_revoca_antes_de_mutar(self):
        with (
            patch.object(
                controller.db,
                "validar_sesion_usuario",
                side_effect=ErrorAutenticacion(
                    "Tu acceso cambió o fue revocado. Inicia sesión nuevamente."
                ),
            ),
            patch.object(controller.db, "cerrar_sesion") as cerrar_sesion,
            patch.object(controller.db, "crear_bitacora_auditoria") as auditar,
            patch.object(controller.db, "get_config") as consultar_configuracion,
            patch.object(controller.scanner, "detener_vigilancia") as detener,
        ):
            result = controller.get_config()

        self.assertFalse(result["success"])
        self.assertIn("revocado", result["error"])
        self.assertIsNone(controller.capture_context.user)
        consultar_configuracion.assert_not_called()
        detener.assert_called_once_with()
        cerrar_sesion.assert_called_once_with("sesion-f11")
        self.assertEqual("AUTHORIZATION_REVOKED", auditar.call_args.args[2])

    def test_desactivacion_falla_cerrado_si_no_puede_revalidar(self):
        with (
            patch.object(
                controller.db,
                "validar_sesion_usuario",
                side_effect=ConnectionError("No se pudo verificar la autorización vigente."),
            ),
            patch.object(controller.db, "cerrar_sesion"),
            patch.object(controller.db, "crear_bitacora_auditoria"),
            patch.object(controller.scanner, "detener_vigilancia"),
            patch.object(controller.scanner, "get_scanners") as acceder_hardware,
        ):
            result = controller.get_scanners()

        self.assertFalse(result["success"])
        self.assertIn("verificar", result["error"])
        acceder_hardware.assert_not_called()
        self.assertIsNone(controller.capture_context.user)


if __name__ == "__main__":
    unittest.main()

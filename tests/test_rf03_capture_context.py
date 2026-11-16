"""Pruebas automatizadas del bloqueo de captura del requisito RF-03."""

import time
import unittest

from src.capture_context import (
    ContextoSesionEscritorio,
    ErrorContextoCaptura,
    ERROR_ESPACIO_NO_ASIGNADO,
    ERROR_ESPACIO_REQUERIDO,
    ERROR_SESION_REQUERIDA,
    exigir_contexto_captura_activo,
    validar_espacio_seleccionado,
)


class SustitutoBaseDatosEspacios:
    """Sustituye el origen de permisos sin conectarse a una base externa."""

    def __init__(self, workspaces):
        self.workspaces = workspaces
        self.calls = 0

    # Devuelve los espacios asignados sin consultar MySQL.
    def obtener_espacios_usuario(self, user_id):
        self.calls += 1
        return list(self.workspaces)


class PruebasContextoCapturaRF03(unittest.TestCase):
    # Bloquea la captura cuando todavía no existe una sesión.
    def test_unitaria_bloquea_la_captura_sin_sesion(self):
        context = ContextoSesionEscritorio(user={"id": "operador-1"})

        with self.assertRaisesRegex(ErrorContextoCaptura, ERROR_SESION_REQUERIDA):
            exigir_contexto_captura_activo(None, context)

    # Revalida y actualiza los datos del espacio asignado.
    def test_integracion_valida_y_actualiza_el_espacio_asignado(self):
        assigned_workspace = {"id": "espacio-1", "name": "Obras 2026"}
        database = SustitutoBaseDatosEspacios([assigned_workspace])
        context = ContextoSesionEscritorio(
            user={"id": "operador-1"},
            workspace={"id": "espacio-1", "name": "Nombre antiguo"},
        )

        result = validar_espacio_seleccionado(database, context)

        self.assertEqual(result, assigned_workspace)
        self.assertIs(context.workspace, assigned_workspace)
        self.assertEqual(database.calls, 1)

    # Habilita la captura únicamente con un espacio vigente.
    def test_funcional_habilita_la_captura_con_un_espacio_valido(self):
        workspace = {"id": "espacio-1", "name": "Obras 2026"}
        database = SustitutoBaseDatosEspacios([workspace])
        context = ContextoSesionEscritorio(user={"id": "operador-1"})

        with self.assertRaisesRegex(ErrorContextoCaptura, ERROR_ESPACIO_REQUERIDO):
            validar_espacio_seleccionado(database, context)

        context.establecer_espacio_trabajo(workspace)
        context.iniciar_sesion("captura-1")
        selected_workspace, session_id = exigir_contexto_captura_activo(database, context)

        self.assertEqual(selected_workspace["id"], "espacio-1")
        self.assertEqual(session_id, "captura-1")

    # Mantiene un costo acotado al revalidar mil operaciones de captura.
    def test_rendimiento_valida_mil_ciclos_sin_bloqueos(self):
        workspace = {"id": "espacio-1", "name": "Obras 2026"}
        database = SustitutoBaseDatosEspacios([workspace])
        context = ContextoSesionEscritorio(
            user={"id": "operador-1"},
            workspace=workspace,
            session_id="captura-1",
        )
        started_at = time.perf_counter()

        for _ in range(1000):
            exigir_contexto_captura_activo(database, context)

        elapsed_seconds = time.perf_counter() - started_at

        self.assertEqual(database.calls, 1000)
        self.assertLess(elapsed_seconds, 5)

    # Vuelve a bloquear la captura si se revoca el espacio asignado.
    def test_aceptacion_revoca_el_espacio_y_vuelve_a_bloquear(self):
        workspace = {"id": "espacio-1", "name": "Obras 2026"}
        database = SustitutoBaseDatosEspacios([workspace])
        context = ContextoSesionEscritorio(user={"id": "operador-1"})
        context.establecer_espacio_trabajo(workspace)
        context.iniciar_sesion("captura-1")

        self.assertEqual(exigir_contexto_captura_activo(database, context)[1], "captura-1")

        context.finalizar_sesion()
        database.workspaces.clear()

        with self.assertRaisesRegex(ErrorContextoCaptura, ERROR_ESPACIO_NO_ASIGNADO):
            validar_espacio_seleccionado(database, context)

        self.assertIsNone(context.workspace)
        with self.assertRaisesRegex(ErrorContextoCaptura, ERROR_SESION_REQUERIDA):
            exigir_contexto_captura_activo(database, context)


if __name__ == "__main__":
    unittest.main()

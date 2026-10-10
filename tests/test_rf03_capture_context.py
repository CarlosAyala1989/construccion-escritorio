"""Pruebas automatizadas del bloqueo de captura del requisito RF-03."""

import time
import unittest

from src.capture_context import (
    CaptureContextError,
    DesktopSessionContext,
    SESSION_REQUIRED_ERROR,
    WORKSPACE_NOT_ASSIGNED_ERROR,
    WORKSPACE_REQUIRED_ERROR,
    require_active_capture_context,
    validate_selected_workspace,
)


class WorkspaceDatabaseStub:
    """Sustituye el origen de permisos sin conectarse a una base externa."""

    def __init__(self, workspaces):
        self.workspaces = workspaces
        self.calls = 0

    def get_user_workspaces(self, user_id):
        self.calls += 1
        return list(self.workspaces)


class CaptureContextRF03Tests(unittest.TestCase):
    def test_unitaria_bloquea_la_captura_sin_sesion(self):
        context = DesktopSessionContext(user={"id": "operador-1"})

        with self.assertRaisesRegex(CaptureContextError, SESSION_REQUIRED_ERROR):
            require_active_capture_context(None, context)

    def test_integracion_valida_y_actualiza_el_espacio_asignado(self):
        assigned_workspace = {"id": "espacio-1", "name": "Obras 2026"}
        database = WorkspaceDatabaseStub([assigned_workspace])
        context = DesktopSessionContext(
            user={"id": "operador-1"},
            workspace={"id": "espacio-1", "name": "Nombre antiguo"},
        )

        result = validate_selected_workspace(database, context)

        self.assertEqual(result, assigned_workspace)
        self.assertIs(context.workspace, assigned_workspace)
        self.assertEqual(database.calls, 1)

    def test_funcional_habilita_la_captura_con_un_espacio_valido(self):
        workspace = {"id": "espacio-1", "name": "Obras 2026"}
        database = WorkspaceDatabaseStub([workspace])
        context = DesktopSessionContext(user={"id": "operador-1"})

        with self.assertRaisesRegex(CaptureContextError, WORKSPACE_REQUIRED_ERROR):
            validate_selected_workspace(database, context)

        context.set_workspace(workspace)
        context.start_session("captura-1")
        selected_workspace, session_id = require_active_capture_context(database, context)

        self.assertEqual(selected_workspace["id"], "espacio-1")
        self.assertEqual(session_id, "captura-1")

    def test_rendimiento_valida_mil_ciclos_sin_bloqueos(self):
        workspace = {"id": "espacio-1", "name": "Obras 2026"}
        database = WorkspaceDatabaseStub([workspace])
        context = DesktopSessionContext(
            user={"id": "operador-1"},
            workspace=workspace,
            session_id="captura-1",
        )
        started_at = time.perf_counter()

        for _ in range(1000):
            require_active_capture_context(database, context)

        elapsed_seconds = time.perf_counter() - started_at

        self.assertEqual(database.calls, 1000)
        self.assertLess(elapsed_seconds, 5)

    def test_aceptacion_revoca_el_espacio_y_vuelve_a_bloquear(self):
        workspace = {"id": "espacio-1", "name": "Obras 2026"}
        database = WorkspaceDatabaseStub([workspace])
        context = DesktopSessionContext(user={"id": "operador-1"})
        context.set_workspace(workspace)
        context.start_session("captura-1")

        self.assertEqual(require_active_capture_context(database, context)[1], "captura-1")

        context.end_session()
        database.workspaces.clear()

        with self.assertRaisesRegex(CaptureContextError, WORKSPACE_NOT_ASSIGNED_ERROR):
            validate_selected_workspace(database, context)

        self.assertIsNone(context.workspace)
        with self.assertRaisesRegex(CaptureContextError, SESSION_REQUIRED_ERROR):
            require_active_capture_context(database, context)


if __name__ == "__main__":
    unittest.main()

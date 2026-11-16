"""Estado y reglas de acceso para una sesión de captura de escritorio (RF-03)."""

# RF-03

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


ERROR_USUARIO_REQUERIDO = "Debes iniciar sesión primero."
ERROR_ESPACIO_REQUERIDO = "Debes seleccionar un espacio de trabajo primero."
ERROR_ESPACIO_NO_ASIGNADO = (
    "El espacio seleccionado ya no está asignado al usuario. Selecciona un espacio válido."
)
ERROR_SESION_REQUERIDA = "Inicia una sesión primero."
ERROR_SESION_YA_ACTIVA = "Ya existe una sesión de escaneo activa."
ERROR_ESPACIO_BLOQUEADO = "No puedes cambiar de espacio mientras exista una sesión de escaneo activa."


class ErrorContextoCaptura(Exception):
    """Error esperado al incumplir una precondición del contexto de captura."""


@dataclass
class ContextoSesionEscritorio:
    """Encapsula el usuario, el espacio de trabajo y la sesión activa sin exponer variables globales independientes."""

    user: Optional[Dict[str, Any]] = None
    workspace: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None

    # Indica si existe una sesión de captura activa.
    @property
    def tiene_sesion_activa(self) -> bool:
        return self.session_id is not None

    # Elimina el usuario, el espacio seleccionado y la sesión local.
    def restablecer(self) -> None:
        self.user = None
        self.workspace = None
        self.session_id = None

    # Inicia el contexto de un usuario y descarta selecciones anteriores.
    def establecer_usuario(self, user: Dict[str, Any]) -> None:
        self.user = user
        self.workspace = None
        self.session_id = None

    # Selecciona un espacio siempre que la captura no haya comenzado.
    def establecer_espacio_trabajo(self, workspace: Dict[str, Any]) -> None:
        if self.tiene_sesion_activa:
            raise ErrorContextoCaptura(ERROR_ESPACIO_BLOQUEADO)
        self.workspace = workspace

    # Registra el identificador de una nueva sesión de captura.
    def iniciar_sesion(self, session_id: str) -> None:
        if self.tiene_sesion_activa:
            raise ErrorContextoCaptura(ERROR_SESION_YA_ACTIVA)
        self.session_id = session_id

    # Finaliza la sesión sin descartar el usuario ni el espacio seleccionado.
    def finalizar_sesion(self) -> None:
        self.session_id = None


def buscar_espacio_asignado(db, context: ContextoSesionEscritorio, workspace_id: str):
    """Devuelve el espacio solicitado solo si sigue asignado al usuario autenticado."""
    if not context.user:
        raise ErrorContextoCaptura(ERROR_USUARIO_REQUERIDO)

    assigned_workspaces = db.get_user_workspaces(context.user["id"])
    return next(
        (workspace for workspace in assigned_workspaces if workspace.get("id") == workspace_id),
        None,
    )


def validar_espacio_seleccionado(db, context: ContextoSesionEscritorio):
    """Revalida la selección contra permisos vigentes antes de permitir captura."""
    if not context.user:
        raise ErrorContextoCaptura(ERROR_USUARIO_REQUERIDO)
    if not context.workspace:
        raise ErrorContextoCaptura(ERROR_ESPACIO_REQUERIDO)

    assigned_workspace = buscar_espacio_asignado(db, context, context.workspace["id"])
    if not assigned_workspace:
        context.workspace = None
        raise ErrorContextoCaptura(ERROR_ESPACIO_NO_ASIGNADO)

    # Actualiza metadatos y credenciales del espacio sin permitir cambiar su identidad.
    context.workspace = assigned_workspace
    return assigned_workspace


def exigir_contexto_captura_activo(db, context: ContextoSesionEscritorio) -> Tuple[Dict[str, Any], str]:
    """Exige una sesión activa y un espacio vigente; devuelve ambos valores explícitamente."""
    if not context.tiene_sesion_activa:
        raise ErrorContextoCaptura(ERROR_SESION_REQUERIDA)

    workspace = validar_espacio_seleccionado(db, context)
    return workspace, context.session_id

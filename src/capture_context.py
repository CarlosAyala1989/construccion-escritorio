"""Estado y reglas de acceso para una sesión de captura de escritorio (RF-03)."""

# RF-03

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


USER_REQUIRED_ERROR = "Debes iniciar sesión primero."
WORKSPACE_REQUIRED_ERROR = "Debes seleccionar un espacio de trabajo primero."
WORKSPACE_NOT_ASSIGNED_ERROR = (
    "El espacio seleccionado ya no está asignado al usuario. Selecciona un espacio válido."
)
SESSION_REQUIRED_ERROR = "Inicia una sesión primero."
SESSION_ALREADY_ACTIVE_ERROR = "Ya existe una sesión de escaneo activa."
WORKSPACE_LOCKED_ERROR = "No puedes cambiar de espacio mientras exista una sesión de escaneo activa."


class CaptureContextError(Exception):
    """Error esperado al incumplir una precondición del contexto de captura."""


@dataclass
class DesktopSessionContext:
    """Encapsula el usuario, el espacio de trabajo y la sesión activa sin exponer variables globales independientes."""

    user: Optional[Dict[str, Any]] = None
    workspace: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None

    @property
    def has_active_session(self) -> bool:
        return self.session_id is not None

    def reset(self) -> None:
        self.user = None
        self.workspace = None
        self.session_id = None

    def set_user(self, user: Dict[str, Any]) -> None:
        self.user = user
        self.workspace = None
        self.session_id = None

    def set_workspace(self, workspace: Dict[str, Any]) -> None:
        if self.has_active_session:
            raise CaptureContextError(WORKSPACE_LOCKED_ERROR)
        self.workspace = workspace

    def start_session(self, session_id: str) -> None:
        if self.has_active_session:
            raise CaptureContextError(SESSION_ALREADY_ACTIVE_ERROR)
        self.session_id = session_id

    def end_session(self) -> None:
        self.session_id = None


def find_assigned_workspace(db, context: DesktopSessionContext, workspace_id: str):
    """Devuelve el espacio solicitado solo si sigue asignado al usuario autenticado."""
    if not context.user:
        raise CaptureContextError(USER_REQUIRED_ERROR)

    assigned_workspaces = db.get_user_workspaces(context.user["id"])
    return next(
        (workspace for workspace in assigned_workspaces if workspace.get("id") == workspace_id),
        None,
    )


def validate_selected_workspace(db, context: DesktopSessionContext):
    """Revalida la selección contra permisos vigentes antes de permitir captura."""
    if not context.user:
        raise CaptureContextError(USER_REQUIRED_ERROR)
    if not context.workspace:
        raise CaptureContextError(WORKSPACE_REQUIRED_ERROR)

    assigned_workspace = find_assigned_workspace(db, context, context.workspace["id"])
    if not assigned_workspace:
        context.workspace = None
        raise CaptureContextError(WORKSPACE_NOT_ASSIGNED_ERROR)

    # Actualiza metadatos y credenciales del espacio sin permitir cambiar su identidad.
    context.workspace = assigned_workspace
    return assigned_workspace


def require_active_capture_context(db, context: DesktopSessionContext) -> Tuple[Dict[str, Any], str]:
    """Exige una sesión activa y un espacio vigente; devuelve ambos valores explícitamente."""
    if not context.has_active_session:
        raise CaptureContextError(SESSION_REQUIRED_ERROR)

    workspace = validate_selected_workspace(db, context)
    return workspace, context.session_id

"""
Database Manager — Conecta al MySQL remoto y al SQLite local.
La BD MySQL remota es la fuente de verdad para configuración.
SQLite local es para la cola de pendientes y caché offline.
"""

import json
import logging
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime
from urllib.parse import unquote, urlparse

import mysql.connector
import pyotp

from src.app_paths import BASE_DIR, DATA_DIR, ensure_runtime_dirs
from src.core.local_crypto import (
    decrypt_local_payload,
    encrypt_local_payload,
    is_encrypted_local_payload,
)

# Rutas locales
REPO_ROOT = os.path.dirname(BASE_DIR)
ensure_runtime_dirs()
SQLITE_PATH = os.path.join(DATA_DIR, "local_queue.db")
DEFAULT_MYSQL_PORT = 3306
DEFAULT_COMPRESSION_THRESHOLD_MB = 10
TOTP_DIGITS = 6
TOTP_INTERVAL_SECONDS = 30
TOTP_VALID_WINDOWS = 1


def _parse_dotenv_file(path):
    values = {}
    if not os.path.exists(path):
        return values

    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value[0] in {'"', "'"}
            ):
                value = value[1:-1]
            values[key] = value

    return values


def _load_env():
    env = {}
    for env_path in [
        os.path.join(REPO_ROOT, "construccion-web", ".env"),
        os.path.join(REPO_ROOT, "construccion-web", ".env.local"),
        os.path.join(REPO_ROOT, ".env"),
        os.path.join(BASE_DIR, ".env"),
        os.path.join(DATA_DIR, ".env"),
    ]:
        env.update(_parse_dotenv_file(env_path))

    env.update(os.environ)
    return env


def _env_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mysql_config_from_env():
    env = _load_env()
    database_url = env.get("DATABASE_URL", "").strip()

    if database_url:
        parsed = urlparse(database_url)
        if parsed.scheme in {"mysql", "mariadb"}:
            return {
                "host": parsed.hostname or "",
                "port": parsed.port or DEFAULT_MYSQL_PORT,
                "user": unquote(parsed.username or ""),
                "password": unquote(parsed.password or ""),
                "database": unquote(parsed.path.lstrip("/")),
            }

    return {
        "host": env.get("MYSQL_HOST") or env.get("DB_HOST") or "",
        "port": _env_int(
            env.get("MYSQL_PORT") or env.get("DB_PORT"),
            DEFAULT_MYSQL_PORT,
        ),
        "user": env.get("MYSQL_USER") or env.get("DB_USER") or "",
        "password": env.get("MYSQL_PASSWORD") or env.get("DB_PASSWORD") or "",
        "database": env.get("MYSQL_DATABASE") or env.get("DB_NAME") or "",
    }


class AuthenticationError(Exception):
    """Fallo de autenticación esperado que puede mostrarse al usuario."""


def _verify_totp_code(secret, code):
    """Verifica un TOTP de seis dígitos con la misma ventana de 30 segundos que la web."""
    normalized_code = re.sub(r"\s+", "", str(code or ""))
    if not secret or not re.fullmatch(rf"\d{{{TOTP_DIGITS}}}", normalized_code):
        return False

    try:
        return pyotp.TOTP(
            secret,
            digits=TOTP_DIGITS,
            interval=TOTP_INTERVAL_SECONDS,
        ).verify(
            normalized_code,
            valid_window=TOTP_VALID_WINDOWS,
        )
    except Exception as error:
        logging.getLogger(__name__).debug("No se pudo evaluar el código TOTP.", exc_info=error)
        return False


class DatabaseManager:
    """Administra la base de datos de una instancia de la aplicación de escritorio."""

    # RF-13/RF-17 — Aísla configuración y conexiones al ciclo de vida de esta instancia.
    def __init__(self):
        ensure_runtime_dirs()
        self._mysql_config = _mysql_config_from_env()
        self._mysql_connections = threading.local()
        self._init_sqlite()

    # ─── SQLite (local) ────────────────────────────────

    def _init_sqlite(self):
        """Crea tablas SQLite locales para la cola y la caché sin conexión."""
        conn = sqlite3.connect(SQLITE_PATH)
        c = conn.cursor()

        # Cola local de procesamiento de documentos.
        c.execute("""
            CREATE TABLE IF NOT EXISTS local_queue (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                original_name TEXT NOT NULL,
                workspace_id TEXT,
                workspace_name TEXT,
                status TEXT DEFAULT 'PENDING',
                encryption_type TEXT,
                encryption_password TEXT,
                policy_id TEXT,
                error_message TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Configuración de MySQL en caché (prioridad al modo sin conexión).
        c.execute("""
            CREATE TABLE IF NOT EXISTS cached_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Búfer local de bitácora (se sincroniza con MySQL al conectarse).
        c.execute("""
            CREATE TABLE IF NOT EXISTS local_audit_log (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                user_name TEXT,
                action TEXT NOT NULL,
                details TEXT,
                status TEXT DEFAULT 'SUCCESS',
                workspace_id TEXT,
                synced INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Seguimiento de sesiones.
        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                workspace_id TEXT,
                workspace_name TEXT,
                status TEXT DEFAULT 'ACTIVE',
                doc_count INTEGER DEFAULT 0,
                started_at TEXT DEFAULT (datetime('now')),
                ended_at TEXT
            )
        """)

        self._encrypt_legacy_audit_logs(c)

        conn.commit()
        conn.close()

    # RF-16 — Migra registros históricos a sobres autenticados y conserva trazabilidad.
    def _encrypt_legacy_audit_logs(self, cursor):
        """Migra registros de bitácora legibles antiguos sin cambiar el esquema SQLite."""
        rows = cursor.execute(
            "SELECT * FROM local_audit_log WHERE details IS NULL OR details NOT LIKE ?",
            ("DZENC1:%",),
        ).fetchall()
        column_names = [column[0] for column in cursor.description]

        for row in rows:
            values = dict(zip(column_names, row))
            encrypted_payload = encrypt_local_payload({
                "user_id": values.get("user_id"),
                "user_name": values.get("user_name"),
                "action": values.get("action"),
                "details": values.get("details"),
                "status": values.get("status") or "SUCCESS",
                "workspace_id": values.get("workspace_id"),
            })
            cursor.execute(
                """UPDATE local_audit_log
                   SET user_id = NULL,
                       user_name = NULL,
                       action = 'ENCRYPTED',
                       details = ?,
                       status = 'ENCRYPTED',
                       workspace_id = NULL
                   WHERE id = ?""",
                (encrypted_payload, values["id"]),
            )

    def get_sqlite(self):
        """Abre una conexión nueva a SQLite."""
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    # ─── MySQL (remoto) ───────────────────────────────

    # RF-13/RF-17 — Reutiliza la conexión por hilo y pasa al modo sin conexión si falla.
    def get_mysql(self):
        """Obtiene la conexión MySQL y vuelve a conectarse si es necesario."""
        required_config = ("host", "user", "database")
        if not all(self._mysql_config.get(key) for key in required_config):
            logging.getLogger(__name__).debug("Falta configuración MySQL; se usará la caché local.")
            return None

        try:
            connection = getattr(self._mysql_connections, "connection", None)
            if connection is None or not connection.is_connected():
                connection = mysql.connector.connect(**self._mysql_config)
                self._mysql_connections.connection = connection
            return connection
        except mysql.connector.Error as error:
            logging.getLogger(__name__).warning("No se pudo conectar con MySQL: %s", error)
            return None

    # RF-13/RF-17 — Devuelve conectividad remota sin ocultar fallos inesperados.
    def is_online(self):
        """Comprueba si se puede acceder a MySQL."""
        try:
            conn = self.get_mysql()
            if conn and conn.is_connected():
                return True
        except mysql.connector.Error as error:
            logging.getLogger(__name__).debug("No se pudo comprobar la conexión MySQL: %s", error)
        return False

    # ─── Autenticación ─────────────────────────────────

    def authenticate_user(self, email, password, totp_code):
        """Autentica a un usuario de escritorio con contraseña y TOTP administrado."""
        import bcrypt
        conn = self.get_mysql()
        if not conn:
            raise ConnectionError("No se pudo conectar con la base de datos.")

        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, name, email, password, role, isActive, accessRole,
                   twoFactorEnabled, twoFactorSecret
            FROM User
            WHERE email = %s
            """,
            (email,)
        )
        user = cursor.fetchone()
        cursor.close()

        if not user:
            raise AuthenticationError("Credenciales inválidas o cuenta desactivada.")
        if not user["isActive"]:
            raise AuthenticationError("Credenciales inválidas o cuenta desactivada.")
        if user.get("accessRole") != "DESKTOP_SCANNER":
            raise AuthenticationError("Esta cuenta no tiene acceso a la aplicación de escritorio.")

        # Verifica la contraseña con bcrypt.
        if not bcrypt.checkpw(password.encode("utf-8"), user["password"].encode("utf-8")):
            raise AuthenticationError("Credenciales inválidas o cuenta desactivada.")

        if not user.get("twoFactorEnabled") or not user.get("twoFactorSecret"):
            raise AuthenticationError(
                "Authenticator no está configurado para esta cuenta. "
                "Solicita al administrador activarlo."
            )

        if not _verify_totp_code(user["twoFactorSecret"], totp_code):
            raise AuthenticationError("Código de Authenticator inválido o vencido.")

        return {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
        }

    # ─── Espacios de trabajo ───────────────────────────

    # RF-03 — Devuelve espacios asignados y usa la caché si MySQL no responde.
    def get_user_workspaces(self, user_id):
        """Devuelve los espacios de trabajo asignados a un usuario."""
        conn = self.get_mysql()
        if not conn:
            # Recurre a la caché como alternativa.
            return self._get_cached("workspaces", [])

        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT w.id, w.name, w.cloudPath, w.defaultPassword,
                       w.cloudFolderId, w.cloudRefreshToken
                FROM Workspace w
                INNER JOIN _UserWorkspaces uw ON uw.B = w.id
                WHERE uw.A = %s
                ORDER BY w.name ASC
            """, (user_id,))
            workspaces = cursor.fetchall()
        except mysql.connector.Error as error:
            logging.getLogger(__name__).warning("Falló la consulta de espacios; se usará caché: %s", error)
            return self._get_cached("workspaces", [])
        finally:
            if cursor:
                cursor.close()

        # Guarda los datos en caché para usarlos sin conexión.
        self._set_cached("workspaces", json.dumps(workspaces))
        return workspaces

    # RF-03 — Busca el espacio seleccionado y conserva la alternativa local.
    def get_workspace(self, workspace_id):
        """Obtiene un espacio de MySQL o recurre a la última caché válida."""
        if not workspace_id:
            return None

        conn = self.get_mysql()
        if conn:
            cursor = None
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    """SELECT id, name, cloudPath, defaultPassword,
                              cloudFolderId, cloudRefreshToken
                       FROM Workspace
                       WHERE id = %s""",
                    (workspace_id,),
                )
                workspace = cursor.fetchone()
                if workspace:
                    return workspace
            except mysql.connector.Error as error:
                logging.getLogger(__name__).warning("Falló la consulta del espacio; se usará caché: %s", error)
            finally:
                if cursor:
                    cursor.close()

        cached_workspaces = self._get_cached("workspaces", [])
        return next(
            (
                workspace
                for workspace in cached_workspaces
                if workspace.get("id") == workspace_id
            ),
            None,
        )

    # ─── Políticas de seguridad ────────────────────────

    # RF-10 — Recupera reglas de seguridad y conserva la caché sin conexión.
    def get_security_policies(self):
        """Devuelve todas las políticas de seguridad de MySQL."""
        conn = self.get_mysql()
        if not conn:
            return self._get_cached("policies", [])

        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT id, type, target, password, priority, workspaceId
                FROM SecurityPolicy
                ORDER BY priority DESC
            """)
            policies = cursor.fetchall()
        except mysql.connector.Error as error:
            logging.getLogger(__name__).warning("Falló la consulta de políticas; se usará caché: %s", error)
            return self._get_cached("policies", [])
        finally:
            if cursor:
                cursor.close()

        self._set_cached("policies", json.dumps(policies))
        return policies

    # ─── Configuración ─────────────────────────────────

    # RF-13/RF-15 — Recupera parámetros de operación en nube y compresión.
    def get_config(self):
        """Devuelve la configuración del sistema desde MySQL."""
        conn = self.get_mysql()
        if not conn:
            return self._get_cached("config", {
                "compressionEnabled": False,
                "compressionThresholdMb": DEFAULT_COMPRESSION_THRESHOLD_MB,
                "deleteLocalAfterUpload": False,
                "cloudProvider": "MANUAL",
            })

        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM Config LIMIT 1")
            config = cursor.fetchone()
        except mysql.connector.Error as error:
            logging.getLogger(__name__).warning("Falló la consulta de configuración; se usará caché: %s", error)
            return self._get_cached("config", {
                "compressionEnabled": False,
                "compressionThresholdMb": DEFAULT_COMPRESSION_THRESHOLD_MB,
                "deleteLocalAfterUpload": False,
                "cloudProvider": "MANUAL",
            })
        finally:
            if cursor:
                cursor.close()

        if config:
            # Convierte valores booleanos.
            config["compressionEnabled"] = bool(config.get("compressionEnabled", 0))
            config["deleteLocalAfterUpload"] = bool(config.get("deleteLocalAfterUpload", 0))
            self._set_cached("config", json.dumps(config, default=str))
            return config

        return {
            "compressionEnabled": False,
            "compressionThresholdMb": DEFAULT_COMPRESSION_THRESHOLD_MB,
            "deleteLocalAfterUpload": False,
            "cloudProvider": "MANUAL",
        }

    # RF-13 — Devuelve credenciales de Drive solo si la configuración es válida.
    def get_google_credentials(self):
        """Devuelve las credenciales del cliente OAuth de Google desde Config.cloudCredentials."""
        config = self.get_config()
        creds_json = config.get("cloudCredentials", "")
        if creds_json:
            try:
                creds = json.loads(creds_json)
                return {
                    "googleClientId": creds.get("clientId", ""),
                    "googleClientSecret": creds.get("clientSecret", ""),
                }
            except (json.JSONDecodeError, TypeError):
                logging.getLogger(__name__).warning(
                    "La configuración de credenciales de Google no contiene JSON válido."
                )
        return {"googleClientId": "", "googleClientSecret": ""}

    # ─── Nomenclaturas ─────────────────────────────────

    # RF-06 — Recupera campos de nomenclatura y usa caché si no hay conexión.
    def get_nomenclatures(self):
        """Devuelve los campos de nomenclatura desde MySQL."""
        conn = self.get_mysql()
        if not conn:
            return self._get_cached("nomenclatures", [])

        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM NomenclatureField ORDER BY fieldOrder ASC")
            fields = cursor.fetchall()
        except mysql.connector.Error as error:
            logging.getLogger(__name__).warning("Falló la consulta de nomenclaturas; se usará caché: %s", error)
            return self._get_cached("nomenclatures", [])
        finally:
            if cursor:
                cursor.close()

        self._set_cached("nomenclatures", json.dumps(fields, default=str))
        return fields

    # ─── Bitácoras de auditoría ────────────────────────

    # RF-16 — Persiste auditoría cifrada localmente y conserva el registro remoto si está disponible.
    def create_audit_log(self, user_id, user_name, action, details, status="SUCCESS", workspace_id=None):
        """Crea una bitácora local cifrada con AES-GCM y luego intenta guardarla en SaaS."""
        log_id = str(uuid.uuid4())

        encrypted_payload = encrypt_local_payload({
            "user_id": user_id,
            "user_name": user_name,
            "action": action,
            "details": details,
            "status": status,
            "workspace_id": workspace_id,
        })

        # Guarda localmente solo el sobre cifrado. Los metadatos de búsqueda se
        # reconstruyen en memoria justo antes de la sincronización.
        sqlite_conn = self.get_sqlite()
        sqlite_conn.execute(
            """INSERT INTO local_audit_log (id, user_id, user_name, action, details, status, workspace_id, synced)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (log_id, None, None, "ENCRYPTED", encrypted_payload, "ENCRYPTED", None)
        )
        sqlite_conn.commit()
        sqlite_conn.close()

        # Intenta sincronizar con MySQL.
        conn = self.get_mysql()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO AuditLog (id, userId, userName, action, details, status, workspaceId, createdAt)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (log_id, user_id, user_name, action, details, status, workspace_id,
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S.000"))
                )
                conn.commit()
                cursor.close()

                # Marca el registro como sincronizado.
                sqlite_conn = self.get_sqlite()
                sqlite_conn.execute("UPDATE local_audit_log SET synced = 1 WHERE id = ?", (log_id,))
                sqlite_conn.commit()
                sqlite_conn.close()
            except Exception as e:
                logging.getLogger(__name__).warning("No se pudo replicar la bitácora a MySQL: %s", e)

    # RF-17 — Reintenta cada bitácora pendiente y registra fallos sin detener el lote.
    def sync_pending_logs(self):
        """Sincroniza con MySQL las bitácoras pendientes de SQLite."""
        conn = self.get_mysql()
        if not conn:
            return 0

        sqlite_conn = self.get_sqlite()
        pending = sqlite_conn.execute(
            "SELECT * FROM local_audit_log WHERE synced = 0"
        ).fetchall()

        synced_count = 0
        for log in pending:
            try:
                log_data = self._read_audit_log_payload(log)
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO AuditLog (id, userId, userName, action, details, status, workspaceId, createdAt)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE id = id""",
                    (log["id"], log_data["user_id"], log_data["user_name"], log_data["action"],
                     log_data["details"], log_data["status"], log_data["workspace_id"], log["created_at"])
                )
                conn.commit()
                cursor.close()

                sqlite_conn.execute("UPDATE local_audit_log SET synced = 1 WHERE id = ?", (log["id"],))
                synced_count += 1
            except Exception as e:
                logging.getLogger(__name__).warning("Falló la sincronización de la bitácora %s: %s", log["id"], e)

        sqlite_conn.commit()
        sqlite_conn.close()
        return synced_count

    @staticmethod
    def _read_audit_log_payload(log):
        """Lee filas cifradas y conserva la compatibilidad con colas antiguas."""
        if is_encrypted_local_payload(log["details"]):
            payload = decrypt_local_payload(log["details"])
            required_fields = {
                "user_id",
                "user_name",
                "action",
                "details",
                "status",
                "workspace_id",
            }
            if not isinstance(payload, dict) or not required_fields.issubset(payload):
                raise ValueError("Bitácora cifrada incompleta.")
            return payload

        return {
            "user_id": log["user_id"],
            "user_name": log["user_name"],
            "action": log["action"],
            "details": log["details"],
            "status": log["status"],
            "workspace_id": log["workspace_id"],
        }

    # ─── Cola local ────────────────────────────────────

    def add_to_queue(self, file_path, original_name, workspace_id=None, workspace_name=None):
        """Añade un documento a la cola local de procesamiento."""
        doc_id = str(uuid.uuid4())
        conn = self.get_sqlite()
        conn.execute(
            """INSERT INTO local_queue (id, file_path, original_name, workspace_id, workspace_name)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, file_path, original_name, workspace_id, workspace_name)
        )
        conn.commit()
        conn.close()
        return doc_id

    def update_queue_item(self, doc_id, **kwargs):
        """Actualiza cualquier campo de un elemento de la cola."""
        allowed_fields = {
            "file_path",
            "original_name",
            "workspace_id",
            "workspace_name",
            "status",
            "encryption_type",
            "encryption_password",
            "policy_id",
            "error_message",
        }
        invalid_fields = set(kwargs) - allowed_fields
        if invalid_fields:
            raise ValueError(f"Campos de cola no válidos: {', '.join(sorted(invalid_fields))}")

        conn = self.get_sqlite()
        sets = []
        values = []
        for key, val in kwargs.items():
            sets.append(f"{key} = ?")
            values.append(val)
        sets.append("updated_at = datetime('now')")
        values.append(doc_id)

        conn.execute(f"UPDATE local_queue SET {', '.join(sets)} WHERE id = ?", values)
        conn.commit()
        conn.close()

    def get_queue_item(self, doc_id):
        """Devuelve un elemento de la cola por su identificador estable."""
        conn = self.get_sqlite()
        item = conn.execute(
            "SELECT * FROM local_queue WHERE id = ?",
            (doc_id,),
        ).fetchone()
        conn.close()
        return dict(item) if item else None

    def get_queue_items(self, status=None):
        """Devuelve elementos de la cola, con filtro opcional por estado."""
        conn = self.get_sqlite()
        if status:
            items = conn.execute(
                "SELECT * FROM local_queue WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            items = conn.execute(
                "SELECT * FROM local_queue ORDER BY created_at DESC"
            ).fetchall()
        conn.close()
        return [dict(i) for i in items]

    # RF-08 — Limita la consulta a documentos que requieren revisión manual.
    def get_pending_review(self):
        """Devuelve los elementos que requieren revisión manual."""
        return self.get_queue_items(status="PENDING_REVIEW")

    # ─── Sesiones ──────────────────────────────────────

    def create_session(self, user_id, workspace_id=None, workspace_name=None):
        """Crea una nueva sesión de escaneo."""
        session_id = str(uuid.uuid4())
        conn = self.get_sqlite()
        conn.execute(
            """INSERT INTO sessions (id, user_id, workspace_id, workspace_name)
               VALUES (?, ?, ?, ?)""",
            (session_id, user_id, workspace_id, workspace_name)
        )
        conn.commit()
        conn.close()
        return session_id

    def close_session(self, session_id):
        """Cierra una sesión de escaneo."""
        conn = self.get_sqlite()
        conn.execute(
            "UPDATE sessions SET status = 'CLOSED', ended_at = datetime('now') WHERE id = ?",
            (session_id,)
        )
        conn.commit()
        conn.close()

    def get_active_session(self, user_id):
        """Devuelve la sesión activa de un usuario."""
        conn = self.get_sqlite()
        session = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? AND status = 'ACTIVE' ORDER BY started_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        conn.close()
        return dict(session) if session else None

    def increment_session_doc_count(self, session_id):
        """Aumenta el conteo de documentos de una sesión."""
        conn = self.get_sqlite()
        conn.execute("UPDATE sessions SET doc_count = doc_count + 1 WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()

    # ─── Ayudantes de caché ────────────────────────────

    def _set_cached(self, key, value):
        conn = self.get_sqlite()
        conn.execute(
            "INSERT OR REPLACE INTO cached_config (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            (key, value)
        )
        conn.commit()
        conn.close()

    def _get_cached(self, key, default=None):
        conn = self.get_sqlite()
        row = conn.execute("SELECT value FROM cached_config WHERE key = ?", (key,)).fetchone()
        conn.close()
        if row:
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return row["value"]
        return default

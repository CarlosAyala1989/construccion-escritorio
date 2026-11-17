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

from src.app_paths import BASE_DIR, DATA_DIR, asegurar_directorios_ejecucion
from src.core.local_crypto import (
    descifrar_contenido_local,
    cifrar_contenido_local,
    es_contenido_local_cifrado,
)
from src.database.mysql_secrets import descifrar_campo_secreto

# Rutas locales
REPO_ROOT = os.path.dirname(BASE_DIR)
asegurar_directorios_ejecucion()
SQLITE_PATH = os.path.join(DATA_DIR, "local_queue.db")
DEFAULT_MYSQL_PORT = 3306
DEFAULT_COMPRESSION_THRESHOLD_MB = 10
TOTP_DIGITS = 6
TOTP_INTERVAL_SECONDS = 30
TOTP_VALID_WINDOWS = 1


# Interpreta dotenv archivo según las reglas del componente.
def _analizar_archivo_entorno(path):
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


# Carga env según las reglas del componente.
def _cargar_entorno():
    env = {}
    for env_path in [
        os.path.join(REPO_ROOT, ".env"),
        os.path.join(BASE_DIR, ".env"),
        os.path.join(DATA_DIR, ".env"),
    ]:
        env.update(_analizar_archivo_entorno(env_path))

    env.update(os.environ)
    return env


# Convierte una variable de entorno a entero o devuelve el valor predeterminado.
def _entero_entorno(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# Construye la configuración de MySQL a partir de variables de entorno.
def _configuracion_mysql_desde_entorno():
    env = _cargar_entorno()
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
        "port": _entero_entorno(
            env.get("MYSQL_PORT") or env.get("DB_PORT"),
            DEFAULT_MYSQL_PORT,
        ),
        "user": env.get("MYSQL_USER") or env.get("DB_USER") or "",
        "password": env.get("MYSQL_PASSWORD") or env.get("DB_PASSWORD") or "",
        "database": env.get("MYSQL_DATABASE") or env.get("DB_NAME") or "",
    }


class ErrorAutenticacion(Exception):
    """Fallo de autenticación esperado que puede mostrarse al usuario."""


def _verificar_codigo_totp(secret, code):
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


class AdministradorBaseDatos:
    """Administra la base de datos de una instancia de la aplicación de escritorio."""

    # RF-13/RF-17 — Aísla configuración y conexiones al ciclo de vida de esta instancia.
    def __init__(self):
        asegurar_directorios_ejecucion()
        self._mysql_config = _configuracion_mysql_desde_entorno()
        self._mysql_connections = threading.local()
        self._inicializar_sqlite()

    # ─── SQLite (local) ────────────────────────────────

    def _inicializar_sqlite(self):
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

        self._cifrar_bitacoras_heredadas(c)
        self._cifrar_cache_heredada(c)
        self._cifrar_claves_cola_heredadas(c)

        conn.commit()
        conn.close()

    # RF-16 — Migra registros históricos a sobres autenticados y conserva trazabilidad.
    def _cifrar_bitacoras_heredadas(self, cursor):
        """Migra registros de bitácora legibles antiguos sin cambiar el esquema SQLite."""
        rows = cursor.execute(
            "SELECT * FROM local_audit_log WHERE details IS NULL OR details NOT LIKE ?",
            ("DZENC1:%",),
        ).fetchall()
        column_names = [column[0] for column in cursor.description]

        for row in rows:
            values = dict(zip(column_names, row))
            encrypted_payload = cifrar_contenido_local({
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

    def _cifrar_cache_heredada(self, cursor):
        """Migra la caché JSON histórica a sobres AES-GCM autenticados."""
        rows = cursor.execute(
            "SELECT key, value FROM cached_config WHERE value NOT LIKE ?",
            ("DZENC1:%",),
        ).fetchall()
        for key, value in rows:
            cursor.execute(
                "UPDATE cached_config SET value = ? WHERE key = ?",
                (cifrar_contenido_local(value), key),
            )

    def _cifrar_claves_cola_heredadas(self, cursor):
        """Cifra contraseñas de cola antiguas que aún estuvieran en claro."""
        rows = cursor.execute(
            """SELECT id, encryption_password FROM local_queue
               WHERE encryption_password IS NOT NULL
                 AND encryption_password NOT LIKE ?""",
            ("DZENC1:%",),
        ).fetchall()
        for item_id, password in rows:
            cursor.execute(
                "UPDATE local_queue SET encryption_password = ? WHERE id = ?",
                (cifrar_contenido_local(password), item_id),
            )

    def obtener_sqlite(self):
        """Abre una conexión nueva a SQLite."""
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    # ─── MySQL (remoto) ───────────────────────────────

    # RF-13/RF-17 — Reutiliza la conexión por hilo y pasa al modo sin conexión si falla.
    def obtener_mysql(self):
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
    def esta_en_linea(self):
        """Comprueba si se puede acceder a MySQL."""
        try:
            conn = self.obtener_mysql()
            if conn and conn.is_connected():
                return True
        except mysql.connector.Error as error:
            logging.getLogger(__name__).debug("No se pudo comprobar la conexión MySQL: %s", error)
        return False

    # ─── Autenticación ─────────────────────────────────

    def autenticar_usuario(self, email, password, totp_code):
        """Autentica a un usuario de escritorio con contraseña y TOTP administrado."""
        import bcrypt
        conn = self.obtener_mysql()
        if not conn:
            raise ConnectionError("No se pudo conectar con la base de datos.")

        # Evita autenticar contra una instantánea abierta por una operación
        # previa del mismo hilo (por ejemplo, justo después de una reasignación).
        conn.rollback()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, name, email, password, role, isActive, accessRole,
                   twoFactorEnabled, twoFactorSecret, authorizationVersion
            FROM User
            WHERE email = %s
            """,
            (email,)
        )
        user = cursor.fetchone()
        cursor.close()

        if not user:
            raise ErrorAutenticacion("Credenciales inválidas o cuenta desactivada.")
        if not user["isActive"]:
            raise ErrorAutenticacion("Credenciales inválidas o cuenta desactivada.")
        if user.get("accessRole") != "DESKTOP_SCANNER":
            raise ErrorAutenticacion("Esta cuenta no tiene acceso a la aplicación de escritorio.")

        # Verifica la contraseña con bcrypt.
        if not bcrypt.checkpw(password.encode("utf-8"), user["password"].encode("utf-8")):
            raise ErrorAutenticacion("Credenciales inválidas o cuenta desactivada.")

        if not user.get("twoFactorEnabled") or not user.get("twoFactorSecret"):
            raise ErrorAutenticacion(
                "Authenticator no está configurado para esta cuenta. "
                "Solicita al administrador activarlo."
            )

        totp_secret = descifrar_campo_secreto(
            "User", "twoFactorSecret", user["id"], user["twoFactorSecret"]
        )
        if not _verificar_codigo_totp(totp_secret, totp_code):
            raise ErrorAutenticacion("Código de Authenticator inválido o vencido.")

        return {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "accessRole": user["accessRole"],
            "authorizationVersion": user.get("authorizationVersion", 1),
        }

    def validar_sesion_usuario(self, user):
        """Revalida en MySQL una sesión abierta; nunca usa caché para autorización."""
        if not user or not user.get("id"):
            raise ErrorAutenticacion("Debes iniciar sesión primero.")

        conn = self.obtener_mysql()
        if not conn:
            raise ConnectionError("No se pudo verificar la autorización vigente.")

        cursor = None
        try:
            # La conexión se reutiliza por hilo y mysql-connector inicia
            # transacciones de lectura. Cierra cualquier snapshot anterior
            # para que una revocación confirmada por la web sea visible ya.
            conn.rollback()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, name, email, role, isActive, accessRole,
                       authorizationVersion
                FROM User
                WHERE id = %s
                """,
                (user["id"],),
            )
            current_user = cursor.fetchone()
        except mysql.connector.Error as error:
            raise ConnectionError(
                "No se pudo verificar la autorización vigente."
            ) from error
        finally:
            if cursor:
                cursor.close()

        revoked = (
            not current_user
            or not current_user.get("isActive")
            or current_user.get("accessRole") != "DESKTOP_SCANNER"
            or current_user.get("authorizationVersion") != user.get("authorizationVersion")
            or current_user.get("role") != user.get("role")
            or current_user.get("accessRole") != user.get("accessRole")
        )
        if revoked:
            raise ErrorAutenticacion(
                "Tu acceso cambió o fue revocado. Inicia sesión nuevamente."
            )

        return {
            "id": current_user["id"],
            "name": current_user["name"],
            "email": current_user["email"],
            "role": current_user["role"],
            "accessRole": current_user["accessRole"],
            "authorizationVersion": current_user["authorizationVersion"],
        }

    # ─── Espacios de trabajo ───────────────────────────

    # RF-03 — Devuelve espacios asignados y usa la caché si MySQL no responde.
    def obtener_espacios_usuario(self, user_id):
        """Devuelve los espacios de trabajo asignados a un usuario."""
        conn = self.obtener_mysql()
        if not conn:
            # Recurre a la caché como alternativa.
            return self._obtener_cache("workspaces", [])

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
            return self._obtener_cache("workspaces", [])
        finally:
            if cursor:
                cursor.close()

        # Guarda los datos en caché para usarlos sin conexión.
        for workspace in workspaces:
            workspace["defaultPassword"] = descifrar_campo_secreto(
                "Workspace", "defaultPassword", workspace["id"], workspace.get("defaultPassword")
            )
            workspace["cloudRefreshToken"] = descifrar_campo_secreto(
                "Workspace", "cloudRefreshToken", workspace["id"], workspace.get("cloudRefreshToken")
            )
        self._guardar_cache("workspaces", json.dumps(workspaces))
        return workspaces

    # RF-03 — Busca el espacio seleccionado y conserva la alternativa local.
    def obtener_espacio_trabajo(self, workspace_id):
        """Obtiene un espacio de MySQL o recurre a la última caché válida."""
        if not workspace_id:
            return None

        conn = self.obtener_mysql()
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
                    workspace["defaultPassword"] = descifrar_campo_secreto(
                        "Workspace", "defaultPassword", workspace["id"], workspace.get("defaultPassword")
                    )
                    workspace["cloudRefreshToken"] = descifrar_campo_secreto(
                        "Workspace", "cloudRefreshToken", workspace["id"], workspace.get("cloudRefreshToken")
                    )
                    return workspace
            except mysql.connector.Error as error:
                logging.getLogger(__name__).warning("Falló la consulta del espacio; se usará caché: %s", error)
            finally:
                if cursor:
                    cursor.close()

        cached_workspaces = self._obtener_cache("workspaces", [])
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
    def obtener_politicas_seguridad(self):
        """Devuelve todas las políticas de seguridad de MySQL."""
        conn = self.obtener_mysql()
        if not conn:
            return self._obtener_cache("policies", [])

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
            return self._obtener_cache("policies", [])
        finally:
            if cursor:
                cursor.close()

        for policy in policies:
            policy["password"] = descifrar_campo_secreto(
                "SecurityPolicy", "password", policy["id"], policy.get("password")
            )
        self._guardar_cache("policies", json.dumps(policies))
        return policies

    # ─── Configuración ─────────────────────────────────

    # RF-13/RF-15 — Recupera parámetros de operación en nube y compresión.
    def get_config(self):
        """Devuelve la configuración del sistema desde MySQL."""
        conn = self.obtener_mysql()
        if not conn:
            return self._obtener_cache("config", {
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
            return self._obtener_cache("config", {
                "compressionEnabled": False,
                "compressionThresholdMb": DEFAULT_COMPRESSION_THRESHOLD_MB,
                "deleteLocalAfterUpload": False,
                "cloudProvider": "MANUAL",
            })
        finally:
            if cursor:
                cursor.close()

        if config:
            config["cloudCredentials"] = descifrar_campo_secreto(
                "Config", "cloudCredentials", config["id"], config.get("cloudCredentials")
            )
            # Convierte valores booleanos.
            config["compressionEnabled"] = bool(config.get("compressionEnabled", 0))
            config["deleteLocalAfterUpload"] = bool(config.get("deleteLocalAfterUpload", 0))
            self._guardar_cache("config", json.dumps(config, default=str))
            return config

        return {
            "compressionEnabled": False,
            "compressionThresholdMb": DEFAULT_COMPRESSION_THRESHOLD_MB,
            "deleteLocalAfterUpload": False,
            "cloudProvider": "MANUAL",
        }

    # RF-13 — Devuelve credenciales de Drive solo si la configuración es válida.
    def obtener_credenciales_google(self):
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
    def obtener_nomenclaturas(self):
        """Devuelve los campos de nomenclatura desde MySQL."""
        conn = self.obtener_mysql()
        if not conn:
            return self._obtener_cache("nomenclatures", [])

        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM NomenclatureField ORDER BY fieldOrder ASC")
            fields = cursor.fetchall()
        except mysql.connector.Error as error:
            logging.getLogger(__name__).warning("Falló la consulta de nomenclaturas; se usará caché: %s", error)
            return self._obtener_cache("nomenclatures", [])
        finally:
            if cursor:
                cursor.close()

        self._guardar_cache("nomenclatures", json.dumps(fields, default=str))
        return fields

    # ─── Bitácoras de auditoría ────────────────────────

    # RF-16 — Persiste auditoría cifrada localmente y conserva el registro remoto si está disponible.
    def crear_bitacora_auditoria(self, user_id, user_name, action, details, status="SUCCESS", workspace_id=None):
        """Crea una bitácora local cifrada con AES-GCM y luego intenta guardarla en SaaS."""
        log_id = str(uuid.uuid4())

        encrypted_payload = cifrar_contenido_local({
            "user_id": user_id,
            "user_name": user_name,
            "action": action,
            "details": details,
            "status": status,
            "workspace_id": workspace_id,
        })

        # Guarda localmente solo el sobre cifrado. Los metadatos de búsqueda se
        # reconstruyen en memoria justo antes de la sincronización.
        sqlite_conn = self.obtener_sqlite()
        sqlite_conn.execute(
            """INSERT INTO local_audit_log (id, user_id, user_name, action, details, status, workspace_id, synced)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (log_id, None, None, "ENCRYPTED", encrypted_payload, "ENCRYPTED", None)
        )
        sqlite_conn.commit()
        sqlite_conn.close()

        # Intenta sincronizar con MySQL.
        conn = self.obtener_mysql()
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
                sqlite_conn = self.obtener_sqlite()
                sqlite_conn.execute("UPDATE local_audit_log SET synced = 1 WHERE id = ?", (log_id,))
                sqlite_conn.commit()
                sqlite_conn.close()
            except Exception as e:
                logging.getLogger(__name__).warning("No se pudo replicar la bitácora a MySQL: %s", e)

    # RF-17 — Reintenta cada bitácora pendiente y registra fallos sin detener el lote.
    def sincronizar_bitacoras_pendientes(self):
        """Sincroniza con MySQL las bitácoras pendientes de SQLite."""
        conn = self.obtener_mysql()
        if not conn:
            return 0

        sqlite_conn = self.obtener_sqlite()
        pending = sqlite_conn.execute(
            "SELECT * FROM local_audit_log WHERE synced = 0"
        ).fetchall()

        synced_count = 0
        for log in pending:
            try:
                log_data = self._leer_contenido_bitacora_auditoria(log)
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
    def _leer_contenido_bitacora_auditoria(log):
        """Lee filas cifradas y conserva la compatibilidad con colas antiguas."""
        if es_contenido_local_cifrado(log["details"]):
            payload = descifrar_contenido_local(log["details"])
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

    def agregar_a_cola(self, file_path, original_name, workspace_id=None, workspace_name=None):
        """Añade un documento a la cola local de procesamiento."""
        doc_id = str(uuid.uuid4())
        conn = self.obtener_sqlite()
        conn.execute(
            """INSERT INTO local_queue (id, file_path, original_name, workspace_id, workspace_name)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, file_path, original_name, workspace_id, workspace_name)
        )
        conn.commit()
        conn.close()
        return doc_id

    def actualizar_elemento_cola(self, doc_id, **kwargs):
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

        conn = self.obtener_sqlite()
        sets = []
        values = []
        for key, val in kwargs.items():
            sets.append(f"{key} = ?")
            if key == "encryption_password" and val is not None:
                val = cifrar_contenido_local(val)
            values.append(val)
        sets.append("updated_at = datetime('now')")
        values.append(doc_id)

        conn.execute(f"UPDATE local_queue SET {', '.join(sets)} WHERE id = ?", values)
        conn.commit()
        conn.close()

    def obtener_elemento_cola(self, doc_id):
        """Devuelve un elemento de la cola por su identificador estable."""
        conn = self.obtener_sqlite()
        item = conn.execute(
            "SELECT * FROM local_queue WHERE id = ?",
            (doc_id,),
        ).fetchone()
        conn.close()
        return self._descifrar_elemento_cola(dict(item)) if item else None

    def get_queue_items(self, status=None):
        """Devuelve elementos de la cola, con filtro opcional por estado."""
        conn = self.obtener_sqlite()
        if status:
            items = conn.execute(
                "SELECT * FROM local_queue WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            items = conn.execute(
                "SELECT * FROM local_queue ORDER BY created_at DESC"
            ).fetchall()
        conn.close()
        return [self._descifrar_elemento_cola(dict(i)) for i in items]

    @staticmethod
    def _descifrar_elemento_cola(item):
        password = item.get("encryption_password")
        if es_contenido_local_cifrado(password):
            item["encryption_password"] = descifrar_contenido_local(password)
        return item

    # RF-08 — Limita la consulta a documentos que requieren revisión manual.
    def obtener_revision_pendiente(self):
        """Devuelve los elementos que requieren revisión manual."""
        return self.get_queue_items(status="PENDING_REVIEW")

    # ─── Sesiones ──────────────────────────────────────

    def crear_sesion(self, user_id, workspace_id=None, workspace_name=None):
        """Crea una nueva sesión de escaneo."""
        session_id = str(uuid.uuid4())
        conn = self.obtener_sqlite()
        conn.execute(
            """INSERT INTO sessions (id, user_id, workspace_id, workspace_name)
               VALUES (?, ?, ?, ?)""",
            (session_id, user_id, workspace_id, workspace_name)
        )
        conn.commit()
        conn.close()
        return session_id

    def cerrar_sesion(self, session_id):
        """Cierra una sesión de escaneo."""
        conn = self.obtener_sqlite()
        conn.execute(
            "UPDATE sessions SET status = 'CLOSED', ended_at = datetime('now') WHERE id = ?",
            (session_id,)
        )
        conn.commit()
        conn.close()

    def obtener_sesion_activa(self, user_id):
        """Devuelve la sesión activa de un usuario."""
        conn = self.obtener_sqlite()
        session = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? AND status = 'ACTIVE' ORDER BY started_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        conn.close()
        return dict(session) if session else None

    def incrementar_cantidad_documentos_sesion(self, session_id):
        """Aumenta el conteo de documentos de una sesión."""
        conn = self.obtener_sqlite()
        conn.execute("UPDATE sessions SET doc_count = doc_count + 1 WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()

    # ─── Ayudantes de caché ────────────────────────────

    def _guardar_cache(self, key, value):
        encrypted_value = cifrar_contenido_local(value)
        conn = self.obtener_sqlite()
        conn.execute(
            "INSERT OR REPLACE INTO cached_config (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            (key, encrypted_value)
        )
        conn.commit()
        conn.close()

    # Obtiene cached según las reglas del componente.
    def _obtener_cache(self, key, default=None):
        conn = self.obtener_sqlite()
        row = conn.execute("SELECT value FROM cached_config WHERE key = ?", (key,)).fetchone()
        conn.close()
        if row:
            try:
                value = row["value"]
                if es_contenido_local_cifrado(value):
                    value = descifrar_contenido_local(value)
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        return default

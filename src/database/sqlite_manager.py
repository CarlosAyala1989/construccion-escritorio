"""
Database Manager — Conecta al MySQL remoto y al SQLite local.
Patrón Singleton para evitar conexiones concurrentes.
La BD MySQL remota es la fuente de verdad para configuración.
SQLite local es para la cola de pendientes y caché offline.
"""

import json
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

# Local paths
REPO_ROOT = os.path.dirname(BASE_DIR)
ensure_runtime_dirs()
SQLITE_PATH = os.path.join(DATA_DIR, "local_queue.db")


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
        if parsed.scheme.startswith("mysql"):
            return {
                "host": parsed.hostname or "",
                "port": parsed.port or 3306,
                "user": unquote(parsed.username or ""),
                "password": unquote(parsed.password or ""),
                "database": unquote(parsed.path.lstrip("/")),
            }

    return {
        "host": env.get("MYSQL_HOST") or env.get("DB_HOST") or "",
        "port": _env_int(env.get("MYSQL_PORT") or env.get("DB_PORT"), 3306),
        "user": env.get("MYSQL_USER") or env.get("DB_USER") or "",
        "password": env.get("MYSQL_PASSWORD") or env.get("DB_PASSWORD") or "",
        "database": env.get("MYSQL_DATABASE") or env.get("DB_NAME") or "",
    }


# MySQL remote config comes from .env / environment variables.
MYSQL_CONFIG = _mysql_config_from_env()


class AuthenticationError(Exception):
    """Expected authentication failure that can be shown to the user."""


def _verify_totp_code(secret, code):
    """Verify a six-digit TOTP using the same 30-second window as the web app."""
    normalized_code = re.sub(r"\s+", "", str(code or ""))
    if not secret or not re.fullmatch(r"\d{6}", normalized_code):
        return False

    try:
        return pyotp.TOTP(secret, digits=6, interval=30).verify(
            normalized_code,
            valid_window=1,
        )
    except Exception:
        return False


class DatabaseManager:
    """Singleton database manager for both MySQL and SQLite."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._mysql_connections = threading.local()
        self._init_sqlite()

    # ─── SQLite (Local) ────────────────────────────────

    def _init_sqlite(self):
        """Create local SQLite tables for offline queue and cache."""
        conn = sqlite3.connect(SQLITE_PATH)
        c = conn.cursor()

        # Local document processing queue
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

        # Cached config from MySQL (offline-first)
        c.execute("""
            CREATE TABLE IF NOT EXISTS cached_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # Local audit log buffer (syncs to MySQL when online)
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

        # Session tracking
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

    def _encrypt_legacy_audit_logs(self, cursor):
        """Migrate legacy readable log rows without changing the SQLite schema."""
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
        """Get a fresh SQLite connection."""
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    # ─── MySQL (Remote) ────────────────────────────────

    def get_mysql(self):
        """Get MySQL connection, reconnecting if needed."""
        if not all(MYSQL_CONFIG.get(key) for key in ["host", "user", "database"]):
            print("[DB] MySQL config missing; using local cache if available")
            return None

        try:
            connection = getattr(self._mysql_connections, "connection", None)
            if connection is None or not connection.is_connected():
                connection = mysql.connector.connect(**MYSQL_CONFIG)
                self._mysql_connections.connection = connection
            return connection
        except mysql.connector.Error as e:
            print(f"[DB] MySQL connection failed: {e}")
            return None

    def is_online(self):
        """Check if MySQL is reachable."""
        try:
            conn = self.get_mysql()
            if conn and conn.is_connected():
                return True
        except Exception:
            pass
        return False

    # ─── Auth ──────────────────────────────────────────

    def authenticate_user(self, email, password, totp_code):
        """Authenticate a desktop user with password and administrator-managed TOTP."""
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

        # Verify bcrypt password
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

    # ─── Workspaces ────────────────────────────────────

    def get_user_workspaces(self, user_id):
        """Get workspaces assigned to a user."""
        conn = self.get_mysql()
        if not conn:
            # Fallback to cached
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
            print(f"[DB] Workspace list failed; using cache: {error}")
            return self._get_cached("workspaces", [])
        finally:
            if cursor:
                cursor.close()

        # Cache for offline use
        self._set_cached("workspaces", json.dumps(workspaces))
        return workspaces

    def get_workspace(self, workspace_id):
        """Get one workspace from MySQL, falling back to the last safe cache."""
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
                print(f"[DB] Workspace lookup failed; using cache: {error}")
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

    # ─── Security Policies ─────────────────────────────

    def get_security_policies(self):
        """Get all security policies from MySQL."""
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
            print(f"[DB] Policy lookup failed; using cache: {error}")
            return self._get_cached("policies", [])
        finally:
            if cursor:
                cursor.close()

        self._set_cached("policies", json.dumps(policies))
        return policies

    # ─── Config ────────────────────────────────────────

    def get_config(self):
        """Get system configuration from MySQL."""
        conn = self.get_mysql()
        if not conn:
            return self._get_cached("config", {
                "compressionEnabled": False,
                "compressionThresholdMb": 10,
                "deleteLocalAfterUpload": False,
                "cloudProvider": "MANUAL",
            })

        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM Config LIMIT 1")
            config = cursor.fetchone()
        except mysql.connector.Error as error:
            print(f"[DB] Config lookup failed; using cache: {error}")
            return self._get_cached("config", {
                "compressionEnabled": False,
                "compressionThresholdMb": 10,
                "deleteLocalAfterUpload": False,
                "cloudProvider": "MANUAL",
            })
        finally:
            if cursor:
                cursor.close()

        if config:
            # Convert booleans
            config["compressionEnabled"] = bool(config.get("compressionEnabled", 0))
            config["deleteLocalAfterUpload"] = bool(config.get("deleteLocalAfterUpload", 0))
            self._set_cached("config", json.dumps(config, default=str))
            return config

        return {
            "compressionEnabled": False,
            "compressionThresholdMb": 10,
            "deleteLocalAfterUpload": False,
            "cloudProvider": "MANUAL",
        }

    def get_google_credentials(self):
        """Get Google OAuth client credentials from Config.cloudCredentials."""
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
                pass
        return {"googleClientId": "", "googleClientSecret": ""}

    # ─── Nomenclatures ─────────────────────────────────

    def get_nomenclatures(self):
        """Get nomenclature fields from MySQL."""
        conn = self.get_mysql()
        if not conn:
            return self._get_cached("nomenclatures", [])

        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM NomenclatureField ORDER BY fieldOrder ASC")
            fields = cursor.fetchall()
        except mysql.connector.Error as error:
            print(f"[DB] Nomenclature lookup failed; using cache: {error}")
            return self._get_cached("nomenclatures", [])
        finally:
            if cursor:
                cursor.close()

        self._set_cached("nomenclatures", json.dumps(fields, default=str))
        return fields

    # ─── Audit Logs ────────────────────────────────────

    def create_audit_log(self, user_id, user_name, action, details, status="SUCCESS", workspace_id=None):
        """Create an AES-GCM encrypted local log, then try the SaaS database."""
        log_id = str(uuid.uuid4())

        encrypted_payload = encrypt_local_payload({
            "user_id": user_id,
            "user_name": user_name,
            "action": action,
            "details": details,
            "status": status,
            "workspace_id": workspace_id,
        })

        # Persist only the encrypted envelope locally. Searchable metadata is
        # reconstructed in memory immediately before synchronization.
        sqlite_conn = self.get_sqlite()
        sqlite_conn.execute(
            """INSERT INTO local_audit_log (id, user_id, user_name, action, details, status, workspace_id, synced)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (log_id, None, None, "ENCRYPTED", encrypted_payload, "ENCRYPTED", None)
        )
        sqlite_conn.commit()
        sqlite_conn.close()

        # Try to sync to MySQL
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

                # Mark as synced
                sqlite_conn = self.get_sqlite()
                sqlite_conn.execute("UPDATE local_audit_log SET synced = 1 WHERE id = ?", (log_id,))
                sqlite_conn.commit()
                sqlite_conn.close()
            except Exception as e:
                print(f"[DB] Failed to sync log to MySQL: {e}")

    def sync_pending_logs(self):
        """Sync unsynced audit logs from SQLite to MySQL."""
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
                print(f"[DB] Sync failed for log {log['id']}: {e}")

        sqlite_conn.commit()
        sqlite_conn.close()
        return synced_count

    @staticmethod
    def _read_audit_log_payload(log):
        """Read encrypted rows while retaining compatibility with legacy queues."""
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

    # ─── Local Queue ───────────────────────────────────

    def add_to_queue(self, file_path, original_name, workspace_id=None, workspace_name=None):
        """Add a document to the local processing queue."""
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
        """Update a queue item with any fields."""
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
        """Get a single queue item by its stable identifier."""
        conn = self.get_sqlite()
        item = conn.execute(
            "SELECT * FROM local_queue WHERE id = ?",
            (doc_id,),
        ).fetchone()
        conn.close()
        return dict(item) if item else None

    def get_queue_items(self, status=None):
        """Get queue items, optionally filtered by status."""
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

    def get_pending_review(self):
        """Get items that need manual review."""
        return self.get_queue_items(status="PENDING_REVIEW")

    # ─── Sessions ──────────────────────────────────────

    def create_session(self, user_id, workspace_id=None, workspace_name=None):
        """Create a new scanning session."""
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
        """Close a scanning session."""
        conn = self.get_sqlite()
        conn.execute(
            "UPDATE sessions SET status = 'CLOSED', ended_at = datetime('now') WHERE id = ?",
            (session_id,)
        )
        conn.commit()
        conn.close()

    def get_active_session(self, user_id):
        """Get the active session for a user."""
        conn = self.get_sqlite()
        session = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? AND status = 'ACTIVE' ORDER BY started_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        conn.close()
        return dict(session) if session else None

    def increment_session_doc_count(self, session_id):
        """Increment the document count for a session."""
        conn = self.get_sqlite()
        conn.execute("UPDATE sessions SET doc_count = doc_count + 1 WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()

    # ─── Cache Helpers ─────────────────────────────────

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

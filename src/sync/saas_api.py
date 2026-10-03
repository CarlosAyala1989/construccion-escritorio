"""
SaaS API Client — Comunicación HTTP con el backend Next.js.
Envía logs, recibe configuración, reporta subidas.
"""

import logging
import requests

REQUEST_TIMEOUT_SECONDS = 10
CONNECTION_TIMEOUT_SECONDS = 5
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_FORBIDDEN = 403


class SaaSAPIClient:
    """Cliente HTTP para comunicarse con el backend SaaS de Next.js."""

    def __init__(self, base_url="http://localhost:3000", token=None):
        self.base_url = base_url
        self.token = token

    # RF-17 — Construye encabezados HTTP sin modificar estado compartido.
    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    # RF-17 — Obtiene la configuración remota y registra fallos de red.
    def get_config(self):
        """Obtiene toda la configuración desde la API SaaS."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/sync/config",
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if resp.status_code == HTTP_OK:
                return resp.json()
        except requests.RequestException as e:
            logging.getLogger(__name__).warning("Falló la consulta de configuración remota: %s", e)
        return None

    # RF-17 — Informa una subida y devuelve si el backend la aceptó.
    def report_upload(self, upload_data):
        """Informa al servicio SaaS que la carga de un documento fue exitosa."""
        try:
            resp = requests.post(
                f"{self.base_url}/api/sync/upload",
                headers=self._headers(),
                json=upload_data,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            return resp.status_code == HTTP_CREATED
        except requests.RequestException as e:
            logging.getLogger(__name__).warning("Falló el reporte de subida: %s", e)
            return False

    # RF-17 — Sincroniza el lote de bitácoras y devuelve el resultado al llamador.
    def sync_logs(self, logs):
        """Envía un lote de bitácoras de auditoría al servicio SaaS."""
        try:
            resp = requests.post(
                f"{self.base_url}/api/sync/logs",
                headers=self._headers(),
                json={"logs": logs},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            return resp.status_code == HTTP_CREATED
        except requests.RequestException as e:
            logging.getLogger(__name__).warning("Falló la sincronización de bitácoras: %s", e)
            return False

    # RF-17 — Comprueba conectividad con estados HTTP aceptados por la API.
    def check_connection(self):
        """Comprueba si la API SaaS está disponible."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/stats",
                timeout=CONNECTION_TIMEOUT_SECONDS,
            )
            return resp.status_code in {HTTP_OK, HTTP_FORBIDDEN}
        except requests.RequestException as error:
            logging.getLogger(__name__).debug("No se pudo comprobar la conexión SaaS: %s", error)
            return False

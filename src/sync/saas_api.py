"""
SaaS API Client — Comunicación HTTP con el backend Next.js.
Envía logs, recibe configuración, reporta subidas.
"""

import requests
import json


class SaaSAPIClient:
    """HTTP client for communicating with the Next.js SaaS backend."""

    def __init__(self, base_url="http://localhost:3000", token=None):
        self.base_url = base_url
        self.token = token

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def get_config(self):
        """Fetch all configuration from the SaaS API."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/sync/config",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException as e:
            print(f"[API] Config fetch failed: {e}")
        return None

    def report_upload(self, upload_data):
        """Report a successful document upload to the SaaS."""
        try:
            resp = requests.post(
                f"{self.base_url}/api/sync/upload",
                headers=self._headers(),
                json=upload_data,
                timeout=10,
            )
            return resp.status_code == 201
        except requests.RequestException as e:
            print(f"[API] Upload report failed: {e}")
            return False

    def sync_logs(self, logs):
        """Send batch audit logs to the SaaS."""
        try:
            resp = requests.post(
                f"{self.base_url}/api/sync/logs",
                headers=self._headers(),
                json={"logs": logs},
                timeout=10,
            )
            return resp.status_code == 201
        except requests.RequestException as e:
            print(f"[API] Log sync failed: {e}")
            return False

    def check_connection(self):
        """Check if the SaaS API is reachable."""
        try:
            resp = requests.get(f"{self.base_url}/api/stats", timeout=5)
            return resp.status_code in [200, 403]
        except requests.RequestException:
            return False

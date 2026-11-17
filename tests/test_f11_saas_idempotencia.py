import unittest
from unittest.mock import Mock, patch

from src.sync.saas_api import ClienteAPISaaS, HTTP_CREATED


class PruebasIdempotenciaSaaSF11(unittest.TestCase):
    def setUp(self):
        self.client = ClienteAPISaaS("http://localhost:3000", "token-prueba")

    @patch("src.sync.saas_api.requests.post")
    def test_reintento_de_subida_conserva_identificador_estable(self, post):
        post.return_value = Mock(status_code=HTTP_CREATED)
        upload = {"id": "cola-123", "fileName": "documento.pdf"}

        self.assertTrue(self.client.informar_subida(upload))
        self.assertTrue(self.client.informar_subida(upload))

        self.assertNotIn("operationId", upload)
        payloads = [call.kwargs["json"] for call in post.call_args_list]
        self.assertEqual(["cola-123", "cola-123"], [item["operationId"] for item in payloads])

    @patch("src.sync.saas_api.requests.post")
    def test_lote_deriva_operation_id_del_id_durable_de_sqlite(self, post):
        post.return_value = Mock(status_code=HTTP_CREATED)
        logs = [{"id": "audit-1", "action": "SCAN"}, {"id": "audit-2", "action": "UPLOAD"}]

        self.assertTrue(self.client.sincronizar_bitacoras(logs))

        payload = post.call_args.kwargs["json"]
        self.assertEqual(["audit-1", "audit-2"], [log["operationId"] for log in payload["logs"]])
        self.assertTrue(all("operationId" not in log for log in logs))

    @patch("src.sync.saas_api.requests.post")
    def test_falla_cerrado_si_no_hay_identificador_reintentable(self, post):
        self.assertFalse(self.client.informar_subida({"fileName": "sin-id.pdf"}))
        self.assertFalse(self.client.sincronizar_bitacoras([{"action": "SCAN"}]))
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()

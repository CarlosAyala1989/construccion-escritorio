import os
import unittest
from unittest.mock import patch

from src.database import sqlite_manager


class PruebasAislamientoEntorno(unittest.TestCase):
    def test_no_lee_archivos_entorno_del_repositorio_web_hermano(self):
        consulted_paths = []

        def fake_env_file(path):
            consulted_paths.append(path)
            return {"F08_FILE_VALUE": path}

        with (
            patch.object(sqlite_manager, "_analizar_archivo_entorno", side_effect=fake_env_file),
            patch.dict(os.environ, {"F08_PROCESS_VALUE": "process-wins"}, clear=False),
        ):
            environment = sqlite_manager._cargar_entorno()

        normalized_paths = [path.replace("\\", "/").lower() for path in consulted_paths]
        self.assertFalse(any("/construccion-web/" in path for path in normalized_paths))
        self.assertEqual("process-wins", environment["F08_PROCESS_VALUE"])
        self.assertEqual(3, len(consulted_paths))


if __name__ == "__main__":
    unittest.main()



# Pruebas automatizadas de cloud uploader hierarchy.
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.sync.cloud_uploader import CargadorNube


HIERARCHY = [
    "001-2022-XIV-MACREPOL-TACNA",
    "REGPOLTAC",
    "DIVOPUS-TAC",
    "DUE",
]


# Agrupa el comportamiento de nube cargador jerarquía tests y el estado de sus operaciones.
class PruebasJerarquiaCargadorNube(unittest.TestCase):
    # Crea procesado archivo según las reglas del componente.
    def _crear_archivo_procesado(self, root):
        file_path = Path(root, *HIERARCHY, "USE-SECCOMUL.pdf")
        file_path.parent.mkdir(parents=True)
        file_path.write_bytes(b"%PDF-test")
        return file_path

    # Comprueba local carga preserves procesado jerarquía mediante una prueba de regresión.
    def test_subida_local_preserva_jerarquia_procesada(self):
        with tempfile.TemporaryDirectory() as processed_dir:
            with tempfile.TemporaryDirectory() as destination:
                file_path = self._crear_archivo_procesado(processed_dir)
                uploader = CargadorNube()

                with patch(
                    "src.sync.cloud_uploader.PROCESSED_DIR",
                    processed_dir,
                ):
                    result = uploader._subir_destino_local(
                        str(file_path),
                        destination,
                        "Riesgos",
                    )

                expected = Path(
                    destination,
                    "Riesgos",
                    *HIERARCHY,
                    "USE-SECCOMUL.pdf",
                )
                self.assertTrue(result["success"])
                self.assertEqual(expected, Path(result["destination"]))
                self.assertTrue(expected.is_file())

    # Comprueba Drive carga uses leaf carpeta as parent mediante una prueba de regresión.
    def test_subida_drive_usa_carpeta_hoja_como_padre(self):
        with tempfile.TemporaryDirectory() as processed_dir:
            file_path = self._crear_archivo_procesado(processed_dir)
            uploader = CargadorNube({
                "googleClientId": "client",
                "googleClientSecret": "secret",
            })
            workspace = {
                "cloudFolderId": "root-folder",
                "cloudRefreshToken": "refresh-token",
            }

            with patch("src.sync.cloud_uploader.PROCESSED_DIR", processed_dir):
                with patch.object(
                    uploader,
                    "_actualizar_token_acceso",
                    return_value="access-token",
                ):
                    with patch.object(
                        uploader,
                        "_asegurar_carpetas_drive",
                        return_value="due-folder",
                    ) as ensure_folders:
                        with patch.object(
                            uploader,
                            "_subida_simple",
                            return_value={"id": "pdf-id"},
                        ) as upload:
                            result = uploader._subir_drive(
                                str(file_path),
                                workspace,
                            )

            ensure_folders.assert_called_once_with(
                "root-folder",
                HIERARCHY,
                "access-token",
            )
            self.assertEqual("due-folder", upload.call_args.args[1]["parents"][0])
            self.assertEqual(
                hashlib.sha256(b"%PDF-test").hexdigest(),
                upload.call_args.args[1]["appProperties"]["sha256"],
            )
            self.assertTrue(result["success"])
            self.assertTrue(result["destination"].endswith(
                "/".join(HIERARCHY + ["USE-SECCOMUL.pdf"])
            ))


if __name__ == "__main__":
    unittest.main()

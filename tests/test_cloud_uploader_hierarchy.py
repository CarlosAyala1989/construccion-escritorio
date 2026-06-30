import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.sync.cloud_uploader import CloudUploader


HIERARCHY = [
    "001-2022-XIV-MACREPOL-TACNA",
    "REGPOLTAC",
    "DIVOPUS-TAC",
    "DUE",
]


class CloudUploaderHierarchyTests(unittest.TestCase):
    def _create_processed_file(self, root):
        file_path = Path(root, *HIERARCHY, "USE-SECCOMUL.pdf")
        file_path.parent.mkdir(parents=True)
        file_path.write_bytes(b"%PDF-test")
        return file_path

    def test_local_upload_preserves_processed_hierarchy(self):
        with tempfile.TemporaryDirectory() as processed_dir:
            with tempfile.TemporaryDirectory() as destination:
                file_path = self._create_processed_file(processed_dir)
                uploader = CloudUploader()

                with patch(
                    "src.sync.cloud_uploader.PROCESSED_DIR",
                    processed_dir,
                ):
                    result = uploader._upload_local_dest(
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

    def test_drive_upload_uses_leaf_folder_as_parent(self):
        with tempfile.TemporaryDirectory() as processed_dir:
            file_path = self._create_processed_file(processed_dir)
            uploader = CloudUploader({
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
                    "_refresh_access_token",
                    return_value="access-token",
                ):
                    with patch.object(
                        uploader,
                        "_ensure_gdrive_folders",
                        return_value="due-folder",
                    ) as ensure_folders:
                        with patch.object(
                            uploader,
                            "_simple_upload",
                            return_value={"id": "pdf-id"},
                        ) as upload:
                            result = uploader._upload_gdrive(
                                str(file_path),
                                workspace,
                            )

            ensure_folders.assert_called_once_with(
                "root-folder",
                HIERARCHY,
                "access-token",
            )
            self.assertEqual("due-folder", upload.call_args.args[1]["parents"][0])
            self.assertTrue(result["success"])
            self.assertTrue(result["destination"].endswith(
                "/".join(HIERARCHY + ["USE-SECCOMUL.pdf"])
            ))


if __name__ == "__main__":
    unittest.main()

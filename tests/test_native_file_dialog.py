import os
import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from src.core.native_file_dialog import (
    _parse_windows_selection,
    _select_files_linux,
)


class NativeFileDialogTests(unittest.TestCase):
    def test_parses_windows_multiple_selection(self):
        raw = "C:\\Documentos\0uno.pdf\0dos.png\0\0"

        self.assertEqual(
            [
                os.path.join("C:\\Documentos", "uno.pdf"),
                os.path.join("C:\\Documentos", "dos.png"),
            ],
            _parse_windows_selection(raw),
        )

    @patch("src.core.native_file_dialog.subprocess.run")
    @patch("src.core.native_file_dialog.shutil.which")
    def test_uses_zenity_on_gtk_desktop(self, which, run):
        which.side_effect = lambda name: f"/usr/bin/{name}" if name == "zenity" else None
        run.return_value = CompletedProcess(
            args=[],
            returncode=0,
            stdout="/tmp/uno.pdf\x1f/tmp/dos.png\n",
            stderr="",
        )

        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}):
            selected = _select_files_linux()

        self.assertEqual(["/tmp/uno.pdf", "/tmp/dos.png"], selected)
        self.assertEqual("/usr/bin/zenity", run.call_args.args[0][0])

    @patch("src.core.native_file_dialog.subprocess.run")
    @patch("src.core.native_file_dialog.shutil.which")
    def test_uses_kdialog_on_kde_desktop(self, which, run):
        which.side_effect = lambda name: f"/usr/bin/{name}" if name == "kdialog" else None
        run.return_value = CompletedProcess(
            args=[],
            returncode=0,
            stdout="/tmp/uno.pdf\n/tmp/dos.png\n",
            stderr="",
        )

        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}):
            selected = _select_files_linux()

        self.assertEqual(["/tmp/uno.pdf", "/tmp/dos.png"], selected)
        self.assertEqual("/usr/bin/kdialog", run.call_args.args[0][0])


if __name__ == "__main__":
    unittest.main()

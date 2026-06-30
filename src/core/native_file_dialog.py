"""Cross-platform native file selection for the desktop client."""

import ctypes
import os
import platform
import shutil
import subprocess
from ctypes import wintypes


DOCUMENT_PATTERNS = ("*.pdf", "*.png", "*.jpg", "*.jpeg", "*.tiff", "*.bmp")
DIALOG_TITLE = "Seleccionar archivos para importar"


def select_document_files():
    """Return document paths selected with the operating system's file dialog."""
    system = platform.system()
    if system == "Windows":
        return _select_files_windows()
    if system == "Linux":
        selected = _select_files_linux()
        if selected is not None:
            return selected
    return _select_files_tk_fallback()


def _select_files_windows():
    """Use the Windows common Open dialog directly, without a Tk window."""
    class OpenFileName(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    file_buffer = ctypes.create_unicode_buffer(65536)
    filter_buffer = ctypes.create_unicode_buffer(
        "Documentos\0*.pdf;*.png;*.jpg;*.jpeg;*.tiff;*.bmp\0"
        "Archivos PDF\0*.pdf\0"
        "Imágenes\0*.png;*.jpg;*.jpeg;*.tiff;*.bmp\0"
        "Todos los archivos\0*.*\0\0"
    )
    user32 = ctypes.windll.user32
    common_dialog = ctypes.windll.comdlg32
    user32.GetForegroundWindow.restype = wintypes.HWND
    common_dialog.GetOpenFileNameW.argtypes = [ctypes.POINTER(OpenFileName)]
    common_dialog.GetOpenFileNameW.restype = wintypes.BOOL
    common_dialog.CommDlgExtendedError.restype = wintypes.DWORD

    dialog = OpenFileName()
    dialog.lStructSize = ctypes.sizeof(OpenFileName)
    dialog.hwndOwner = user32.GetForegroundWindow()
    dialog.lpstrFilter = ctypes.cast(filter_buffer, wintypes.LPCWSTR)
    dialog.nFilterIndex = 1
    dialog.lpstrFile = ctypes.cast(file_buffer, wintypes.LPWSTR)
    dialog.nMaxFile = len(file_buffer)
    dialog.lpstrInitialDir = os.path.expanduser("~")
    dialog.lpstrTitle = DIALOG_TITLE
    dialog.Flags = (
        0x00000004  # OFN_HIDEREADONLY
        | 0x00000200  # OFN_ALLOWMULTISELECT
        | 0x00000800  # OFN_PATHMUSTEXIST
        | 0x00001000  # OFN_FILEMUSTEXIST
        | 0x00080000  # OFN_EXPLORER
    )

    if common_dialog.GetOpenFileNameW(ctypes.byref(dialog)):
        return _parse_windows_selection(file_buffer[:])

    error_code = common_dialog.CommDlgExtendedError()
    if error_code == 0:
        return []
    raise OSError(error_code, "Windows no pudo abrir el selector de archivos")


def _parse_windows_selection(raw_selection):
    parts = [part for part in raw_selection.split("\0") if part]
    if len(parts) <= 1:
        return parts
    directory = parts[0]
    return [os.path.join(directory, name) for name in parts[1:]]


def _select_files_linux():
    """Use the file selector matching the active Linux desktop when available."""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    candidates = ["kdialog", "zenity"] if "kde" in desktop else ["zenity", "kdialog"]

    for dialog_name in candidates:
        executable = shutil.which(dialog_name)
        if not executable:
            continue

        if dialog_name == "kdialog":
            command = [
                executable,
                "--title",
                DIALOG_TITLE,
                "--multiple",
                "--separate-output",
                "--getopenfilename",
                os.path.expanduser("~"),
                "Documentos (*.pdf *.png *.jpg *.jpeg *.tiff *.bmp)",
            ]
            separator = "\n"
        else:
            separator = "\x1f"
            command = [
                executable,
                "--file-selection",
                "--multiple",
                f"--separator={separator}",
                f"--title={DIALOG_TITLE}",
                f"--filename={os.path.expanduser('~')}{os.sep}",
                "--file-filter=Documentos | *.pdf *.png *.jpg *.jpeg *.tiff *.bmp",
                "--file-filter=Archivos PDF | *.pdf",
                "--file-filter=Imágenes | *.png *.jpg *.jpeg *.tiff *.bmp",
                "--file-filter=Todos los archivos | *",
            ]

        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode == 0:
            return [path for path in result.stdout.rstrip("\n").split(separator) if path]
        if result.returncode == 1:
            return []

    return None


def _select_files_tk_fallback():
    """Keep compatibility with minimal Linux installations without KDE/GTK helpers."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.update_idletasks()
        files = filedialog.askopenfilenames(
            parent=root,
            title=DIALOG_TITLE,
            initialdir=os.path.expanduser("~"),
            filetypes=[
                ("Documentos", " ".join(DOCUMENT_PATTERNS)),
                ("PDF", "*.pdf"),
                ("Imágenes", "*.png *.jpg *.jpeg *.tiff *.bmp"),
                ("Todos", "*.*"),
            ],
        )
        return list(files)
    finally:
        root.destroy()

# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for Gobernanza Documental Desktop Client

import os
from PyInstaller.utils.hooks import collect_submodules


block_cipher = None

datas = [
    ('web', 'web'),
]

if os.path.isdir('data/templates'):
    datas.append(('data/templates', 'data/templates'))

hiddenimports = [
    'eel',
    'bottle',
    'bottle_websocket',
    'tkinter',
    'tkinter.filedialog',
    'src.app_paths',
    'src.controller',
    'src.core.ocr_engine',
    'src.core.vision_engine',
    'src.core.crypto_engine',
    'src.core.file_structurer',
    'src.core.native_file_dialog',
    'src.core.pending_tray',
    'src.core.secure_file_writer',
    'src.database.sqlite_manager',
    'src.hardware.scanner',
    'src.sync.cloud_uploader',
    'src.sync.saas_api',
]

hiddenimports += collect_submodules('win32com')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GobernanzaDocumental',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

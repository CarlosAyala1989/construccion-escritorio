# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for Gobernanza Documental Desktop Client

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('web', 'web'),
        ('data/templates', 'data/templates'),
    ],
    hiddenimports=[
        'eel',
        'bottle',
        'src.controller',
        'src.core.ocr_engine',
        'src.core.vision_engine',
        'src.core.crypto_engine',
        'src.database.sqlite_manager',
        'src.hardware.scanner',
        'src.sync.cloud_uploader',
        'src.sync.saas_api',
    ],
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# dadarzz-mac.spec
# PyInstaller spec file — macOS Apple Silicon (M1/M2/M3)
# Run with: pyinstaller dadarzz-mac.spec

import os
from PyInstaller.utils.hooks import collect_all

datas_flask, binaries_flask, hiddenimports_flask = collect_all('flask')
datas_groq,  binaries_groq,  hiddenimports_groq  = collect_all('groq')

a = Analysis(
    ['Agent.py'],
    pathex=['.'],
    binaries=binaries_flask + binaries_groq,
    datas=[
        ('templates', 'templates'),
        ('static',    'static'),
        *datas_flask,
        *datas_groq,
    ],
    hiddenimports=[
        'flask',
        'flask.templating',
        'jinja2',
        'werkzeug',
        'groq',
        'httpx',
        'anyio',
        *hiddenimports_flask,
        *hiddenimports_groq,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt5', 'wx'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='dadarzz-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX can break ARM64 binaries — keep off
    console=True,
    target_arch='arm64',        # M1/M2/M3 Apple Silicon
    codesign_identity=None,
    entitlements_file=None,
)

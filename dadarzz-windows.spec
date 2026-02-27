# dadarzz-windows.spec
# PyInstaller spec file — Windows x86_64
# Run with: pyinstaller dadarzz-windows.spec
#
# Prerequisites:
#   pip install pyinstaller flask groq httpx
#
# Notes:
#   - Build must be run ON a Windows machine (cross-compilation not supported)
#   - Output: dist\dadarzz-agent.exe
#   - On first run, Windows Defender / SmartScreen may show a warning.
#     Users click "More info" → "Run anyway".
#   - UPX is left on for Windows — it's safe and reduces file size noticeably.
#     Remove upx=True and the upx_exclude list if you hit any issues.

import os
from PyInstaller.utils.hooks import collect_all

datas_flask, binaries_flask, hiddenimports_flask = collect_all('flask')
datas_groq,  binaries_groq,  hiddenimports_groq  = collect_all('groq')

a = Analysis(
    ['Agent.py'],
    pathex=['.'],
    binaries=binaries_flask + binaries_groq,
    datas=[
        ('templates', 'templates'),   # Windows uses backslash internally
        ('static',    'static'),      # but PyInstaller accepts forward slashes
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
    name='dadarzz-agent',           # output: dadarzz-agent.exe
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=True,                   # keep console so users see startup messages
    # No target_arch needed — PyInstaller matches the host machine
    icon=None,                      # set to 'icon.ico' if you have one
)

# dadarzz-linux.spec
# PyInstaller spec file — Linux x86_64
# Run with: pyinstaller dadarzz-linux.spec
#
# Prerequisites:
#   pip install pyinstaller flask groq httpx
#
# Notes:
#   - Build must be run ON a Linux machine (cross-compilation not supported)
#   - Output: dist/dadarzz-agent  (no extension)
#   - After distributing, recipients run:
#       chmod +x dadarzz-agent && ./dadarzz-agent
#   - The binary is NOT portable across distros if it links to system libs
#     that differ (e.g. glibc version). Build on the OLDEST distro you want
#     to support (e.g. Ubuntu 20.04) for widest compatibility.
#   - UPX is off by default — enable it if binary size is a concern and
#     you've verified it works on your target distros.

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
    strip=True,                     # strip debug symbols — reduces size on Linux
    upx=False,
    console=True,
    # No target_arch — matches host
)

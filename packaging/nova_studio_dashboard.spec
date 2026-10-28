# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the NOVA Studio dashboard desktop app (Windows).

Builds the web dashboard wrapped in a native window (pywebview) into a single
windowed exe — no console. Entry point: webapp/desktop.py.

Build (from repo root, on Windows):
    pyinstaller packaging\\nova_studio_dashboard.spec --noconfirm

Produces  dist\\NOVA-Studio\\NOVA-Studio.exe  (onedir). The Inno Setup script
packages it into NOVA-Setup.exe.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
WEBAPP = ROOT / "webapp"

block_cipher = None

# The dashboard's HTML/CSS/JS must ship with the app.
datas = [
    (str(WEBAPP / "static"), "webapp/static"),
    (str(ROOT / "licenses"), "licenses"),
    (str(ROOT / "scripts"), "scripts"),
    (str(ROOT / "docs"), "docs"),
    (str(ROOT / "README.md"), "."),
]

hiddenimports = []
hiddenimports += collect_submodules("pydantic")
hiddenimports += collect_submodules("pydantic_core")
hiddenimports += collect_submodules("flask")
hiddenimports += ["platformdirs", "waitress", "webview", "jinja2",
                  "nova_studio.core.studio",
                  "nova_studio.phase4.still_video",
                  "webapp.server"]

a = Analysis(
    [str(WEBAPP / "desktop.py")],
    pathex=[str(SRC), str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy.tests", "pytest", "PySide6"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="NOVA-Studio",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False,                 # windowed — NO console window
    disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
    codesign_identity=None, entitlements_file=None,
    icon=str(ROOT / "packaging" / "nova.ico")
        if (ROOT / "packaging" / "nova.ico").exists() else None,
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, upx_exclude=[], name="NOVA-Studio",
)

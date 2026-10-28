# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for NOVA AI Video Studio (Windows 11, onedir, windowed).

Build (from the repo root, on Windows):
    pyinstaller packaging\\nova_studio.spec --noconfirm

Produces  dist\\NOVA-Studio\\NOVA-Studio.exe  (an onedir bundle). The Inno Setup
script packages that folder into NOVA-Setup.exe.

onedir (not onefile) is deliberate: it starts faster, avoids the onefile temp
extraction that some AV flags, and lets the installer drop a bundled FFmpeg next
to the exe where the launcher finds it.
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Repo root = parent of this packaging/ dir. SPECPATH is provided by PyInstaller.
ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

block_cipher = None

# Ship read-only reference material beside the app (not user data).
datas = [
    (str(ROOT / "licenses"), "licenses"),
    (str(ROOT / "scripts"), "scripts"),
    (str(ROOT / "docs"), "docs"),
    (str(ROOT / "README.md"), "."),
]

# Pydantic v2 pulls in compiled submodules; collect them to be safe.
hiddenimports = []
hiddenimports += collect_submodules("pydantic")
hiddenimports += collect_submodules("pydantic_core")
hiddenimports += ["platformdirs"]
# The app imports UI/adapters lazily; name the ones PyInstaller may miss.
hiddenimports += [
    "nova_studio.app",
    "nova_studio.ui.main_window",
    "nova_studio.core.studio",
]

a = Analysis(
    [str(SRC / "nova_studio" / "win_launcher.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim heavy, unused libraries that may ride along with the environment so
    # the bundle stays lean. (Only excluded if present; harmless otherwise.)
    excludes=[
        "tkinter", "matplotlib", "numpy.tests", "pytest", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NOVA-Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                      # windowed GUI app (no console)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "packaging" / "nova.ico")
        if (ROOT / "packaging" / "nova.ico").exists() else None,
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NOVA-Studio",
)

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the NOVA Studio dashboard desktop app (Windows)."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_all

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
WEBAPP = ROOT / "webapp"
block_cipher = None

datas = [
    (str(WEBAPP / "static"), "webapp/static"),
    (str(ROOT / "licenses"), "licenses"),
    (str(ROOT / "scripts"), "scripts"),
    (str(ROOT / "docs"), "docs"),
    (str(ROOT / "README.md"), "."),
]
binaries = []

# webapp.server is imported dynamically by desktop.main(). Collect the whole
# package (and explicitly include the entry modules) so PyInstaller cannot omit
# it from the frozen one-dir build.
hiddenimports = []
for package in ("webapp", "flask", "pydantic", "pydantic_core"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass
hiddenimports += [
    "webapp", "webapp.desktop", "webapp.server", "webapp.models",
    "platformdirs", "waitress", "webview", "jinja2",
    "nova_studio.core.studio", "nova_studio.phase4.still_video",
]

# Bundle optional local LLM runtime only when installed.
try:
    _lc_datas, _lc_bins, _lc_hidden = collect_all("llama_cpp")
    datas += _lc_datas
    binaries += _lc_bins
    hiddenimports += _lc_hidden
except Exception:
    pass

a = Analysis(
    [str(WEBAPP / "desktop.py")],
    pathex=[str(ROOT), str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy.tests", "pytest", "PySide6"],
    win_no_prefer_redirects=False, win_private_assemblies=False,
    cipher=block_cipher, noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="NOVA-Studio",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    icon=str(ROOT / "packaging" / "nova.ico")
        if (ROOT / "packaging" / "nova.ico").exists() else None,
    version=str(ROOT / "packaging" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas,
               strip=False, upx=False, upx_exclude=[], name="NOVA-Studio")

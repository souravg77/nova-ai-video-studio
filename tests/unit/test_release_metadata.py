"""Release metadata stays consistent, and the installer keeps upgrade safety.

Inno Setup is not available on every dev machine, so these checks read the
installer script as text; CI compiles it for real.
"""
import re
from pathlib import Path

from nova_studio import config

ROOT = Path(__file__).resolve().parents[2]
ISS = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def test_one_version_everywhere():
    v = config.APP_VERSION
    assert _pyproject_version() == v
    assert re.search(r'#define AppVersion "([^"]+)"', ISS).group(1) == v

    vi = (ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    four = [int(x) for x in (v.split(".") + ["0"] * 4)[:4]]
    tup = ", ".join(map(str, four))
    assert f"filevers=({tup})" in vi
    assert f"prodvers=({tup})" in vi
    dotted = ".".join(map(str, four))
    assert f"StringStruct('FileVersion', '{dotted}')" in vi
    assert f"StringStruct('ProductVersion', '{dotted}')" in vi


def test_app_id_never_changes():
    # Changing AppId makes Windows treat a new version as a different program:
    # upgrades would install side by side instead of replacing NOVA.
    assert "AppId={{B7A9F3C2-2E6A-4C1F-9E2D-7C1A8E2D0001}" in ISS


def test_upgrade_and_uninstall_safety():
    assert "CloseApplications=yes" in ISS
    assert "UsePreviousAppDir=yes" in ISS
    # Stale runtime from an older build is cleared before files are copied.
    assert re.search(r'\[InstallDelete\][^\[]*Name: "\{app\}\\_internal"', ISS)
    # User data lives outside {app}; nothing in the script deletes it.
    assert "localappdata" not in ISS.lower().replace("%localappdata%", "")


def test_ffmpeg_and_its_licence_are_required():
    start = ISS.index("#ifndef NoFfmpeg")
    block = ISS[start:ISS.index("#endif", start)]
    for src in ("ffmpeg\\ffmpeg.exe", "ffmpeg\\ffprobe.exe", "ffmpeg\\LICENSE.txt"):
        line = next(ln for ln in block.splitlines() if src in ln)
        assert "skipifsourcedoesntexist" not in line
    notices = (ROOT / "licenses" / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "General Public License v3" in notices
    assert "ffmpeg-licenses\\LICENSE.txt" in notices


def test_welcome_text_does_not_overclaim():
    welcome = next(ln for ln in ISS.splitlines() if ln.startswith("WelcomeLabel2="))
    assert "fully offline" not in welcome
    assert "offline by default" in welcome

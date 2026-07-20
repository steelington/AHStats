# PyInstaller spec for AHSTATS - onefile, windowed (no console) build.
#
# Build with: pyinstaller AHStats.spec --clean
#
# Data layout notes:
#   - ahstats/assets/* is bundled at the same relative path
#     ("ahstats/assets") inside the onefile archive, matching
#     ahstats.paths.resource_path()'s expectation.
#   - customtkinter ships its own internal assets (default themes, fonts)
#     that PyInstaller's import analysis doesn't pick up automatically -
#     collect_all() pulls those in too.
from PyInstaller.utils.hooks import collect_all

datas = [("ahstats/assets", "ahstats/assets")]
binaries = []
hiddenimports = []

for pkg in ("customtkinter",):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AHStats",
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
    icon="ahstats/assets/app_icon.ico",
)

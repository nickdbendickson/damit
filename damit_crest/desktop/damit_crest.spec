# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller damit_crest.spec   (Python 3.10–3.12; damit_desktop/web/ is committed, rebuild it with `npm run build:desktop` after changing src/)
# Result: dist/DamIT Crest/ (Windows: dist\DamIT Crest\DamIT Crest.exe), and dist/DamIT Crest.app on macOS.

import sys
from pathlib import Path

if not Path("damit_desktop/web/index.html").is_file():
    raise SystemExit("damit_desktop/web/index.html is missing: run `npm run build:desktop` from the repo root first.")

block_cipher = None

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=[("damit_desktop/web", "damit_desktop/web")],
    hiddenimports=[
        "damit_desktop",
        "damit_desktop.__main__",
        "damit_desktop.algorithms",
        "damit_desktop.handoff",
        "damit_desktop.qgis_run",
        "damit_desktop.layers",
        "damit_desktop.localdem",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DamIT Crest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DamIT Crest",
)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="DamIT Crest.app",
        icon=None,
        bundle_identifier="org.damit.crest",
        info_plist={"CFBundleName": "DamIT Crest", "CFBundleDisplayName": "DamIT Crest — Dam Breach and Hazard Desk"},
    )

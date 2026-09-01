# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one-file build bundling the app and its assets.

Built per target by .github/workflows/build.yml; binary lands in dist/.
`config.yaml` is deliberately NOT bundled: it is read from the working
directory and shipped next to the executable in the release archive.
"""

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="grbl-machine-controller",
    debug=False,
    strip=False,
    upx=False,
    console=False,   # GUI app: no console window (Linux uses .Desktop/systemd anyway)
)

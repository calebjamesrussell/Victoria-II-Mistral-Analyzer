# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Victoria II Mistral Analyzer.
# Build:  pyinstaller vic2-analyzer.spec
# Produces a one-folder portable distribution in dist/vic2-analyzer/

import sys

block_cipher = None

a = Analysis(
    ["run_analyzer.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "matplotlib.backends.backend_tkagg",
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "matplotlib.tests", "numpy.tests"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="vic2-analyzer",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="vic2-analyzer",
)

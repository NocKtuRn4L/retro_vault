# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for RetroVault."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


project_root = Path(SPECPATH).resolve().parents[1]
icon_path = Path(SPECPATH) / "retrovault.ico"

datas = collect_data_files(
    "retrovault",
    includes=["data/*", "data/emulators/*.json", "ui/*.qss"],
)

analysis = Analysis(
    [str(Path(SPECPATH) / "entrypoint.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
    ],
    noarchive=False,
)

# PySide's hook may collect Qt6Network.dll even when QtNetwork is excluded.
analysis.binaries = [
    binary for binary in analysis.binaries if Path(binary[0]).name.casefold() != "qt6network.dll"
]

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="RetroVault",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(icon_path) if icon_path.is_file() else None,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RetroVault",
)

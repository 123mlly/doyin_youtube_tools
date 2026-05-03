# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: GUI desktop bundle (onedir + Qt). Build from repo root:
#   pip install -e ".[gui,build-gui]"
#   pyinstaller packaging/DouyinDownloaderGui.spec
#
# Outputs:
#   dist/DouyinDownloaderGui/     (Windows / generic onedir)
#   dist/DouyinDownloaderGui.app (macOS bundle)

import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
ROOT = Path(SPECPATH).resolve().parent

datas, binaries, hiddenimports = collect_all("PySide6")

a = Analysis(
    [str(ROOT / "gui" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas + [(str(ROOT / "config.example.yml"), ".")],
    hiddenimports=list(hiddenimports),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DouyinDownloaderGui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DouyinDownloaderGui",
)

if platform.system() == "Darwin":
    app = BUNDLE(
        coll,
        name="DouyinDownloaderGui.app",
        bundle_identifier="com.douyin.downloader.gui",
        info_plist={
            "CFBundleDisplayName": "Douyin Downloader",
            "CFBundleName": "DouyinDownloaderGui",
            "NSHighResolutionCapable": True,
        },
    )

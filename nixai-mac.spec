# -*- mode: python ; coding: utf-8 -*-
from _pyinstaller_common import collect_hiddenimports, common_datas, common_excludes


hiddenimports = collect_hiddenimports()


a = Analysis(
    ['app/mac_launcher.py'],
    pathex=[],
    binaries=[],
    datas=common_datas(),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=common_excludes(),
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NixAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NixAI',
)

app = BUNDLE(
    coll,
    name='NixAI.app',
    icon='assets/macos/NixAI.icns',
    bundle_identifier='de.fkde.nixai',
    info_plist={
        'CFBundleName': 'NixAI',
        'CFBundleDisplayName': 'NixAI',
        'CFBundleShortVersionString': '0.1.0',
        'CFBundleVersion': '0.1.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
    },
)

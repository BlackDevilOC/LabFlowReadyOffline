# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['build.py'],
    pathex=[
        'offline',   # so PyInstaller resolves 'database' and 'dbActions' from offline/
    ],
    binaries=[],
    datas=[
        ('.env', '.'),
        ('static', 'static'),
        ('templates', 'templates'),
        ('logo_icon.ico', '.'),
        ('hospital_logo.png', '.'),
    ],
    hiddenimports=[
        'database',
        'dbActions',
        'offline',
        'offline.database',
        'offline.app',
        'replica_engine',
        'analytics_router',
        'patient_list_query',
        'search_utils',
        'user_access',
        'logdata',
    ],
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
    [],
    exclude_binaries=True,
    name='LabFlow',
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
    icon='logo_icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LabFlow',
)

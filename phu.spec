# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('gui', 'gui'), ('assets', 'assets')]
datas += collect_data_files('ttp')

block_cipher = None


a = Analysis(
    ['phu\\main.py'],
    pathex=['.', 'phu', 'venv/Lib/site-packages'],
    binaries=[],
    datas=datas,
    hiddenimports=['pyi_splash',
                   'ttp',
                   'ttp.utils.loaders',
                   'ttp.utils.get_attributes',
                   'ttp.patterns',
                   'ttp.patterns.get_pattern',
                   'ttp.patterns.get_patterns',
                   'ttp.match',
                   'ttp.match.string'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
splash = Splash(
    'gui/img/splash3.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=False,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    splash,
    splash.binaries,
    [],
    name='Provisioning Helper Utility',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='gui/img/icon.ico'
)

# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['system\\ui_main.py'],
    pathex=['.'],
    binaries=[],
    # config.yaml NAO entra aqui: esta' no .gitignore (tem IP e senha reais da
    # estacao) e o build falharia num clone limpo. Empacotamos o exemplo; o
    # instalador gera o config.yaml definitivo ao lado do exe.
    datas=[
        ('config.example.yaml',  '.'),
        ('spec_limits.csv',      '.'),
        ('column_mappings.json', '.'),
        ('assets/app.ico',       'assets'),
    ],
    hiddenimports=[
        'config.loader',
        'monitor.file_monitor',
        'parser.cyg_parser',
        'database.db_writer',
        'buffer.queue_buffer',
        'state.app_context',
        'state.runtime_status',
        'state.offset_manager',
        'logs.logger_setup',
        'sync.file_sync',
        'spec.spec_validator',
        'system.single_instance',
        'pystray._win32',
        'PIL._tkinter_finder',
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
    a.binaries,
    a.datas,
    [],
    name='MES_Client',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets\\app.ico',
)

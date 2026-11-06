# -*- mode: python ; coding: utf-8 -*-
# MES_Client_Win7.spec — build do Proteus Client para WINDOWS 7 SP1 (Python 3.8.10, 32 bits).
# Usado na pasta gerada por win7\gerar_edicao_win7.py (nunca direto no projeto).
# Igual ao parser_TE.spec da edição Windows 10, exceto:
#   - pacote 'csvparser' no lugar de 'parser' (colisão com o módulo embutido do 3.8)
#   - sem 'optimize' (o parâmetro só existe no PyInstaller 6+; aqui é o 5.13.2)
#   - upx=False (o UPX é fonte conhecida de falso positivo de antivírus)

a = Analysis(
    ['system\\ui_main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('config.example.yaml',  '.'),
        ('spec_limits.csv',      '.'),
        ('column_mappings.json', '.'),
        ('assets/app.ico',       'assets'),
    ],
    hiddenimports=[
        'config.loader',
        'monitor.file_monitor',
        'csvparser.cyg_parser',
        'csvparser.campos',
        'csvparser.configuravel',
        'csvparser.registry',
        'state.station_cache',
        'system.ui_fontes',
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
    # Módulo embutido 'parser' do Python 3.8 (removido no 3.10): o pacote do
    # projeto foi renomeado para csvparser justamente para não colidir.
    excludes=[],
    noarchive=False,
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
    upx=False,
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

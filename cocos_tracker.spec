# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_all
import os

block_cipher = None

# Collect all necessary data files from packages
dash_datas, dash_binaries, dash_hiddenimports = collect_all('dash')
plotly_datas, plotly_binaries, plotly_hiddenimports = collect_all('plotly')
duckdb_datas, duckdb_binaries, duckdb_hiddenimports = collect_all('duckdb')

a = Analysis(
    ['code\\portfolio_dashboard.py'],
    pathex=['e:\\Cocos Portfolio Tracker'],
    binaries=duckdb_binaries + dash_binaries + plotly_binaries,
    datas=[
        # App source files bundled into _MEIPASS
        ('code\\sectors.json',          '.'),
        ('code\\sector_manager.py',     '.'),
        ('code\\sector_api.py',         '.'),
        ('code\\etl.py',                '.'),
        ('code\\setup_db.py',           '.'),
        ('code\\ingest_logger.py',      '.'),
        ('code\\ingest_monitor.py',     '.'),
        ('code\\ingest_api.py',         '.'),
        # Empty DB — user's data lives next to the .exe
        ('data\\db\\portfolio.duckdb',  'data\\db'),
        # Package data
        *dash_datas,
        *plotly_datas,
        *duckdb_datas,
    ],
    hiddenimports=[
        'dash',
        'dash.dependencies',
        'dash_core_components',
        'dash_html_components',
        'dash_table',
        'plotly',
        'plotly.graph_objects',
        'plotly.express',
        'duckdb',
        'pandas',
        'flask',
        'flask_compress',
        'openpyxl',
        'pydantic',
        'requests',
        *dash_hiddenimports,
        *plotly_hiddenimports,
        *duckdb_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pyinstaller', 'pytest', 'jupyter', 'notebook', 'IPython'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Cocos Portfolio Tracker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # sin ventana de consola
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='cocos.ico',
    onefile=True,
)

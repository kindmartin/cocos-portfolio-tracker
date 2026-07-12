"""
sector_manager.py — Gestión de sectores para instrumentos.

Funciones:
  - Listar sectores
  - Crear nuevo sector
  - Asignar sector a instrumento
  - Listar instrumentos por sector
"""
import duckdb
from pathlib import Path
from datetime import datetime
import re
import unicodedata
from setup_db import DB_PATH, create_schema

# Detectar ruta base
_base_dir = Path(__file__).parent
if _base_dir.name == "code":
    _base_dir = _base_dir.parent


# Sectores predefinidos
DEFAULT_SECTORS = [
    ('Oil & Gas Arg.', '#8B4513'),
    ('Banca Arg', '#1e3a5f'),
    ('Tech USA', '#00d4ff'),
    ('Tech China', '#ff1493'),
    ('Agro Arg', '#90ee90'),
    ('Bonos Arg', '#ff6b6b'),
    ('Bonos USA', '#ffa500'),
    ('Tech Arg', '#4169e1'),
    ('Cash USD', '#fff000'),
    ('Cash Arg', '#ffff99'),
]


def init_sectors(conn=None) -> duckdb.DuckDBPyConnection:
    """Inicializa la tabla de sectores con los predefinidos."""
    if conn is None:
        conn = duckdb.connect(str(DB_PATH))
    
    # Verificar si ya existen sectores
    result = conn.execute('SELECT COUNT(*) FROM sector_list').fetchone()
    if result[0] > 0:
        return conn
    
    print('[LOG] Inicializando sectores predefinidos...')
    for idx, (name, color) in enumerate(DEFAULT_SECTORS, 1):
        conn.execute(
            'INSERT INTO sector_list (sector_id, sector_name, color) VALUES (?, ?, ?)',
            (idx, name, color)
        )
        print(f'  [OK] {idx}. {name}')
    
    return conn


def list_sectors(conn=None) -> list:
    """Retorna lista de todos los sectores."""
    if conn is None:
        conn = duckdb.connect(str(DB_PATH))
    
    result = conn.execute(
        'SELECT sector_id, sector_name, color FROM sector_list ORDER BY sector_id'
    ).fetchall()
    
    return [{'id': r[0], 'name': r[1], 'color': r[2]} for r in result]


def _normalize_sector_name(name: str) -> str:
    """Normaliza nombres para evitar duplicados semánticos (&, y, acentos, espacios)."""
    text = (name or '').strip().lower()
    text = text.replace('&', ' y ')
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def add_sector(name: str, color: str = '#808080', conn=None) -> dict:
    """Crea un nuevo sector."""
    if conn is None:
        conn = duckdb.connect(str(DB_PATH))

    clean_name = (name or '').strip()
    if not clean_name:
        return {'success': False, 'error': 'Nombre requerido'}

    normalized_new = _normalize_sector_name(clean_name)

    existing = conn.execute('SELECT sector_name FROM sector_list').fetchall()
    for (existing_name,) in existing:
        if _normalize_sector_name(existing_name) == normalized_new:
            return {
                'success': False,
                'error': f'Ya existe un sector equivalente: "{existing_name}"'
            }
    
    try:
        # Generar ID (max + 1)
        result = conn.execute('SELECT MAX(sector_id) FROM sector_list').fetchone()
        next_id = (result[0] or 0) + 1
        
        conn.execute(
            'INSERT INTO sector_list (sector_id, sector_name, color) VALUES (?, ?, ?)',
            (next_id, clean_name, color)
        )
        
        return {'success': True, 'id': next_id, 'name': clean_name, 'color': color}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_sector(sector_id: int, conn=None) -> dict:
    """Elimina un sector. Primero desasigna todos los instrumentos."""
    if conn is None:
        conn = duckdb.connect(str(DB_PATH))
    
    try:
        # Verificar que el sector existe
        sector = conn.execute('SELECT sector_name FROM sector_list WHERE sector_id = ?', (sector_id,)).fetchone()
        if not sector:
            return {'success': False, 'error': f'Sector {sector_id} no existe'}
        
        sector_name = sector[0]
        
        # Desasignar todos los instrumentos de este sector
        conn.execute('DELETE FROM instrument_sectors WHERE sector_id = ?', (sector_id,))
        
        # Eliminar el sector
        conn.execute('DELETE FROM sector_list WHERE sector_id = ?', (sector_id,))
        
        return {'success': True, 'message': f'Sector "{sector_name}" eliminado'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def assign_sector(ticker: str, sector_id: int, conn=None) -> dict:
    """Asigna un sector a un instrumento."""
    if conn is None:
        conn = duckdb.connect(str(DB_PATH))
    
    try:
        # Verificar que el instrumento existe
        inst = conn.execute('SELECT ticker FROM instruments WHERE ticker = ?', (ticker,)).fetchone()
        if not inst:
            return {'success': False, 'error': f'Instrumento {ticker} no existe'}
        
        # Verificar que el sector existe
        sect = conn.execute('SELECT sector_id FROM sector_list WHERE sector_id = ?', (sector_id,)).fetchone()
        if not sect:
            return {'success': False, 'error': f'Sector {sector_id} no existe'}
        
        # Actualizar o insertar
        conn.execute(
            '''INSERT INTO instrument_sectors (ticker, sector_id) VALUES (?, ?)
               ON CONFLICT (ticker) DO UPDATE SET sector_id = excluded.sector_id'''
            if 'INSERT OR REPLACE' not in conn.execute("SELECT 1").fetch() else
            '''REPLACE INTO instrument_sectors (ticker, sector_id) VALUES (?, ?)''',
            (ticker, sector_id)
        )
        
        return {'success': True, 'ticker': ticker, 'sector_id': sector_id}
    except Exception as e:
        # Fallback: DELETE + INSERT
        try:
            conn.execute('DELETE FROM instrument_sectors WHERE ticker = ?', (ticker,))
            conn.execute('INSERT INTO instrument_sectors (ticker, sector_id) VALUES (?, ?)', (ticker, sector_id))
            return {'success': True, 'ticker': ticker, 'sector_id': sector_id}
        except Exception as e2:
            return {'success': False, 'error': str(e2)}


def get_instrument_sector(ticker: str, conn=None) -> dict | None:
    """Obtiene el sector asignado a un instrumento."""
    if conn is None:
        conn = duckdb.connect(str(DB_PATH))
    
    result = conn.execute(
        '''SELECT isec.ticker, isec.sector_id, sl.sector_name, sl.color
           FROM instrument_sectors isec
           LEFT JOIN sector_list sl ON isec.sector_id = sl.sector_id
           WHERE isec.ticker = ?''',
        (ticker,)
    ).fetchone()
    
    if not result:
        return None
    
    return {
        'ticker': result[0],
        'sector_id': result[1],
        'sector_name': result[2],
        'color': result[3]
    }


def list_instruments_with_sectors(conn=None) -> list:
    """Retorna todos los instrumentos con sus sectores asignados."""
    if conn is None:
        conn = duckdb.connect(str(DB_PATH))
    
    result = conn.execute(
        '''SELECT i.ticker, i.nombre, i.tipo, i.moneda_base,
                  COALESCE(isec.sector_id, 0) as sector_id,
                  COALESCE(sl.sector_name, 'Sin sector') as sector_name,
                  COALESCE(sl.color, '#808080') as color
           FROM instruments i
           LEFT JOIN instrument_sectors isec ON i.ticker = isec.ticker
           LEFT JOIN sector_list sl ON isec.sector_id = sl.sector_id
           ORDER BY i.ticker'''
    ).fetchall()
    
    return [
        {
            'ticker': r[0],
            'nombre': r[1],
            'tipo': r[2],
            'moneda_base': r[3],
            'sector_id': r[4],
            'sector_name': r[5],
            'color': r[6]
        }
        for r in result
    ]


if __name__ == '__main__':
    print('[LOG] Inicializando BD y sectores...')
    from setup_db import create_schema
    
    conn = duckdb.connect(str(DB_PATH))
    create_schema(conn)
    init_sectors(conn)
    
    print()
    print('[LOG] Sectores disponibles:')
    for s in list_sectors(conn):
        print(f'  {s["id"]:2}. {s["name"]:<25} {s["color"]}')
    
    print()
    print('[LOG] Instrumentos:')
    for inst in list_instruments_with_sectors(conn):
        print(f'  {inst["ticker"]:<8} {inst["nombre"]:<30} → {inst["sector_name"]}')

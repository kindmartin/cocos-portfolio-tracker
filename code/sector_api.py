"""
sector_api.py — Endpoints Flask para gestión de sectores.

Endpoints:
  GET  /api/sectors                      - Lista todos los sectores
  POST /api/sectors                      - Crear nuevo sector
  GET  /api/sectors/instruments          - Instrumentos con sus sectores
  POST /api/sectors/assign               - Asignar sector a instrumento
  GET  /api/sectors/instrument/<ticker>  - Obtener sector de instrumento
"""
from flask import Blueprint, request, jsonify
import duckdb
from pathlib import Path
from sector_manager import (
    list_sectors,
    add_sector,
    delete_sector,
    assign_sector,
    get_instrument_sector,
    list_instruments_with_sectors,
)
from setup_db import DB_PATH

# Detectar ruta base
_base_dir = Path(__file__).parent
if _base_dir.name == "code":
    _base_dir = _base_dir.parent

sector_bp = Blueprint('sectors', __name__, url_prefix='/api/sectors')


def get_conn():
    """Obtiene conexión a BD."""
    return duckdb.connect(str(DB_PATH))


@sector_bp.route('', methods=['GET'])
def get_sectors():
    """Retorna lista de sectores."""
    try:
        sectors = list_sectors(get_conn())
        return jsonify({'success': True, 'data': sectors})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@sector_bp.route('', methods=['POST'])
def create_sector():
    """Crea un nuevo sector."""
    try:
        data = request.json or {}
        name = data.get('name')
        color = data.get('color', '#808080')
        
        if not name:
            return jsonify({'success': False, 'error': 'Nombre requerido'}), 400
        
        result = add_sector(name, color, get_conn())
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@sector_bp.route('/<int:sector_id>', methods=['DELETE'])
def delete(sector_id):
    """Elimina un sector."""
    try:
        if not sector_id:
            return jsonify({'success': False, 'error': 'ID de sector requerido'}), 400
        
        result = delete_sector(sector_id, get_conn())
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@sector_bp.route('/instruments', methods=['GET'])
def get_instruments():
    """Retorna instrumentos con sus sectores asignados."""
    try:
        instruments = list_instruments_with_sectors(get_conn())
        return jsonify({'success': True, 'data': instruments})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@sector_bp.route('/assign', methods=['POST'])
def assign():
    """Asigna sector a instrumento."""
    try:
        data = request.json or {}
        ticker = data.get('ticker')
        sector_id = data.get('sector_id')
        
        if not ticker or not sector_id:
            return jsonify({'success': False, 'error': 'Ticker y sector_id requeridos'}), 400
        
        result = assign_sector(ticker, sector_id, get_conn())
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@sector_bp.route('/instrument/<ticker>', methods=['GET'])
def get_instrument_sector_api(ticker):
    """Obtiene sector asignado a un instrumento."""
    try:
        sector = get_instrument_sector(ticker, get_conn())
        if not sector:
            return jsonify({'success': True, 'data': None})
        return jsonify({'success': True, 'data': sector})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@sector_bp.route('/export', methods=['GET'])
def export_sectors():
    """Exporta sectores y asignaciones como JSON descargable."""
    import json
    from flask import Response
    try:
        conn = get_conn()
        sectors = conn.execute(
            'SELECT sector_id, sector_name, color FROM sector_list ORDER BY sector_name'
        ).fetchall()
        assignments = conn.execute('''
            SELECT isec.ticker, sl.sector_name
            FROM instrument_sectors isec
            JOIN sector_list sl ON sl.sector_id = isec.sector_id
            ORDER BY sl.sector_name, isec.ticker
        ''').fetchall()
        conn.close()

        data = {
            '_description': 'Sectores exportados desde Cocos Portfolio Tracker',
            'sectors': [{'id': s[0], 'name': s[1], 'color': s[2]} for s in sectors],
            'assignments': {a[0]: a[1] for a in assignments},
        }
        return Response(
            json.dumps(data, ensure_ascii=False, indent=2),
            mimetype='application/json',
            headers={'Content-Disposition': 'attachment; filename=sectors_export.json'}
        )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@sector_bp.route('/import', methods=['POST'])
def import_sectors():
    """Importa sectores y asignaciones desde JSON. Merge: agrega sin borrar existentes."""
    try:
        data = request.json or {}
        sectors_in  = data.get('sectors', [])
        assigns_in  = data.get('assignments', {})

        if not sectors_in and not assigns_in:
            return jsonify({'success': False, 'error': 'JSON vacío o formato incorrecto'}), 400

        conn = get_conn()

        # Insertar sectores nuevos (ignorar duplicados por nombre)
        existing_names = {r[0] for r in conn.execute('SELECT sector_name FROM sector_list').fetchall()}
        added_sectors = 0
        for s in sectors_in:
            name  = s.get('name', '').strip()
            color = s.get('color', '#808080')
            if name and name not in existing_names:
                conn.execute(
                    'INSERT INTO sector_list (sector_name, color) VALUES (?, ?)', (name, color)
                )
                existing_names.add(name)
                added_sectors += 1

        # Reconstruir mapa nombre → id
        name_to_id = {r[0]: r[1] for r in conn.execute('SELECT sector_name, sector_id FROM sector_list').fetchall()}

        # Insertar asignaciones nuevas (REPLACE para actualizar si ya existe)
        added_assigns = 0
        for ticker, sector_name in assigns_in.items():
            sector_id = name_to_id.get(sector_name)
            if not sector_id:
                continue
            conn.execute(
                '''INSERT INTO instrument_sectors (ticker, sector_id)
                   VALUES (?, ?)
                   ON CONFLICT (ticker) DO UPDATE SET sector_id = excluded.sector_id''',
                (ticker, sector_id)
            )
            added_assigns += 1

        conn.close()
        return jsonify({
            'success': True,
            'added_sectors': added_sectors,
            'added_assignments': added_assigns,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

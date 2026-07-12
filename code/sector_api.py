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

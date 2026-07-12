#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_db_to_csv.py — Exporta movimientos y snapshots de la BD DuckDB a CSVs tipo COCOS.

Propósito:
  Uniformizar la ingesta: en lugar de depender del Excel histórico,
  exportar TODOS los datos (pasados + nuevos) desde la BD.
  La BD es la fuente única de verdad.

Uso:
  python export_db_to_csv.py                 # muestra preview
  python export_db_to_csv.py --execute       # genera archivos
  python export_db_to_csv.py --db ruta.duckdb

Genera:
  CSV Cocos/movimientos/movimientos_YYYYMM.csv (mensual)
  CSV Cocos/snapshots/portfolio_report_YYYYMMDD.csv (diario)
"""
import argparse
from datetime import datetime
from pathlib import Path
import pandas as pd
import duckdb

# Detectar ruta base (funciona en .exe y script)
_base_dir = Path(__file__).parent
if _base_dir.name == "code":
    _base_dir = _base_dir.parent

DB_PATH = _base_dir / "data" / "db" / "portfolio.duckdb"
CSV_MOV_DIR = _base_dir / "data" / "csv" / "movimientos"
CSV_SNAP_DIR = _base_dir / "data" / "csv" / "snapshots"

COCOS_MOV_COLUMNS = [
    'nroTicket', 'nroComprobante', 'fechaEjecucion', 'fechaLiquidacion',
    'tipoOperacion', 'instrumento', 'moneda', 'mercado',
    'cantidad', 'precio', 'montoBruto', 'comision', 'ddmm', 'iva', 'otros', 'total'
]

COCOS_SNAP_COLUMNS = [
    'instrumento', 'cantidad', 'precio', 'total'
]


def export_movimientos(conn, output_dir: Path) -> dict:
    """Exporta transactions de BD a movimientos_YYYYMM.csv"""
    
    query = """
    SELECT 
        nro_ticket AS nroTicket,
        COALESCE(nro_comprobante, '') AS nroComprobante,
        STRFTIME(fecha_op, '%d-%m-%Y') AS fechaEjecucion,
        STRFTIME(fecha_liq, '%d-%m-%Y') AS fechaLiquidacion,
        tipo_op AS tipoOperacion,
        CONCAT(COALESCE(instrumento_raw, ticker), ' (', ticker, ')') AS instrumento,
        moneda,
        COALESCE(mercado, '') AS mercado,
        cantidad,
        precio,
        monto_bruto AS montoBruto,
        COALESCE(comision, 0) AS comision,
        '' AS ddmm,
        COALESCE(iva, 0) AS iva,
        0 AS otros,
        total,
        fecha_op
    FROM transactions
    WHERE ticker IS NOT NULL AND ticker != 'nan'
    ORDER BY fecha_op
    """
    
    df = conn.execute(query).fetch_df()
    
    if df.empty:
        print("[WARN] No hay transacciones en la BD")
        return {}
    
    # Agrupar por mes
    df['year_month'] = df['fecha_op'].dt.strftime('%Y%m')
    grouped = {}
    
    for month, group in df.groupby('year_month'):
        group_clean = group.drop(['fecha_op', 'year_month'], axis=1)
        grouped[month] = group_clean
    
    return grouped


def export_snapshots(conn, output_dir: Path) -> dict:
    """Exporta snapshots de BD a portfolio_report_YYYYMMDD.csv"""
    
    query = """
    SELECT 
        s.snapshot_date,
        CONCAT(COALESCE(i.nombre, s.ticker), ' (', s.ticker, ')') AS instrumento,
        s.cantidad,
        s.precio,
        s.total_raw AS total,
        s.snapshot_date
    FROM snapshots s
    LEFT JOIN instruments i ON s.ticker = i.ticker
    WHERE s.ticker IS NOT NULL AND s.ticker != 'nan'
    ORDER BY s.snapshot_date, s.ticker
    """
    
    df = conn.execute(query).fetch_df()
    
    if df.empty:
        print("[WARN] No hay snapshots en la BD")
        return {}
    
    # Agrupar por fecha
    df['snapshot_date_str'] = df['snapshot_date'].dt.strftime('%Y%m%d')
    grouped = {}
    
    for date_str, group in df.groupby('snapshot_date_str'):
        # Ya tienen los nombres correctos del SELECT
        group_clean = group[['instrumento', 'cantidad', 'precio', 'total']].copy()
        grouped[date_str] = group_clean
    
    return grouped


def preview_movimientos(grouped: dict):
    """Muestra preview de movimientos"""
    print("\n📊 MOVIMIENTOS (por mes):")
    if not grouped:
        print("  (sin datos)")
        return
    
    total_rows = 0
    for month in sorted(grouped.keys()):
        df = grouped[month]
        total_rows += len(df)
        print(f"  movimientos_{month}.csv → {len(df)} transacciones")
    
    print(f"  TOTAL: {total_rows} transacciones")
    
    # Primeras 3 filas
    first_month = sorted(grouped.keys())[0]
    print(f"\n  Primeros registros ({first_month}):")
    print(grouped[first_month][['fechaEjecucion', 'tipoOperacion', 'instrumento', 'cantidad', 'total']].head(3).to_string(index=False))


def preview_snapshots(grouped: dict):
    """Muestra preview de snapshots"""
    print("\n📸 SNAPSHOTS (por fecha):")
    if not grouped:
        print("  (sin datos)")
        return
    
    total_rows = 0
    for date_str in sorted(grouped.keys())[:10]:  # Solo primeras 10 fechas
        df = grouped[date_str]
        total_rows += len(df)
        print(f"  portfolio_report_{date_str}.csv → {len(df)} instrumentos")
    
    if len(grouped) > 10:
        print(f"  ... y {len(grouped) - 10} más")
    
    print(f"  TOTAL: {total_rows} snapshot rows")
    
    # Primeros snapshot
    first_date = sorted(grouped.keys())[0]
    print(f"\n  Primeros registros ({first_date}):")
    print(grouped[first_date][['instrumento', 'cantidad', 'total']].head(3).to_string(index=False))


def execute_movimientos(grouped: dict, output_dir: Path) -> int:
    """Escribe movimientos a archivos"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    created = 0
    for month in sorted(grouped.keys()):
        df = grouped[month]
        csv_path = output_dir / f"movimientos_{month}.csv"
        
        # Escribir con separador COCOS
        df_cocos = df[[c for c in COCOS_MOV_COLUMNS if c in df.columns]]
        df_cocos.to_csv(csv_path, sep=';', index=False, encoding='utf-8')
        print(f"  [OK] {csv_path.name}")
        created += 1
    
    return created


def execute_snapshots(grouped: dict, output_dir: Path) -> int:
    """Escribe snapshots a archivos"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    created = 0
    for date_str in sorted(grouped.keys()):
        df = grouped[date_str]
        csv_path = output_dir / f"portfolio_report_{date_str}.csv"
        
        df_cocos = df[[c for c in COCOS_SNAP_COLUMNS if c in df.columns]]
        df_cocos.to_csv(csv_path, sep=';', index=False, encoding='utf-8')
        
        if created < 3:  # Mostrar primeros 3
            print(f"  ✓ {csv_path.name}")
        elif created == 3:
            print(f"  ...")
        
        created += 1
    
    return created


def main():
    parser = argparse.ArgumentParser(description="Exporta BD a CSVs tipo COCOS")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--execute", action="store_true",
                        help="Generar archivos (sin flag solo preview)")
    args = parser.parse_args()
    
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: BD no encontrada: {db_path}")
        return 1
    
    print(f"[INFO] Conectando a BD: {db_path}")
    conn = duckdb.connect(str(db_path))
    
    # Movimientos
    print("\n[RUN] Exportando MOVIMIENTOS...")
    mov_grouped = export_movimientos(conn, CSV_MOV_DIR)
    preview_movimientos(mov_grouped)
    
    # Snapshots
    print("\n[RUN] Exportando SNAPSHOTS...")
    snap_grouped = export_snapshots(conn, CSV_SNAP_DIR)
    preview_snapshots(snap_grouped)
    
    # Ejecutar
    if args.execute:
        print("\n" + "=" * 80)
        print("[RUN] GENERANDO ARCHIVOS...")
        print("=" * 80)
        
        print("\n[OUT] Movimientos:")
        mov_count = execute_movimientos(mov_grouped, CSV_MOV_DIR)
        
        print("\n[OUT] Snapshots:")
        snap_count = execute_snapshots(snap_grouped, CSV_SNAP_DIR)
        
        print("\n" + "=" * 80)
        print(f"[SUCCESS] {mov_count} movimientos + {snap_count} snapshots exportados")
        print("=" * 80)
    else:
        print("\n" + "=" * 80)
        print("Para generar archivos, ejecuta con --execute")
        print("=" * 80)
    
    conn.close()
    return 0


if __name__ == '__main__':
    exit(main())

#!/usr/bin/env python3
"""
launcher_dashboard.py — Lanzador interactivo del Dashboard
"""

import subprocess
import sys
import time
from pathlib import Path

# Detectar ruta base
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent
    if BASE_DIR.name == "code":
        BASE_DIR = BASE_DIR.parent

DB_PATH = BASE_DIR / "data" / "db" / "portfolio.duckdb"


def check_db():
    """Verifica que la BD existe"""
    if not DB_PATH.exists():
        print("\n" + "=" * 60)
        print("[ERROR] Base de datos no encontrada")
        print(f"        {DB_PATH}")
        print("=" * 60)
        print("\nEjecutá primero:")
        print("  python etl.py")
        print("\nPara cargar CSVs en: 'csv for ingest/'\n")
        return False
    return True


def show_menu():
    """Muestra menú de opciones"""
    print("\n" + "=" * 60)
    print(" 📊 PORTFOLIO MANAGER — Dashboard")
    print("=" * 60)
    print("\n[1] Lanzar Dashboard (puerto 8050)")
    print("[2] Lanzar Dashboard (puerto custom)")
    print("[3] Lanzar sin abrir navegador")
    print("[4] Mostrar info de la BD")
    print("[5] Volver atrás")
    print("\n" + "-" * 60)
    choice = input("Selecciona opción (1-5): ").strip()
    return choice


def launch_dashboard(port=8050, no_browser=False):
    """Lanza el dashboard con opciones"""
    dashboard_py = BASE_DIR / "code" / "portfolio_dashboard.py"
    
    cmd = ["python", str(dashboard_py), "--port", str(port)]
    if no_browser:
        cmd.append("--no-browser")
    
    print("\n" + "=" * 60)
    print("[RUN] Iniciando Dashboard...")
    print(f"[URL] http://localhost:{port}")
    print(f"[DB]  {DB_PATH}")
    print("[CTRL+C para detener]")
    print("=" * 60 + "\n")
    
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        print("\n[STOP] Dashboard detenido")
    except Exception as e:
        print(f"\n[ERROR] {e}")


def show_db_info():
    """Muestra información de la BD"""
    try:
        import duckdb
        
        if not DB_PATH.exists():
            print("\n[ERROR] BD no existe")
            return
        
        print("\n" + "=" * 60)
        print(" BD INFO")
        print("=" * 60)
        
        conn = duckdb.connect(str(DB_PATH))
        
        # Snapshots
        snap_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchall()[0][0]
        snap_dates = conn.execute("SELECT COUNT(DISTINCT snapshot_date) FROM snapshots").fetchall()[0][0]
        print(f"\n[SNAPSHOTS] {snap_dates} fechas | {snap_count} registros")
        
        # Transactions
        trans_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchall()[0][0]
        trans_months = conn.execute("SELECT COUNT(DISTINCT DATE_TRUNC('month', transaction_date)) FROM transactions").fetchall()[0][0]
        print(f"[TRANSACTIONS] {trans_months} meses | {trans_count} registros")
        
        # Instruments
        inst_count = conn.execute("SELECT COUNT(*) FROM instruments").fetchall()[0][0]
        print(f"[INSTRUMENTS] {inst_count} instrumentos")
        
        # FX rates
        fx_count = conn.execute("SELECT COUNT(*) FROM fx_rates").fetchall()[0][0]
        print(f"[FX RATES] {fx_count} registros")
        
        # Tamaño archivo
        size_mb = DB_PATH.stat().st_size / (1024 * 1024)
        print(f"\n[SIZE] {size_mb:.1f} MB")
        print(f"[PATH] {DB_PATH}")
        print("=" * 60)
        
        conn.close()
    
    except Exception as e:
        print(f"\n[ERROR] {str(e)}")


def main():
    """Main loop"""
    if not check_db():
        return
    
    while True:
        choice = show_menu()
        
        if choice == "1":
            launch_dashboard()
        
        elif choice == "2":
            try:
                port = int(input("\nPuerto (default 8050): ").strip() or "8050")
                if not (1024 <= port <= 65535):
                    print("[ERROR] Puerto debe estar entre 1024 y 65535")
                    continue
                launch_dashboard(port=port)
            except ValueError:
                print("[ERROR] Puerto inválido")
        
        elif choice == "3":
            launch_dashboard(no_browser=True)
        
        elif choice == "4":
            show_db_info()
        
        elif choice == "5":
            print("\n[SALIR] Hasta luego!\n")
            break
        
        else:
            print("\n[ERROR] Opción no válida")


if __name__ == "__main__":
    main()

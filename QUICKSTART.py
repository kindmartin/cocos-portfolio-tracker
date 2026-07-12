#!/usr/bin/env python3
"""
QUICKSTART.py — Guía interactiva de inicio rápido
Detecta el estado del sistema y guía al usuario
"""

import sys
from pathlib import Path
import subprocess

# Detectar ruta base
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

DB_PATH = BASE_DIR / "data" / "db" / "portfolio.duckdb"
CODE_DIR = BASE_DIR / "code"
INGEST_DIR = BASE_DIR / "csv for ingest"


def check_requirements():
    """Verifica dependencias"""
    missing = []
    
    try:
        import duckdb
    except ImportError:
        missing.append("duckdb")
    
    try:
        import pandas
    except ImportError:
        missing.append("pandas")
    
    try:
        import dash
    except ImportError:
        missing.append("dash")
    
    try:
        import plotly
    except ImportError:
        missing.append("plotly")
    
    try:
        import flask
    except ImportError:
        missing.append("flask")
    
    return missing


def print_banner():
    """Imprime encabezado"""
    print("\n" + "=" * 70)
    print("  🎯 PORTFOLIO MANAGER — GUÍA DE INICIO RÁPIDO")
    print("=" * 70 + "\n")


def check_status():
    """Verifica estado del sistema"""
    print("[CHECK] Verificando estado del sistema...\n")
    
    # Check dependencias
    missing = check_requirements()
    if missing:
        print(f"[WARN] Faltan dependencias: {', '.join(missing)}")
        print(f"\nEjecutá:")
        print(f"  cd {CODE_DIR}")
        print(f"  pip install -r requirements.txt\n")
        return False
    
    # Check BD
    if not DB_PATH.exists():
        print("[WARN] Base de datos no existe")
        print(f"       {DB_PATH}\n")
        return False
    
    # Check CSVs en ingest
    csv_files = list(INGEST_DIR.glob("*.csv"))
    if csv_files:
        print(f"[INFO] {len(csv_files)} archivos esperando en 'csv for ingest/'\n")
    
    print("[OK] Sistema listo!\n")
    return True


def show_main_menu():
    """Menú principal de quickstart"""
    print("=" * 70)
    print("¿Qué querés hacer?\n")
    print("[1] 🚀 LANZAR EL PORTAL (Dashboard)")
    print("[2] 📥 CARGAR CSVs (ETL Manual)")
    print("[3] 🤖 MONITOREAR (vigilancia automática)")
    print("[4] 🌐 API + UI (control remoto)")
    print("[5] ℹ️  INFORMACIÓN (estado de la BD)")
    print("[6] 🛠️  SETUP COMPLETO (instalar todo)")
    print("[7] ❌ SALIR\n")
    print("-" * 70)
    
    choice = input("Opción (1-7): ").strip()
    return choice


def launch_dashboard():
    """Lanza el dashboard"""
    print("\n[RUN] Lanzando Dashboard en puerto 8050...")
    print("      Abre http://localhost:8050 automáticamente")
    print("      Presiona Ctrl+C para detener\n")
    print("-" * 70 + "\n")
    
    try:
        subprocess.run(
            ["python", str(CODE_DIR / "portfolio_dashboard.py")],
            check=False,
            cwd=str(CODE_DIR)
        )
    except KeyboardInterrupt:
        print("\n[STOP] Dashboard detenido")
    except Exception as e:
        print(f"[ERROR] {str(e)}")


def load_csvs():
    """Lanza ETL"""
    if not csv_files_exist():
        print("\n[WARN] No hay archivos en 'csv for ingest/'")
        print(f"       Copialos a: {INGEST_DIR}\n")
        return
    
    print("\n[RUN] Ejecutando ETL...")
    print("-" * 70 + "\n")
    
    try:
        subprocess.run(
            ["python", str(CODE_DIR / "etl.py")],
            check=False,
            cwd=str(CODE_DIR)
        )
    except KeyboardInterrupt:
        print("\n[STOP] ETL cancelado")
    except Exception as e:
        print(f"[ERROR] {str(e)}")


def run_monitor():
    """Lanza monitor"""
    print("\n[RUN] Monitor automático (revisará cada 30 segundos)")
    print("      Presiona Ctrl+C para detener\n")
    print("-" * 70 + "\n")
    
    try:
        subprocess.run(
            ["python", str(CODE_DIR / "ingest_monitor.py")],
            check=False,
            cwd=str(CODE_DIR)
        )
    except KeyboardInterrupt:
        print("\n[STOP] Monitor detenido")
    except Exception as e:
        print(f"[ERROR] {str(e)}")


def run_api():
    """Lanza API"""
    print("\n[RUN] Iniciando API en puerto 5000...")
    print("      UI Web: http://localhost:5000/ingest_ui.html")
    print("      Status: http://localhost:5000/api/ingest/status")
    print("      Presiona Ctrl+C para detener\n")
    print("-" * 70 + "\n")
    
    try:
        subprocess.run(
            ["python", str(CODE_DIR / "ingest_api.py")],
            check=False,
            cwd=str(CODE_DIR)
        )
    except KeyboardInterrupt:
        print("\n[STOP] API detenido")
    except Exception as e:
        print(f"[ERROR] {str(e)}")


def show_info():
    """Muestra información de la BD"""
    try:
        import duckdb
        
        if not DB_PATH.exists():
            print("\n[ERROR] BD no existe\n")
            return
        
        print("\n" + "=" * 70)
        print("  BD INFO")
        print("=" * 70 + "\n")
        
        conn = duckdb.connect(str(DB_PATH))
        
        snap_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchall()[0][0]
        snap_dates = conn.execute("SELECT COUNT(DISTINCT snapshot_date) FROM snapshots").fetchall()[0][0]
        print(f"[SNAPSHOTS] {snap_dates} fechas | {snap_count} registros")
        
        trans_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchall()[0][0]
        trans_months = conn.execute("SELECT COUNT(DISTINCT DATE_TRUNC('month', transaction_date)) FROM transactions").fetchall()[0][0]
        print(f"[TRANSACTIONS] {trans_months} meses | {trans_count} registros")
        
        inst_count = conn.execute("SELECT COUNT(*) FROM instruments").fetchall()[0][0]
        print(f"[INSTRUMENTS] {inst_count} instrumentos")
        
        fx_count = conn.execute("SELECT COUNT(*) FROM fx_rates").fetchall()[0][0]
        print(f"[FX RATES] {fx_count} registros")
        
        size_mb = DB_PATH.stat().st_size / (1024 * 1024)
        print(f"\n[SIZE] {size_mb:.1f} MB")
        print(f"[PATH] {DB_PATH}")
        
        csv_files = list(INGEST_DIR.glob("*.csv"))
        if csv_files:
            print(f"\n[INGEST] {len(csv_files)} archivos listos para procesar")
        
        print("\n" + "=" * 70 + "\n")
        
        conn.close()
    except Exception as e:
        print(f"[ERROR] {str(e)}\n")


def full_setup():
    """Setup completo"""
    print("\n" + "=" * 70)
    print("  SETUP COMPLETO")
    print("=" * 70)
    
    # Check dependencias
    missing = check_requirements()
    if missing:
        print(f"\n[1/3] Instalando dependencias...")
        print(f"      {', '.join(missing)}\n")
        
        try:
            result = subprocess.run(
                ["pip", "install", "-r", str(CODE_DIR / "requirements.txt")],
                check=False,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print("[OK] Dependencias instaladas\n")
            else:
                print("[ERROR] No se pudieron instalar dependencias\n")
                print(result.stderr)
                return
        except Exception as e:
            print(f"[ERROR] {str(e)}\n")
            return
    else:
        print("\n[OK] Dependencias ya instaladas\n")
    
    # Create DB
    if not DB_PATH.exists():
        print("[2/3] Creando base de datos...")
        try:
            result = subprocess.run(
                ["python", str(CODE_DIR / "setup_db.py")],
                check=False,
                capture_output=True,
                text=True,
                cwd=str(CODE_DIR)
            )
            if result.returncode == 0:
                print("[OK] BD creada\n")
            else:
                print("[ERROR] No se pudo crear la BD\n")
                return
        except Exception as e:
            print(f"[ERROR] {str(e)}\n")
            return
    else:
        print("[OK] BD ya existe\n")
    
    # Load initial data
    csv_files = list(INGEST_DIR.glob("*.csv"))
    if csv_files:
        print(f"[3/3] Cargando {len(csv_files)} CSVs iniciales...")
        try:
            result = subprocess.run(
                ["python", str(CODE_DIR / "etl.py")],
                check=False,
                capture_output=True,
                text=True,
                cwd=str(CODE_DIR)
            )
            if result.returncode == 0:
                print("[OK] CSVs cargados\n")
            else:
                print("[WARN] ETL completó con advertencias\n")
        except Exception as e:
            print(f"[ERROR] {str(e)}\n")
            return
    else:
        print("[INFO] No hay CSVs en 'csv for ingest/' para cargar inicialmente\n")
    
    print("=" * 70)
    print("[OK] SETUP COMPLETADO!\n")
    print("Próximo paso: Selecciona '1' para lanzar el Dashboard\n")


def csv_files_exist():
    """Verifica si hay CSVs para procesar"""
    return len(list(INGEST_DIR.glob("*.csv"))) > 0


def main():
    """Main loop"""
    print_banner()
    
    if not check_status():
        print("Ejecutá primero:")
        print(f"  cd {CODE_DIR}")
        print(f"  pip install -r requirements.txt\n")
        input("Presiona ENTER...")
        return
    
    while True:
        choice = show_main_menu()
        
        if choice == "1":
            if not DB_PATH.exists():
                print("\n[ERROR] BD no existe. Ejecutá '6' primero\n")
                input("Presiona ENTER...")
                continue
            launch_dashboard()
        
        elif choice == "2":
            if not DB_PATH.exists():
                print("\n[ERROR] BD no existe. Ejecutá '6' primero\n")
                input("Presiona ENTER...")
                continue
            load_csvs()
        
        elif choice == "3":
            if not DB_PATH.exists():
                print("\n[ERROR] BD no existe. Ejecutá '6' primero\n")
                input("Presiona ENTER...")
                continue
            run_monitor()
        
        elif choice == "4":
            if not DB_PATH.exists():
                print("\n[ERROR] BD no existe. Ejecutá '6' primero\n")
                input("Presiona ENTER...")
                continue
            run_api()
        
        elif choice == "5":
            show_info()
            input("Presiona ENTER...")
        
        elif choice == "6":
            full_setup()
            input("Presiona ENTER...")
        
        elif choice == "7":
            print("\n[SALIR] Hasta luego!\n")
            break
        
        else:
            print("\n[ERROR] Opción no válida\n")
            input("Presiona ENTER...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[STOP] Quickstart cerrado\n")
    except Exception as e:
        print(f"\n[ERROR] {str(e)}\n")

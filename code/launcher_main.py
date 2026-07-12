#!/usr/bin/env python3
"""
launcher_main.py — Lanzador maestro de Portfolio Manager
Interfaz unificada para: Dashboard, ETL, Monitor, API+UI
"""

import subprocess
import sys
from pathlib import Path

# Detectar ruta base
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent
    if BASE_DIR.name == "code":
        BASE_DIR = BASE_DIR.parent

DB_PATH = BASE_DIR / "data" / "db" / "portfolio.duckdb"
CODE_DIR = BASE_DIR / "code"


def check_db():
    """Verifica que la BD existe"""
    if not DB_PATH.exists():
        print("\n" + "=" * 70)
        print("[WARN] Base de datos no existe todavía")
        print("=" * 70)
        print("\nPrimer setup:")
        print("  1. python etl.py (carga CSVs iniciales)")
        print("  2. Luego lanza el Dashboard\n")
        return False
    return True


def print_header(title):
    """Imprime encabezado estilizado"""
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def show_main_menu():
    """Menú principal"""
    print_header("📊 PORTFOLIO MANAGER — Lanzador Principal")
    print("\n[COMPONENTES PRINCIPALES]")
    print("[1] 📈 Dashboard       → Vista web interactiva (puerto 8050)")
    print("[2] 🔄 ETL Manual      → Cargar CSVs desde 'csv for ingest/'")
    print("[3] 🤖 Monitor        → Vigilancia automática de ingestión")
    print("[4] 🌐 API + UI Web   → Control remoto + estadísticas")
    print("[5] 🛠️  Herramientas  → Exportar, resetear, utilities")
    print("[6] ❌ Salir\n")
    print("-" * 70)
    choice = input("Selecciona opción (1-6): ").strip()
    return choice


def show_dashboard_menu():
    """Menú del Dashboard"""
    print_header("📈 Dashboard")
    print("\n[1] Lanzar en puerto 8050 (default)")
    print("[2] Lanzar en puerto custom")
    print("[3] Lanzar sin abrir navegador")
    print("[4] Ver información de la BD")
    print("[5] Volver atrás\n")
    print("-" * 70)
    choice = input("Selecciona opción (1-5): ").strip()
    return choice


def show_etl_menu():
    """Menú del ETL"""
    print_header("🔄 ETL Manual")
    print("\n[1] Procesar todo (snapshots + transactions)")
    print("[2] Solo snapshots")
    print("[3] Solo transactions")
    print("[4] Con --force (reprocesar duplicados)")
    print("[5] Con --reset (limpiar e iniciar)")
    print("[6] Ver ayuda")
    print("[7] Volver atrás\n")
    print("-" * 70)
    choice = input("Selecciona opción (1-7): ").strip()
    return choice


def show_tools_menu():
    """Menú de herramientas"""
    print_header("🛠️  Herramientas")
    print("\n[1] Exportar datos a CSV")
    print("[2] Reset de base de datos")
    print("[3] Ver logs de ingestión")
    print("[4] Limpiar archivos de error")
    print("[5] Volver atrás\n")
    print("-" * 70)
    choice = input("Selecciona opción (1-5): ").strip()
    return choice


def run_command(cmd, description):
    """Ejecuta comando y maneja errores"""
    print(f"\n[RUN] {description}...")
    print("-" * 70)
    try:
        result = subprocess.run(cmd, check=False, cwd=str(CODE_DIR))
        if result.returncode != 0:
            print(f"\n[ERROR] Comando falló con código {result.returncode}")
        else:
            print(f"\n[OK] {description} completado")
    except KeyboardInterrupt:
        print(f"\n[STOP] {description} cancelado")
    except Exception as e:
        print(f"\n[ERROR] {str(e)}")
    
    input("\nPresiona ENTER para continuar...")


def dashboard_menu():
    """Manejo del menú Dashboard"""
    while True:
        choice = show_dashboard_menu()
        
        if choice == "1":
            run_command(["python", "portfolio_dashboard.py"], "Dashboard")
        
        elif choice == "2":
            try:
                port = input("\nPuerto (1024-65535, default 8050): ").strip() or "8050"
                port = int(port)
                if not (1024 <= port <= 65535):
                    print("[ERROR] Puerto inválido")
                    input("\nPresiona ENTER para continuar...")
                    continue
                run_command(["python", "portfolio_dashboard.py", "--port", str(port)], f"Dashboard puerto {port}")
            except ValueError:
                print("[ERROR] Puerto debe ser número")
                input("\nPresiona ENTER para continuar...")
        
        elif choice == "3":
            run_command(["python", "portfolio_dashboard.py", "--no-browser"], "Dashboard (sin navegador)")
        
        elif choice == "4":
            show_db_info()
            input("\nPresiona ENTER para continuar...")
        
        elif choice == "5":
            break
        
        else:
            print("[ERROR] Opción no válida")
            input("\nPresiona ENTER para continuar...")


def etl_menu():
    """Manejo del menú ETL"""
    while True:
        choice = show_etl_menu()
        
        if choice == "1":
            run_command(["python", "etl.py"], "ETL completo")
        elif choice == "2":
            run_command(["python", "etl.py", "--snapshots"], "ETL snapshots")
        elif choice == "3":
            run_command(["python", "etl.py", "--transactions"], "ETL transactions")
        elif choice == "4":
            run_command(["python", "etl.py", "--force"], "ETL con --force")
        elif choice == "5":
            confirm = input("\n⚠️  Esto BORRARÁ toda la BD. ¿Estás seguro? (s/n): ").strip().lower()
            if confirm == 's':
                run_command(["python", "etl.py", "--reset"], "ETL reset")
        elif choice == "6":
            run_command(["python", "etl.py", "--help"], "Ayuda ETL")
        elif choice == "7":
            break
        else:
            print("[ERROR] Opción no válida")
            input("\nPresiona ENTER para continuar...")


def tools_menu():
    """Manejo del menú Herramientas"""
    while True:
        choice = show_tools_menu()
        
        if choice == "1":
            run_command(["python", "export_db_to_csv.py", "--execute"], "Exportar datos")
        elif choice == "2":
            confirm = input("\n⚠️  Esto BORRARÁ toda la BD. ¿Estás seguro? (s/n): ").strip().lower()
            if confirm == 's':
                run_command(["python", "etl.py", "--reset"], "Reset BD")
        elif choice == "3":
            show_ingestion_logs()
            input("\nPresiona ENTER para continuar...")
        elif choice == "4":
            clean_errors()
            input("\nPresiona ENTER para continuar...")
        elif choice == "5":
            break
        else:
            print("[ERROR] Opción no válida")
            input("\nPresiona ENTER para continuar...")


def show_db_info():
    """Muestra información de la BD"""
    try:
        import duckdb
        
        if not DB_PATH.exists():
            print("\n[ERROR] BD no existe")
            return
        
        print_header("BD INFO")
        
        conn = duckdb.connect(str(DB_PATH))
        
        snap_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchall()[0][0]
        snap_dates = conn.execute("SELECT COUNT(DISTINCT snapshot_date) FROM snapshots").fetchall()[0][0]
        print(f"\n[SNAPSHOTS] {snap_dates} fechas | {snap_count} registros")
        
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
        print("=" * 70)
        
        conn.close()
    except Exception as e:
        print(f"[ERROR] {str(e)}")


def show_ingestion_logs():
    """Muestra logs de ingestión"""
    logs_dir = BASE_DIR / "data" / "ingest_logs"
    if not logs_dir.exists():
        print("\n[INFO] Sin logs de ingestión aún")
        return
    
    logs = sorted(logs_dir.glob("*.json"), reverse=True)[:10]
    print_header("Logs de Ingestión (últimos 10)")
    for log_file in logs:
        print(f"  {log_file.name}")
    print("=" * 70)


def clean_errors():
    """Limpia archivos de error"""
    errors_dir = BASE_DIR / "data" / "ingest_errors"
    if not errors_dir.exists():
        print("\n[INFO] Sin archivos de error")
        return
    
    error_files = list(errors_dir.glob("*"))
    if not error_files:
        print("\n[INFO] Sin archivos de error")
        return
    
    print_header("Archivos de Error")
    for f in error_files[:10]:
        print(f"  {f.name}")
    if len(error_files) > 10:
        print(f"  ... y {len(error_files) - 10} más")
    print(f"\nTotal: {len(error_files)} archivos")
    
    confirm = input("\n¿Eliminar todos? (s/n): ").strip().lower()
    if confirm == 's':
        for f in error_files:
            f.unlink()
        print("[OK] Archivos eliminados")


def main():
    """Main loop"""
    while True:
        choice = show_main_menu()
        
        if choice == "1":
            if not check_db():
                input("\nPresiona ENTER para continuar...")
                continue
            dashboard_menu()
        
        elif choice == "2":
            if not check_db():
                print("\nPrimero ejecutá: python etl.py")
                input("\nPresiona ENTER para continuar...")
                continue
            etl_menu()
        
        elif choice == "3":
            if not check_db():
                input("\nPresiona ENTER para continuar...")
                continue
            print_header("🤖 Monitor Automático")
            run_command(["python", "ingest_monitor.py", "--once"], "Monitor")
        
        elif choice == "4":
            if not check_db():
                input("\nPresiona ENTER para continuar...")
                continue
            print_header("🌐 API + UI Web")
            run_command(["python", "ingest_api.py"], "API")
        
        elif choice == "5":
            tools_menu()
        
        elif choice == "6":
            print("\n[SALIR] Hasta luego!\n")
            break
        
        else:
            print("[ERROR] Opción no válida")
            input("\nPresiona ENTER para continuar...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[STOP] Lanzador cerrado\n")
    except Exception as e:
        print(f"\n[ERROR FATAL] {str(e)}\n")

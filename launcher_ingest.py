#!/usr/bin/env python
"""
launcher_ingest.py — Launcher interactivo para opciones de ingestión.

Permite elegir entre:
1. Procesamiento manual único
2. Monitoreo automático  
3. API REST + UI web
"""
import subprocess
import sys
from pathlib import Path

_base_dir = Path(__file__).parent

def print_menu():
    print("\n" + "="*60)
    print("  🚀 Portfolio Manager - Opciones de Ingestión")
    print("="*60)
    print("\n1. 📤 Procesamiento Manual (una sola vez)")
    print("   └─ Procesa ahora todos los CSVs en 'csv for ingest/'")
    print("   └─ Útil para: ejecución puntual\n")
    
    print("2. 🔄 Monitoreo Automático (daemon background)")
    print("   └─ Verifica cada 30 segundos")
    print("   └─ Procesa automáticamente cuando hay nuevos CSVs")
    print("   └─ Útil para: procesamiento continuo\n")
    
    print("3. 🌐 API REST + UI Web")
    print("   └─ Inicia servidor en localhost:5000")
    print("   └─ UI disponible en ingest_ui.html")
    print("   └─ Útil para: control manual desde dashboard\n")
    
    print("4. 🎯 Opciones Avanzadas")
    print("   └─ --reset: borrar BD y recargar todo")
    print("   └─ --force: forzar recarga de duplicados")
    print("   └─ --snapshots: solo snapshots\n")
    
    print("5. ❌ Salir\n")

def run_manual_ingest():
    """Ejecuta ingestión manual única."""
    print("\n🤔 Opciones:")
    print("  1. Procesar todo (default)")
    print("  2. Solo snapshots")
    print("  3. Solo transacciones")
    print("  4. Forzar recarga (--force)")
    print("  5. Resetear BD completa (--reset)")
    
    choice = input("\nSeleccionar (1): ").strip() or "1"
    
    args = []
    if choice == "2":
        args = ["--snapshots"]
    elif choice == "3":
        args = ["--transactions"]
    elif choice == "4":
        args = ["--force"]
    elif choice == "5":
        print("\n⚠️  ADVERTENCIA: Esto borrará toda la BD y la recargará.")
        confirm = input("¿Continuar? (s/n): ").lower().strip()
        if confirm != 's':
            print("❌ Cancelado")
            return
        args = ["--reset"]
    
    print("\n▶️  Ejecutando ETL...")
    try:
        subprocess.run(
            ["python", str(_base_dir / "code" / "etl.py")] + args,
            check=True
        )
        print("\n✅ Ingestión completada")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error: {e}")
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")

def run_monitor():
    """Inicia monitor automático."""
    print("\n🤔 Opciones:")
    print("  1. Cada 30s (default)")
    print("  2. Cada 10s (más frecuente)")
    print("  3. Cada 5s (muy frecuente)")
    print("  4. Cada 60s (menos frecuente)")
    
    choice = input("\nSeleccionar (1): ").strip() or "1"
    
    intervals = {
        "1": 30,
        "2": 10,
        "3": 5,
        "4": 60
    }
    interval = intervals.get(choice, 30)
    
    print(f"\n🔄 Iniciando monitor (cada {interval}s)...")
    print("💡 Presiona Ctrl+C para detener\n")
    
    try:
        subprocess.run([
            "python", 
            str(_base_dir / "code" / "ingest_monitor.py"),
            "--interval", str(interval)
        ])
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitor detenido")
    except FileNotFoundError:
        print("❌ Error: ingest_monitor.py no encontrado")
    except Exception as e:
        print(f"❌ Error: {e}")

def run_api():
    """Inicia API REST."""
    print("\n🌐 Iniciando API REST...")
    print("📍 Servidor: http://localhost:5000")
    print("🎨 UI: " + str(_base_dir / "ingest_ui.html"))
    print("💡 Presiona Ctrl+C para detener\n")
    
    try:
        subprocess.run([
            "python",
            str(_base_dir / "code" / "ingest_api.py")
        ])
    except KeyboardInterrupt:
        print("\n\n⏹️  API detenido")
    except FileNotFoundError:
        print("❌ Error: ingest_api.py no encontrado")
    except ModuleNotFoundError:
        print("❌ Error: Flask no está instalado")
        print("   Ejecuta: pip install flask")
    except Exception as e:
        print(f"❌ Error: {e}")

def run_advanced():
    """Opciones avanzadas."""
    print("\n🎯 Opciones Avanzadas:")
    print("  1. Resetear BD completa (--reset)")
    print("  2. Forzar recarga de duplicados (--force)")
    print("  3. Solo procesar snapshots")
    print("  4. Solo procesar transacciones")
    print("  5. Cargar FX rates desde CSV personalizado")
    
    choice = input("\nSeleccionar (1): ").strip() or "1"
    
    args = []
    if choice == "1":
        print("\n⚠️  ADVERTENCIA: Esto borrará toda la BD.")
        confirm = input("¿Continuar? (s/n): ").lower().strip()
        if confirm != 's':
            print("❌ Cancelado")
            return
        args = ["--reset"]
    elif choice == "2":
        args = ["--force"]
    elif choice == "3":
        args = ["--snapshots"]
    elif choice == "4":
        args = ["--transactions"]
    elif choice == "5":
        csv_file = input("\nRuta del archivo CSV: ").strip()
        if not Path(csv_file).exists():
            print("❌ Archivo no encontrado")
            return
        args = ["--fx-csv", csv_file]
    
    print(f"\n▶️  Ejecutando: etl.py {' '.join(args)}")
    try:
        subprocess.run(
            ["python", str(_base_dir / "code" / "etl.py")] + args,
            check=True
        )
        print("\n✅ Operación completada")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error: {e}")
    except Exception as e:
        print(f"❌ Error inesperado: {e}")

def main():
    while True:
        print_menu()
        choice = input("Seleccionar opción: ").strip()
        
        if choice == "1":
            run_manual_ingest()
        elif choice == "2":
            run_monitor()
        elif choice == "3":
            run_api()
        elif choice == "4":
            run_advanced()
        elif choice == "5":
            print("\n👋 Adiós!")
            sys.exit(0)
        else:
            print("❌ Opción inválida")
        
        input("\nPresiona Enter para continuar...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Saliendo...")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error fatal: {e}")
        sys.exit(1)

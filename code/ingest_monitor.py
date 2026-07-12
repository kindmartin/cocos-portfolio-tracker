"""
ingest_monitor.py — Monitor automático de csv for ingest/

Uso:
  python ingest_monitor.py              # Monitorea continuamente
  python ingest_monitor.py --once       # Una sola ejecución
  python ingest_monitor.py --interval 5 # Cada 5 segundos (default: 30)
"""
import argparse
import time
import subprocess
from pathlib import Path
from datetime import datetime

# Detectar ruta base
_base_dir = Path(__file__).parent
if _base_dir.name == "code":
    _base_dir = _base_dir.parent

INGEST_DIR = _base_dir / "csv for ingest"
LOG_FILE = _base_dir / "ingest_monitor.log"


def append_log(message: str):
    """Agrega mensaje al log del monitor."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {message}\n"
    print(log_msg.strip())
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_msg)


def check_and_ingest():
    """Verifica si hay nuevos CSVs y ejecuta ETL si es necesario."""
    csv_files = list(INGEST_DIR.glob("*.csv"))
    
    if not csv_files:
        return False
    
    append_log(f"[OK] Detectados {len(csv_files)} archivo(s) en 'csv for ingest'")
    
    try:
        etl_script = _base_dir / "code" / "etl.py"
        result = subprocess.run(
            ["python", str(etl_script)],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            append_log("[OK] ETL completado exitosamente")
            return True
        else:
            append_log(f"[ERROR] ETL falló: {result.stderr}")
            return False
    
    except subprocess.TimeoutExpired:
        append_log("[ERROR] ETL tardó más de 5 minutos (timeout)")
        return False
    except Exception as e:
        append_log(f"[ERROR] Error ejecutando ETL: {str(e)}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Monitor automático de csv for ingest/")
    parser.add_argument('--once',     action='store_true', help='Ejecuta una sola vez')
    parser.add_argument('--interval', type=int, default=30, help='Intervalo en segundos (default: 30)')
    args = parser.parse_args()
    
    append_log("[START] Monitor iniciado")
    append_log(f"[PATH] Monitoreando: {INGEST_DIR}")
    append_log(f"[TIME] Intervalo: {args.interval}s")
    
    try:
        if args.once:
            check_and_ingest()
            append_log("[OK] Verificación única completada")
        else:
            while True:
                check_and_ingest()
                time.sleep(args.interval)
    
    except KeyboardInterrupt:
        append_log("[STOP] Monitor detenido por usuario")
    except Exception as e:
        append_log(f"[ERROR] Error fatal: {str(e)}")


if __name__ == '__main__':
    main()

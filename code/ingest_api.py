"""
ingest_api.py — API REST para controlar ingestión desde el dashboard.

Endpoints:
  GET  /api/ingest/status      - Estado actual de ingestión
  POST /api/ingest/trigger     - Dispara ingestión manual
  GET  /api/ingest/logs        - Lista últimos logs
  GET  /api/ingest/logs/<id>   - Detalle de un log específico
"""
from flask import Flask, jsonify, request, send_file
from pathlib import Path
import json
import subprocess
import threading
from datetime import datetime

# Detectar ruta base (funciona en .exe y en script)
import sys
if getattr(sys, 'frozen', False):
    _base_dir = Path(sys.executable).parent
else:
    _base_dir = Path(__file__).parent
    if _base_dir.name == "code":
        _base_dir = _base_dir.parent

INGEST_DIR = _base_dir / "csv for ingest"
LOGS_DIR = _base_dir / "data" / "ingest_logs"

app = Flask(__name__)

# Estado global
ingest_state = {
    "running": False,
    "last_run": None,
    "current_files": 0,
    "message": "Ready"
}


@app.route("/api/ingest/status", methods=["GET"])
def ingest_status():
    """Retorna estado actual de ingestión."""
    csv_count = len(list(INGEST_DIR.glob("*.csv")))
    
    return jsonify({
        "running": ingest_state["running"],
        "pending_files": csv_count,
        "last_run": ingest_state["last_run"],
        "message": ingest_state["message"]
    })


@app.route("/api/ingest/trigger", methods=["POST"])
def trigger_ingest():
    """Dispara una ingestión manual en background."""
    if ingest_state["running"]:
        return jsonify({"error": "Ingestión ya en progreso"}), 409
    
    csv_files = list(INGEST_DIR.glob("*.csv"))
    if not csv_files:
        return jsonify({"error": "No hay archivos para ingestar"}), 400
    
    # Ejecutar ETL en thread separado
    def run_etl():
        ingest_state["running"] = True
        ingest_state["message"] = "Procesando..."
        ingest_state["current_files"] = len(csv_files)
        
        try:
            etl_script = _base_dir / "code" / "etl.py"
            result = subprocess.run(
                ["python", str(etl_script)],
                capture_output=True,
                text=True,
                timeout=600
            )
            
            if result.returncode == 0:
                ingest_state["message"] = "[OK] Completado"
                ingest_state["last_run"] = datetime.now().isoformat()
            else:
                ingest_state["message"] = f"[ERROR] Error: {result.stderr[:100]}"
        
        except subprocess.TimeoutExpired:
            ingest_state["message"] = "[ERROR] Timeout (>10 min)"
        except Exception as e:
            ingest_state["message"] = f"[ERROR] {str(e)[:100]}"
        
        finally:
            ingest_state["running"] = False
    
    thread = threading.Thread(target=run_etl, daemon=True)
    thread.start()
    
    return jsonify({
        "status": "started",
        "files": len(csv_files),
        "message": "Ingestión iniciada en background"
    }), 202


@app.route("/api/ingest/logs", methods=["GET"])
def list_logs():
    """Lista los últimos 10 logs de ingestión."""
    logs = []
    log_files = sorted(LOGS_DIR.glob("ingest_*.json"), reverse=True)[:10]
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logs.append({
                    "session_id": data.get("session_id"),
                    "start_time": data.get("start_time"),
                    "end_time": data.get("end_time"),
                    "status": data.get("status"),
                    "files_processed": data.get("files_processed"),
                    "files_success": data.get("files_success"),
                    "files_error": data.get("files_error")
                })
        except Exception:
            pass
    
    return jsonify({"logs": logs})


@app.route("/api/ingest/logs/<session_id>", methods=["GET"])
def get_log_detail(session_id):
    """Retorna detalles completos de un log específico."""
    # Buscar archivo de log
    log_file = LOGS_DIR / f"ingest_{session_id}.json"
    
    if not log_file.exists():
        return jsonify({"error": "Log no encontrado"}), 404
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ingest/logs/<session_id>/download", methods=["GET"])
def download_log(session_id):
    """Descarga un archivo de log JSON."""
    log_file = LOGS_DIR / f"ingest_{session_id}.json"
    
    if not log_file.exists():
        return jsonify({"error": "Log no encontrado"}), 404
    
    return send_file(log_file, as_attachment=True, download_name=log_file.name)


@app.route("/api/ingest/health", methods=["GET"])
def health():
    """Health check."""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat()
    })


if __name__ == '__main__':
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    print("🚀 Ingest API iniciado en http://localhost:5000")
    print("📚 Documentación:")
    print("  GET  /api/ingest/status      - Estado actual")
    print("  POST /api/ingest/trigger     - Disparar ingestión")
    print("  GET  /api/ingest/logs        - Listar logs")
    print("  GET  /api/ingest/logs/<id>   - Detalle de log")
    app.run(debug=False, host="0.0.0.0", port=5000)

"""
ingest_logger.py — Sistema de logging para rastrear ingestiones de CSV.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Literal

# Detectar ruta base
_base_dir = Path(__file__).parent
if _base_dir.name == "code":
    _base_dir = _base_dir.parent

LOGS_DIR = _base_dir / "data" / "ingest_logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


class IngestLogger:
    """Logger para operaciones de ingesta de CSV."""
    
    def __init__(self):
        self.logs = []
        self.current_session = None
    
    def start_session(self) -> str:
        """Inicia una nueva sesión de ingesta. Retorna session_id."""
        self.current_session = {
            "session_id": datetime.now().isoformat(),
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "status": "running",
            "files_processed": 0,
            "files_success": 0,
            "files_error": 0,
            "events": []
        }
        return self.current_session["session_id"]
    
    def log_event(self, 
                  filename: str, 
                  event_type: Literal["detect", "move", "load", "error"],
                  message: str,
                  metadata: dict = None):
        """Registra un evento en la sesión actual."""
        if self.current_session is None:
            self.start_session()
        
        event = {
            "timestamp": datetime.now().isoformat(),
            "filename": filename,
            "type": event_type,
            "message": message,
            "metadata": metadata or {}
        }
        
        self.current_session["events"].append(event)
        
        # Actualizar contadores
        if event_type == "error":
            self.current_session["files_error"] += 1
        elif event_type == "load":
            self.current_session["files_success"] += 1
        
        self.current_session["files_processed"] = (
            self.current_session["files_success"] + self.current_session["files_error"]
        )
    
    def end_session(self, status: Literal["success", "error", "partial"] = "success"):
        """Finaliza la sesión actual y la guarda a disco."""
        if self.current_session is None:
            return
        
        self.current_session["status"] = status
        self.current_session["end_time"] = datetime.now().isoformat()
        
        # Guardar a archivo
        session_id = self.current_session["session_id"].replace(":", "-").replace(".", "-")
        log_file = LOGS_DIR / f"ingest_{session_id}.json"
        
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(self.current_session, f, indent=2, ensure_ascii=False)
        
        print(f"\n[LOG] Log guardado: {log_file}")
        return self.current_session
    
    def get_summary(self) -> dict:
        """Retorna un resumen de la sesión actual."""
        if self.current_session is None:
            return {}
        
        return {
            "session_id": self.current_session["session_id"],
            "files_processed": self.current_session["files_processed"],
            "files_success": self.current_session["files_success"],
            "files_error": self.current_session["files_error"],
            "status": self.current_session["status"]
        }


# Instancia global
logger = IngestLogger()


def get_latest_log() -> dict | None:
    """Retorna el log más reciente."""
    logs = sorted(LOGS_DIR.glob("ingest_*.json"), reverse=True)
    if not logs:
        return None
    
    with open(logs[0], 'r', encoding='utf-8') as f:
        return json.load(f)


def list_all_logs() -> list[dict]:
    """Lista todos los logs disponibles."""
    logs = []
    for log_file in sorted(LOGS_DIR.glob("ingest_*.json"), reverse=True):
        with open(log_file, 'r', encoding='utf-8') as f:
            logs.append(json.load(f))
    return logs

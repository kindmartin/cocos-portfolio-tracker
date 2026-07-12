#!/usr/bin/env python3
"""
launcher.py — Portfolio Dashboard Launcher
Ejecutable simple que lanza portfolio_dashboard.py

Uso:
  python launcher.py              # Puerto 8050 (default)
  python launcher.py --port 8080  # Puerto custom
  python launcher.py --no-browser # No abre browser automático
"""

import sys
from pathlib import Path

# Agregar carpeta 'code' al PATH
code_dir = Path(__file__).parent / "code"
sys.path.insert(0, str(code_dir))

# Importar y ejecutar dashboard
from portfolio_dashboard import main

if __name__ == '__main__':
    main()

# Portfolio Manager — Gestión Automática de Portafolio de Inversión

Aplicación web local (Dash + DuckDB) para seguimiento de portafolio de inversión. Corre en tu máquina y se accede desde el navegador en `http://localhost:8050`.

---

## 🚀 Instalación (nuevo usuario)

### Requisitos previos

1. **Python 3.11+** — descargar desde [python.org/downloads](https://www.python.org/downloads/)
   - Durante la instalación: marcar ✅ **"Add Python to PATH"**
2. **Git** — descargar desde [git-scm.com](https://git-scm.com)

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/tu-usuario/portfolio-manager
cd portfolio-manager

# 2. Crear entorno virtual
python -m venv .venv

# 3. Activar entorno virtual (Windows)
.venv\Scripts\activate

# 4. Instalar dependencias
pip install -r requirements.txt

# 5. Inicializar base de datos vacía
python code/setup_db.py

# 6. Lanzar la aplicación
python QUICKSTART.py
```

Abrir el navegador en: **http://localhost:8050**

> **Nota:** La base de datos (`data/db/portfolio.duckdb`) y los CSVs con datos personales **no están incluidos** en el repositorio. Cada usuario trabaja con sus propios datos.

---

## 📦 Estructura del Proyecto

```
portfolio-manager/
├── code/
│   ├── portfolio_dashboard.py      → Aplicación web Dash (principal)
│   ├── setup_db.py                 → Crear schema DuckDB
│   ├── etl.py                      → Cargar datos desde CSV
│   ├── launcher_main.py            → Launcher avanzado (menú completo)
│   ├── launcher_dashboard.py       → Launcher solo dashboard
│   ├── ingest_monitor.py           → Monitor automático de CSVs
│   ├── ingest_api.py               → API REST para ingestión
│   ├── ingest_logger.py            → Sistema de logging
│   ├── sector_manager.py           → Gestión de sectores
│   ├── sector_api.py               → API de sectores
│   ├── sectors.json                → Mapa ticker → sector
│   └── export_db_to_csv.py         → Exportar datos a CSV
├── data/
│   ├── db/                         → Base de datos DuckDB (no incluida en repo)
│   ├── processed csv/              → CSVs procesados (no incluidos en repo)
│   ├── ingest_logs/                → Logs de ingestión
│   └── ingest_errors/              → CSVs con errores
├── csv for ingest/                 → 📥 Depositar nuevos CSVs aquí
├── ingest_ui.html                  → UI web para control de ingestión
├── QUICKSTART.py                   → Lanzador recomendado para principiantes
├── requirements.txt                → Dependencias Python
└── docs/
    └── README.md
```

---

## 🎯 Lanzadores disponibles

### 1. QUICKSTART (recomendado)
```bash
python QUICKSTART.py
```
Menú interactivo que verifica el sistema, lanza el dashboard, carga CSVs y más.

### 2. Launcher maestro (usuarios avanzados)
```bash
python code/launcher_main.py
```
Acceso completo: ETL manual, monitor automático, API REST, herramientas.

### 3. Directo
```bash
python code/portfolio_dashboard.py           # Puerto default 8050
python code/portfolio_dashboard.py --port 8080
python code/portfolio_dashboard.py --no-browser
```

---

## 📊 Dashboard — Vistas

| Vista | Descripción |
|---|---|
| **KPIs** | Valor total, ganancia, drawdown, USD/ARS |
| **Portfolio** | Asignación por sector/instrumento |
| **P&L** | Evolución de ganancias y capital neto |
| **Holdings** | Tabla detallada de posiciones |
| **Base 100** | Comparativa vs S&P 500 |
| **Sectores** | Desglose por sector |
| **Cashflow** | Evolución de depósitos/retiros |

---

## 📥 Ingestión de CSVs

### Flujo

1. Depositar CSV en `csv for ingest/`
2. Ejecutar ingestión (manual, automática o vía API)
3. El sistema auto-detecta tipo (snapshot o movimiento)
4. Mueve el archivo a la carpeta correcta automáticamente
5. Si hay error → mueve a `data/ingest_errors/` con detalle

### Opción A: Manual
```bash
python code/etl.py
python code/etl.py --snapshots      # Solo snapshots
python code/etl.py --transactions   # Solo movimientos
python code/etl.py --force          # Forzar recarga (ignora duplicados)
python code/etl.py --reset          # Borrar todo y recargar desde cero
```

### Opción B: Monitor automático
```bash
python code/ingest_monitor.py              # Monitorea cada 30s
python code/ingest_monitor.py --once       # Una sola ejecución
python code/ingest_monitor.py --interval 5 # Cada 5 segundos
```

### Opción C: API REST + UI Web
```bash
# Terminal 1
python code/ingest_api.py

# Terminal 2: abrir ingest_ui.html en el navegador
```

Endpoints:
- `GET  /api/ingest/status`  — Estado actual
- `POST /api/ingest/trigger` — Procesar
- `GET  /api/ingest/logs`    — Histórico

---

## 💾 Base de Datos

**Motor:** DuckDB  
**Ubicación:** `data/db/portfolio.duckdb`

| Tabla | Contenido |
|---|---|
| `transactions` | Movimientos (compras, ventas, depósitos) |
| `snapshots` | Valuación diaria de cada instrumento |
| `instruments` | Activos únicos con metadata |
| `fx_daily` | Tasas de cambio USD/ARS |

**Vistas:**
- `v_positions` — Posiciones actuales por fecha
- `v_portfolio_value` — Valuación total diaria
- `v_portfolio_returns` — Retorno acumulado
- `v_fx_by_date` — Tasa MEP por fecha

---

## 🛠️ Troubleshooting

**"DB no encontrada"**
```bash
python code/setup_db.py
python code/etl.py
```

**"DuckDB version mismatch"**
```bash
pip install --upgrade duckdb
```

**Puerto 8050 en uso**
```bash
python code/portfolio_dashboard.py --port 8080
```

**"No se pudo detectar tipo de CSV"**
- Verificar columnas: debe tener `instrumento` o `fechaejecucion`
- Encoding: debe ser UTF-8
- Ver detalle en `data/ingest_errors/`

---

## 📋 Logging

Cada ingestión genera un log en `data/ingest_logs/ingest_TIMESTAMP.json` con:
- Archivos procesados / errores
- Tipo detectado por archivo
- Timestamps de inicio y fin

---

## 🔮 Próximas mejoras

- [ ] Botón "Procesar CSV" en el dashboard
- [ ] Notificaciones por email al completar
- [ ] Validación de CSV antes de mover
- [ ] Soporte para archivos ZIP
- [ ] Ejecutable `.exe` standalone (PyInstaller)

---

**Versión:** 2.0  
**Última actualización:** 2026-07-11

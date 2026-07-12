# Cocos Portfolio Tracker

Dashboard local de gestión de portafolio para cuentas de COCOS Capital. Corre completamente en tu máquina — sin nube, sin servicios externos.

Construido con Python, Dash, Plotly y DuckDB.

![KPIs Dashboard](docs/screenshots/01_kpis.png)

---

## Por qué existe este proyecto

COCOS Capital ofrece una buena plataforma de brokerage, pero sus reportes integrados son limitados para analizar el portafolio a lo largo del tiempo. Las alternativas obvias — trackers de terceros, integraciones con el broker, o pulls automáticos de datos — requieren una API key o acceso OAuth a tu cuenta. Eso significa darle a un servicio externo acceso de lectura (o más) a tus posiciones, transacciones y saldo.

Este proyecto toma un camino diferente: **exportás los CSVs manualmente desde COCOS y los tirás en una carpeta**. La app lee esos archivos, los carga en una base de datos DuckDB local, y sirve un dashboard completo de análisis en tu propia máquina. Sin API keys. Sin conexiones externas. Sin servicios que puedan ser comprometidos o cambiar sus términos.

Tus datos nunca salen de tu computadora.

---

## Capturas de pantalla

### KPIs / Evolución del Portfolio
![KPIs y evolución del portfolio](docs/screenshots/01_kpis.png)

### Composición del Portfolio
![Gráfico de composición y tabla de holdings](docs/screenshots/02_portfolio.png)

### P&L por Instrumento
![Ganancia/pérdida porcentual por instrumento](docs/screenshots/03_pnl.png)

### Desglose por Sector
![Gráfico de asignación por sector](docs/screenshots/07_sectores.png)

---

## Instalación

### Requisitos previos

- Python 3.11 o superior — descargar desde [python.org/downloads](https://www.python.org/downloads/)
  - Durante la instalación: marcar ✅ **"Add Python to PATH"**
- Git — descargar desde [git-scm.com](https://git-scm.com)

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/kindmartin/cocos-portfolio-tracker
cd cocos-portfolio-tracker

# 2. Crear entorno virtual
python -m venv .venv

# 3. Activar (Windows)
.venv\Scripts\activate

# 4. Instalar dependencias
pip install -r requirements.txt

# 5. Inicializar base de datos vacía
python code/setup_db.py

# 6. Lanzar
python QUICKSTART.py
```

Abrir el navegador en **http://localhost:8050**

> La base de datos y los CSVs con datos personales **no están incluidos** en el repositorio. Cada usuario trabaja con sus propios datos.

---

## Cómo cargar tus datos

### Paso 1 — Descargar los CSVs desde COCOS

La app trabaja con dos tipos de archivos que exportás manualmente desde [cocos.capital](https://cocos.capital):

#### Reporte de posiciones (snapshot)
Muestra el valor de cada instrumento en una fecha determinada.

1. Iniciá sesión en **[app.cocos.capital/capital-portfolio](https://app.cocos.capital/capital-portfolio)**
2. En el panel de Portfolio, hacer click en el botón **"Descargar Portfolio"** (arriba a la derecha)
3. El archivo se descarga con el nombre: `portfolio_report_YYYYMMDD.csv`

![Descargar Portfolio desde COCOS](docs/screenshots/cocos_portfolio_download.jpg)

> Hacé esto periódicamente (semanal o mensualmente) para tener historial de evolución del portfolio.

#### Movimientos de cuenta (transacciones)
Compras, ventas, depósitos, retiros y otros movimientos.

1. Iniciá sesión y ir a **[app.cocos.capital/movements](https://app.cocos.capital/movements)**
2. Seleccioná la moneda (ARS, US$, etc.) y filtrá el período si querés
3. Hacer click en **"Descargar movimientos"** (arriba a la derecha)
4. El archivo se descarga con el nombre: `movimientos_cuenta YYYY.csv`

![Descargar Movimientos desde COCOS](docs/screenshots/cocos_movements_download.jpg)

---

### Paso 2 — Copiar los archivos a la carpeta de ingestión

Copiá los archivos descargados a:

```
cocos-portfolio-tracker/
└── csv for ingest/          ← acá van los CSVs
```

La app acepta ambos tipos en la misma carpeta al mismo tiempo — detecta automáticamente de qué tipo es cada uno por sus columnas.

---

### Paso 3 — Procesar

**Opción A — Desde el dashboard:**
Click en el botón **"Actualizar datos desde csv for ingest/"**

**Opción B — Desde la terminal:**
```bash
python code/etl.py
```

**Opciones útiles:**
```bash
python code/etl.py --snapshots      # Solo cargar snapshots
python code/etl.py --transactions   # Solo cargar movimientos
python code/etl.py --force          # Forzar recarga aunque ya existan
python code/etl.py --reset          # Borrar todo y recargar desde cero
```

Después del procesamiento, los archivos se mueven automáticamente a `data/processed csv/`. Si hay un error, el archivo queda en `data/ingest_errors/` con un archivo `.error` que explica qué falló.

---

## Estructura del proyecto

```
cocos-portfolio-tracker/
├── code/
│   ├── portfolio_dashboard.py   # App web principal (Dash)
│   ├── setup_db.py              # Inicializar schema DuckDB
│   ├── etl.py                   # Cargar CSVs a la base de datos
│   ├── ingest_monitor.py        # Monitoreo automático de csv for ingest/
│   ├── ingest_api.py            # API REST para control de ingestión
│   ├── sector_manager.py        # Lógica de asignación de sectores
│   └── launcher_main.py         # Menú de lanzador avanzado
├── csv for ingest/              # Depositar nuevos CSVs aquí
├── data/
│   └── db/                      # Base de datos DuckDB (no incluida en repo)
├── QUICKSTART.py                # Lanzador recomendado para nuevos usuarios
├── requirements.txt
└── docs/
    └── README.md
```

---

## Lanzadores disponibles

| Comando | Descripción |
|---|---|
| `python QUICKSTART.py` | Menú interactivo — recomendado para nuevos usuarios |
| `python code/launcher_main.py` | Menú completo con ETL, monitor, API, herramientas |
| `python code/portfolio_dashboard.py` | Lanzar dashboard directo en puerto 8050 |
| `python code/portfolio_dashboard.py --port 8080` | Puerto personalizado |

---

## Troubleshooting

**"DB no encontrada"**
```bash
python code/setup_db.py
python code/etl.py
```

**Puerto 8050 en uso**
```bash
python code/portfolio_dashboard.py --port 8080
```

**"DuckDB version mismatch"**
```bash
pip install --upgrade duckdb
```

**"No se pudo detectar tipo de CSV"**
- Verificar que el archivo tenga las columnas estándar de COCOS (`instrumento` o `fechaejecucion`)
- El encoding debe ser UTF-8
- Ver detalle del error en `data/ingest_errors/`

---

## Stack tecnológico

| Capa | Librería |
|---|---|
| Interfaz web | [Dash](https://dash.plotly.com) 2.18+ |
| Gráficos | [Plotly](https://plotly.com/python) 6.0+ |
| Base de datos | [DuckDB](https://duckdb.org) 1.0+ |
| Procesamiento de datos | [pandas](https://pandas.pydata.org) 2.2+ |
| API de ingestión | [Flask](https://flask.palletsprojects.com) 3.0+ |

---

## Licencia

MIT

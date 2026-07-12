#!/usr/bin/env python3
"""
portfolio_dashboard.py — Dashboard web del portfolio. Lee directo de DuckDB.

Uso:
  python portfolio_dashboard.py              → http://localhost:8050
  python portfolio_dashboard.py --port 8080
  python portfolio_dashboard.py --no-browser  (no abre el browser automáticamente)

Tableau 2026.2 (conexión directa sin .hyper):
  Tableau → Conectar → A un archivo → DuckDB → seleccionar db/portfolio.duckdb
  Todas las vistas (v_positions, v_portfolio_returns, v_allocation, etc.) 
  están disponibles directamente como tablas en Tableau.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from dash import Dash, Input, Output, State, dash_table, dcc, html, ALL, no_update
from dash.exceptions import PreventUpdate

# Auto-inicializar estructura de carpetas
try:
    from init_portfolio import check_and_create_structure
    check_and_create_structure()
except ImportError:
    pass  # No es crítico si no está disponible (ej: dentro del .exe)

# ─── CONFIG ───────────────────────────────────────────────────────────────────

# Detectar ruta base (funciona en .exe y script)
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    # En desarrollo: carpeta padre si estamos en 'code/', else actual
    BASE_DIR = Path(__file__).parent
    if BASE_DIR.name == "code":
        BASE_DIR = BASE_DIR.parent

DB_PATH = BASE_DIR / "data" / "db" / "portfolio.duckdb"
BACKUP_DIR = BASE_DIR / "data" / "db" / "backups"
INGEST_DIR = BASE_DIR / "csv for ingest"
SNAPSHOTS_CSV_DIR = BASE_DIR / "data" / "processed csv" / "snapshots"
TRANSACTIONS_CSV_DIR = BASE_DIR / "data" / "processed csv" / "transactions"


def _load_sector_map() -> dict:
    """Carga sectores combinando sectors.json (manual) + sectors_cache.json (yfinance)."""
    try:
        from sector_resolver import get_sector_map
        return get_sector_map()
    except ImportError:
        pass
    # fallback: solo sectors.json
    _code_dir = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).parent
    path = _code_dir / "sectors.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            return {k: v for k, v in data.items() if not k.startswith('_')}
        except Exception:
            pass
    return {}


SECTOR_MAP = _load_sector_map()

# ─── THEME ────────────────────────────────────────────────────────────────────

BG       = '#0f1117'
CARD_BG  = '#1a1d2e'
PLOT_BG  = '#161929'
GRID     = '#252a45'
ACCENT   = '#4a9eff'
GREEN    = '#00d4aa'
RED      = '#ff6b6b'
YELLOW   = '#ffd166'
TEXT     = '#e0e0e0'
SUBTEXT  = '#8892b0'

PLOT_LAYOUT = dict(
    paper_bgcolor=CARD_BG,
    plot_bgcolor=PLOT_BG,
    font=dict(color=TEXT, family='Inter, Segoe UI, Arial, sans-serif', size=12),
    xaxis=dict(gridcolor=GRID, zeroline=False, showline=False),
    yaxis=dict(gridcolor=GRID, zeroline=False, showline=False),
    margin=dict(l=55, r=20, t=45, b=40),
    legend=dict(bgcolor='rgba(0,0,0,0)', font=dict(color=TEXT, size=11)),
)

TAB_STYLE = {
    'backgroundColor': CARD_BG,
    'color': SUBTEXT,
    'borderBottom': f'2px solid {GRID}',
    'padding': '10px 20px',
    'fontWeight': '500',
}
TAB_SELECTED = {
    **TAB_STYLE,
    'color': ACCENT,
    'borderBottom': f'2px solid {ACCENT}',
    'backgroundColor': CARD_BG,
}


# ─── DATA HELPERS ─────────────────────────────────────────────────────────────

def db_query(sql: str) -> pd.DataFrame:
    with duckdb.connect(str(DB_PATH), read_only=False) as conn:
        return conn.execute(sql).df()


def get_db_status() -> str:
    """Verifica el estado de la DB: 'no_db' | 'empty' | 'ready'."""
    if not DB_PATH.exists():
        return 'no_db'
    try:
        with duckdb.connect(str(DB_PATH), read_only=False) as conn:
            n = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            return 'ready' if n > 0 else 'empty'
    except Exception:
        return 'no_db'


def load_returns() -> pd.DataFrame:
    try:
        return db_query("""
            SELECT snapshot_date AS fecha, total_usd, total_ars,
                   ret_sem_usd_pct, drawdown_usd_pct, usd_ars_rate
            FROM v_portfolio_returns
            ORDER BY snapshot_date
        """)
    except Exception:
        return pd.DataFrame(columns=['fecha', 'total_usd', 'total_ars', 'ret_sem_usd_pct', 'drawdown_usd_pct', 'usd_ars_rate'])


def load_positions_latest() -> pd.DataFrame:
    try:
        return db_query("""
            WITH last_snap AS (SELECT MAX(snapshot_date) AS fecha FROM v_positions),
            totals AS (
                SELECT SUM(total_usd) AS total
                FROM v_positions p CROSS JOIN last_snap ls
                WHERE p.snapshot_date = ls.fecha
            )
            SELECT
                p.snapshot_date AS fecha, p.ticker, p.nombre, p.tipo,
                p.cantidad,
                ROUND(p.precio,    2) AS precio_ars,
                ROUND(p.total_ars, 0) AS total_ars,
                ROUND(p.total_usd, 2) AS total_usd,
                ROUND(p.usd_ars,   2) AS usd_ars,
                ROUND(p.total_usd / NULLIF(t.total, 0) * 100, 2) AS peso_pct
            FROM v_positions p CROSS JOIN last_snap ls CROSS JOIN totals t
            WHERE p.snapshot_date = ls.fecha
            ORDER BY p.total_usd DESC
        """)
    except Exception:
        return pd.DataFrame(columns=['fecha', 'ticker', 'nombre', 'tipo', 'cantidad', 'precio_ars', 'total_ars', 'total_usd', 'usd_ars', 'peso_pct'])


def load_holdings_evolution() -> pd.DataFrame:
    try:
        return db_query("""
            WITH totals AS (
                SELECT snapshot_date, SUM(total_usd) AS total_portfolio
                FROM v_positions
                GROUP BY snapshot_date
            ),
            positions_labeled AS (
                SELECT
                    p.snapshot_date AS fecha,
                    CASE
                        WHEN p.ticker = 'ARS' THEN 'CASH_ARS'
                        WHEN p.ticker IN ('USD', 'EXT') THEN 'CASH_USD'
                        ELSE p.ticker
                    END AS ticker,
                    CASE
                        WHEN p.ticker = 'ARS' THEN 'CASH_ARS'
                        WHEN p.ticker IN ('USD', 'EXT') THEN 'CASH_USD'
                        ELSE p.nombre
                    END AS nombre,
                    CASE
                        WHEN p.ticker IN ('ARS','USD','EXT') THEN 'CASH'
                        ELSE p.tipo
                    END AS tipo,
                    ROUND(p.total_usd, 2) AS total_usd
                FROM v_positions p
            ),
            positions_grouped AS (
                SELECT
                    fecha,
                    ticker,
                    MAX(nombre) AS nombre,
                    MAX(tipo) AS tipo,
                    ROUND(SUM(total_usd), 2) AS total_usd
                FROM positions_labeled
                GROUP BY fecha, ticker
            )
            SELECT
                p.fecha, p.ticker, p.nombre, p.tipo,
                p.total_usd,
                ROUND(p.total_usd / NULLIF(t.total_portfolio, 0) * 100, 2) AS pct_portfolio
            FROM positions_grouped p
            JOIN totals t ON t.snapshot_date = p.fecha
            ORDER BY p.fecha, p.total_usd DESC
        """)
    except Exception:
        return pd.DataFrame(columns=['fecha', 'ticker', 'nombre', 'tipo', 'total_usd', 'pct_portfolio'])


def load_holdings_normalized(base_date: str | None = None) -> pd.DataFrame:
    # Filtro de fecha base: si se especifica, solo normalizar desde esa fecha en adelante
    date_filter = f"AND snapshot_date >= '{base_date}'" if base_date else ""
    try:
        return db_query(f"""
            WITH base AS (
                SELECT snapshot_date AS fecha, ticker, nombre, tipo, cantidad,
                       CASE WHEN cantidad > 0 THEN ROUND(total_usd / cantidad, 4) END AS precio_usd,
                       ROUND(total_usd, 2) AS total_usd
                FROM v_positions WHERE tipo != 'CASH' {date_filter}
            ),
            prices AS (
                SELECT ticker, fecha, precio_usd, cantidad,
                    COALESCE(precio_usd / NULLIF(LAG(precio_usd) OVER (PARTITION BY ticker ORDER BY fecha), 0), 1.0) AS price_ratio,
                    COALESCE(cantidad   / NULLIF(LAG(cantidad)   OVER (PARTITION BY ticker ORDER BY fecha), 0), 1.0) AS qty_ratio
                FROM base WHERE precio_usd IS NOT NULL AND precio_usd > 0
            ),
            split_adj AS (
                SELECT ticker, fecha,
                    EXP(SUM(LN(
                        CASE WHEN price_ratio < 0.5
                             AND (qty_ratio BETWEEN 0.8 AND 1.2 OR price_ratio * qty_ratio BETWEEN 0.7 AND 1.3)
                             THEN price_ratio ELSE 1.0 END
                    )) OVER (PARTITION BY ticker ORDER BY fecha)) AS cum_split_factor
                FROM prices
            ),
            adj AS (
                SELECT b.*, b.precio_usd / NULLIF(s.cum_split_factor, 0) AS precio_adj
                FROM base b JOIN split_adj s ON b.ticker = s.ticker AND b.fecha = s.fecha
            ),
            first_val AS (
                SELECT ticker, fecha AS first_fecha, precio_adj AS first_precio
                FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fecha) AS rn FROM adj
                      WHERE precio_adj IS NOT NULL AND precio_adj > 0) t WHERE rn = 1
            )
            SELECT a.fecha, a.ticker, a.nombre, a.tipo, a.total_usd,
                   ROUND(a.precio_adj / NULLIF(f.first_precio, 0) * 100, 2) AS indice_100
            FROM adj a JOIN first_val f ON a.ticker = f.ticker
            ORDER BY a.fecha, a.ticker
        """)
    except Exception:
        return pd.DataFrame(columns=['fecha', 'ticker', 'nombre', 'tipo', 'total_usd', 'indice_100'])


def load_performance_vs_spy(base_date: str | None = None) -> pd.DataFrame:
    """Performance de cada instrumento relativo a SPY (SPY=100). Incluye índice MSO (portfolio-weighted)."""
    date_filter = f"AND snapshot_date >= '{base_date}'" if base_date else ""
    try:
        return db_query(f"""
            WITH base AS (
                SELECT snapshot_date AS fecha, ticker, nombre, tipo, cantidad,
                       CASE WHEN cantidad > 0 THEN ROUND(total_usd / cantidad, 4) END AS precio_usd,
                       ROUND(total_usd, 2) AS total_usd
                FROM v_positions WHERE tipo != 'CASH' {date_filter}
            ),
            prices AS (
                SELECT ticker, fecha, precio_usd, cantidad,
                    COALESCE(precio_usd / NULLIF(LAG(precio_usd) OVER (PARTITION BY ticker ORDER BY fecha), 0), 1.0) AS price_ratio,
                    COALESCE(cantidad   / NULLIF(LAG(cantidad)   OVER (PARTITION BY ticker ORDER BY fecha), 0), 1.0) AS qty_ratio
                FROM base WHERE precio_usd IS NOT NULL AND precio_usd > 0
            ),
            split_adj AS (
                SELECT ticker, fecha,
                    EXP(SUM(LN(
                        CASE WHEN price_ratio < 0.5
                             AND (qty_ratio BETWEEN 0.8 AND 1.2 OR price_ratio * qty_ratio BETWEEN 0.7 AND 1.3)
                             THEN price_ratio ELSE 1.0 END
                    )) OVER (PARTITION BY ticker ORDER BY fecha)) AS cum_split_factor
                FROM prices
            ),
            adj AS (
                SELECT b.*, b.precio_usd / NULLIF(s.cum_split_factor, 0) AS precio_adj
                FROM base b JOIN split_adj s ON b.ticker = s.ticker AND b.fecha = s.fecha
            ),
            first_val AS (
                SELECT ticker, fecha AS first_fecha, precio_adj AS first_precio
                FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY fecha) AS rn FROM adj
                      WHERE precio_adj IS NOT NULL AND precio_adj > 0) t WHERE rn = 1
            ),
            indices AS (
                SELECT a.fecha, a.ticker, a.nombre, a.tipo, a.total_usd,
                       ROUND(a.precio_adj / NULLIF(f.first_precio, 0) * 100, 2) AS indice_100
                FROM adj a JOIN first_val f ON a.ticker = f.ticker
            ),
            spy_idx AS (
                SELECT fecha, indice_100 AS spy_index FROM indices WHERE ticker = 'SPY'
            ),
            perf_vs_spy_calc AS (
                SELECT i.fecha, i.ticker, i.nombre, i.tipo, i.total_usd,
                       i.indice_100,
                       COALESCE(s.spy_index, 100) AS spy_index,
                       CASE 
                           WHEN i.ticker = 'SPY' THEN 100.0
                           WHEN s.spy_index IS NULL OR s.spy_index = 0 THEN 100.0
                           ELSE ROUND(i.indice_100 / s.spy_index * 100, 2)
                       END AS perf_vs_spy,
                       SUM(i.total_usd) OVER (PARTITION BY i.fecha) AS total_portfolio_usd,
                       ROW_NUMBER() OVER (PARTITION BY i.fecha ORDER BY i.ticker) AS rn
                FROM indices i
                LEFT JOIN spy_idx s ON i.fecha = s.fecha
            ),
            mso_calc AS (
                SELECT fecha, ticker, nombre, tipo, total_usd, indice_100, spy_index, perf_vs_spy,
                       ROUND(SUM(indice_100 * total_usd) OVER (PARTITION BY fecha) / 
                             NULLIF(SUM(total_usd) OVER (PARTITION BY fecha), 0), 2) AS mso_index
                FROM perf_vs_spy_calc
            )
            SELECT fecha, ticker, nombre, tipo, total_usd, indice_100, spy_index, perf_vs_spy, mso_index
            FROM mso_calc
            ORDER BY fecha, ticker
        """)
    except Exception:
        return pd.DataFrame(columns=['fecha', 'ticker', 'nombre', 'tipo', 'total_usd', 'indice_100', 'spy_index', 'perf_vs_spy', 'mso_index'])


def load_cashflow_evolution() -> pd.DataFrame:
    """Réplica de build_cashflow_tables de tableau_export.py."""
    try:
        with duckdb.connect(str(DB_PATH), read_only=False) as conn:
            try:
                portfolio = conn.execute("""
                    SELECT fecha, total_usd, COALESCE(ccl, 0) AS ccl, fuente
                    FROM v_portfolio_history_full
                    WHERE total_usd IS NOT NULL ORDER BY fecha
                """).df()
            except Exception:
                portfolio = conn.execute("""
                    SELECT snapshot_date::DATE AS fecha, total_usd,
                           COALESCE(usd_ars_rate, 0) AS ccl, 'CSV' AS fuente
                    FROM v_portfolio_returns WHERE total_usd IS NOT NULL ORDER BY snapshot_date
                """).df()
            portfolio['fecha'] = pd.to_datetime(portfolio['fecha'])

            snap0 = conn.execute("""
                SELECT snapshot_date::DATE, ROUND(total_usd, 2)
                FROM v_portfolio_value ORDER BY snapshot_date LIMIT 1
            """).fetchone()
            init_fecha = pd.Timestamp(snap0[0])
            init_usd   = float(snap0[1])

            cashflows = conn.execute("""
                SELECT t.fecha_op::DATE AS fecha, t.tipo_op, t.moneda, t.total,
                       CASE WHEN t.moneda = 'USD' THEN t.total
                            ELSE t.total / NULLIF(fx.usd_ars, 0) END AS usd_equiv
                FROM transactions t
                JOIN v_fx_by_date fx ON fx.fecha = t.fecha_op::DATE
                WHERE t.tipo_op IN ('DEPOSITO','EXTRACCION')
                  AND ABS(t.total) > 0
                ORDER BY t.fecha_op
            """).df()
            cashflows['fecha'] = pd.to_datetime(cashflows['fecha'])

        # Capital neto debe reflejar solo aportes/retiros externos.
        # No insertar una fila sintética en init_fecha porque puede pisar el acumulado real
        # de flujos previos al primer snapshot visible y generar saltos artificiales.
        cum_dep, cum_ext = 0.0, 0.0
        cf_events = []
        for _, row in cashflows.iterrows():
            equiv = float(row['usd_equiv']) if pd.notna(row['usd_equiv']) else 0.0
            if equiv > 0:
                cum_dep += equiv
            else:
                cum_ext += abs(equiv)
            cf_events.append({'fecha': row['fecha'], 'dep': cum_dep, 'ext': cum_ext})

        cf_df = pd.DataFrame(cf_events).sort_values('fecha') if cf_events else pd.DataFrame(columns=['fecha', 'dep', 'ext'])

        rows = []
        for _, p in portfolio.iterrows():
            prev = cf_df[cf_df['fecha'] <= p['fecha']]
            dep  = float(prev['dep'].iloc[-1]) if not prev.empty else 0.0
            ext  = float(prev['ext'].iloc[-1]) if not prev.empty else 0.0
            val  = float(p['total_usd'])
            capital_neto = dep - ext
            # Definicion consistente con los KPIs: ganancia = valor de cartera - capital neto.
            gain = val - capital_neto
            rows.append({
                'fecha':         p['fecha'],
                'portfolio_usd': round(val, 2),
                'capital_neto':  round(capital_neto, 2),
                'ganancia_usd':  round(gain, 2),
                'ganancia_pct':  round(gain / capital_neto * 100, 2) if capital_neto > 0 else 0.0,
                'fuente':        p['fuente'],
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=['fecha', 'portfolio_usd', 'capital_neto', 'ganancia_usd', 'ganancia_pct', 'fuente'])


def compute_twr_annualized() -> tuple[float, float]:
    """Retorna (retorno_total_pct, retorno_anualizado_pct) sobre capital neto."""
    try:
        cf = load_cashflow_evolution()
        if cf.empty:
            return 0.0, 0.0
        first  = cf.iloc[0]
        last   = cf.iloc[-1]
        total_return = last['ganancia_pct']
        # Calcular años transcurridos
        n_days = (pd.Timestamp(last['fecha']) - pd.Timestamp(first['fecha'])).days
        if n_days <= 0:
            return total_return, 0.0
        annualized = ((1 + total_return / 100) ** (365.25 / n_days) - 1) * 100
        return round(total_return, 2), round(annualized, 2)
    except Exception:
        return 0.0, 0.0


def load_pnl_by_ticker() -> pd.DataFrame:
    """P&L por ticker: costo invertido (USD equiv al momento de compra) vs valor actual."""
    try:
        return db_query("""
            WITH latest_pos AS (
                SELECT p.ticker, p.nombre, p.tipo,
                       ROUND(p.total_usd, 2) AS valor_usd,
                       p.cantidad, ROUND(p.usd_ars, 1) AS usd_ars
                FROM v_positions p
                WHERE p.snapshot_date = (SELECT MAX(snapshot_date) FROM v_positions)
                  AND p.tipo NOT IN ('CASH', 'MEP')
            ),
            -- Costo total invertido por ticker, convertido a USD al tipo de la operación
            costo_usd AS (
                SELECT t.ticker,
                       ROUND(SUM(
                           CASE WHEN t.moneda IN ('USD','EXT') THEN ABS(t.total)
                                WHEN t.moneda = 'ARS' AND fx.usd_ars > 0 THEN ABS(t.total) / fx.usd_ars
                                ELSE 0 END
                       ), 2) AS costo_usd_total
                FROM transactions t
                JOIN v_fx_by_date fx ON fx.fecha = t.fecha_op::DATE
                WHERE t.tipo_op = 'COMPRA'
                  AND t.ticker IS NOT NULL
                  AND t.ticker NOT IN ('ARS','USD','EXT')
                GROUP BY t.ticker
            )
            SELECT
                p.ticker,
                p.nombre,
                p.tipo,
                COALESCE(c.costo_usd_total, 0)                                          AS costo_usd,
                p.valor_usd,
                ROUND(p.valor_usd - COALESCE(c.costo_usd_total, 0), 2)                 AS pnl_usd,
                CASE WHEN COALESCE(c.costo_usd_total, 0) > 0
                     THEN ROUND((p.valor_usd - c.costo_usd_total) / c.costo_usd_total * 100, 1)
                     ELSE NULL END                                                       AS pnl_pct
            FROM latest_pos p
            LEFT JOIN costo_usd c ON p.ticker = c.ticker
            ORDER BY p.valor_usd DESC
        """)
    except Exception:
        return pd.DataFrame(columns=['ticker', 'nombre', 'tipo', 'costo_usd', 'valor_usd', 'pnl_usd', 'pnl_pct'])


def load_cashflow_events() -> pd.DataFrame:
    """Eventos individuales de entrada/salida de capital (para bar chart y tabla)."""
    try:
        with duckdb.connect(str(DB_PATH), read_only=False) as conn:
            events_df = conn.execute("""
                SELECT
                    t.fecha_op::DATE  AS fecha,
                    t.tipo_op,
                    TRIM(t.tipo_op_raw)  AS descripcion,
                    t.moneda,
                    ROUND(CASE WHEN t.moneda = 'USD' THEN t.total
                               ELSE t.total / NULLIF(fx.usd_ars, 0) END, 2) AS usd_equiv
                FROM transactions t
                JOIN v_fx_by_date fx ON fx.fecha = t.fecha_op::DATE
                WHERE t.tipo_op IN ('DEPOSITO', 'EXTRACCION')
                  AND ABS(t.total) > 0
                ORDER BY t.fecha_op
            """).df()
        events_df['fecha'] = pd.to_datetime(events_df['fecha'])
        events_df['descripcion'] = events_df['descripcion'].str.title()
        return events_df
    except Exception:
        return pd.DataFrame(columns=['fecha', 'tipo_op', 'descripcion', 'moneda', 'usd_equiv'])


def load_cashflow_summary() -> pd.DataFrame:
    """Totales agrupados por descripcion y tipo para la tabla resumen."""
    df = load_cashflow_events()
    summary = (
        df.groupby(['descripcion', 'tipo_op'], as_index=False)['usd_equiv']
        .sum()
        .rename(columns={'descripcion': 'Descripción', 'tipo_op': 'Tipo', 'usd_equiv': 'Importe USD'})
        .sort_values('Importe USD', ascending=False)
        .reset_index(drop=True)
    )
    summary['Importe USD'] = summary['Importe USD'].round(2)
    return summary


def load_positions_evolution_with_sectors() -> pd.DataFrame:
    """Carga evolución de posiciones con información de sectores asignados."""
    try:
        return db_query("""
            SELECT 
                vp.snapshot_date AS fecha,
                vp.ticker,
                vp.nombre,
                vp.total_usd,
                COALESCE(sl.sector_name, 'Sin sector') AS sector_name,
                COALESCE(sl.color, '#808080') AS color
            FROM v_positions vp
            LEFT JOIN instrument_sectors isec ON vp.ticker = isec.ticker
            LEFT JOIN sector_list sl ON isec.sector_id = sl.sector_id
            ORDER BY vp.snapshot_date, vp.ticker
        """)
    except Exception as e:
        print(f"[load_positions_evolution_with_sectors] ERROR: {e}")
        return pd.DataFrame()


# ─── APP LAYOUT ───────────────────────────────────────────────────────────────

app = Dash(
    __name__,
    title="Portfolio Dashboard",
    suppress_callback_exceptions=True,
)

# Registrar endpoints de sectores
try:
    from sector_api import sector_bp
    app.server.register_blueprint(sector_bp)
except Exception as e:
    print(f"[WARN] No se pudo registrar endpoint de sectores: {e}")

def _kpi(label: str, value: str, note: str = '', up: bool = True) -> html.Div:
    note_color = GREEN if up else RED
    return html.Div([
        html.P(label, style={'color': SUBTEXT, 'fontSize': '11px', 'margin': '0 0 6px 0',
                              'textTransform': 'uppercase', 'letterSpacing': '1.2px'}),
        html.H3(value, style={'color': TEXT, 'margin': '0', 'fontSize': '22px', 'fontWeight': '700',
                               'lineHeight': '1'}),
        html.P(note, style={'color': note_color, 'fontSize': '12px', 'margin': '6px 0 0 0'}) if note else None,
    ], style={
        'background': CARD_BG, 'padding': '18px 22px', 'borderRadius': '10px',
        'flex': '1', 'minWidth': '140px', 'border': f'1px solid {GRID}',
    })


def _check_has_data() -> bool:
    """Verifica si hay datos en la BD (snapshots o transacciones)."""
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=False)
        snap_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        trans_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        conn.close()
        return (snap_count + trans_count) > 0
    except Exception:
        return False


app.layout = html.Div([

    dcc.Interval(id='iv', interval=5 * 60 * 1000, n_intervals=0),
    dcc.Store(id='etl-done', data=0),  # se incrementa tras cada ETL exitoso
    dcc.Store(id='onboarding-dismissed', data=False),  # guarda si usuario cerró onboarding
    dcc.Store(id='sectors-refresh', data=0),
    dcc.ConfirmDialog(
        id='confirm-clear-data',
        message='Esto va a borrar TODOS los datos de la base (sin borrar CSV) y también los logs de ingest. ¿Confirmás?'
    ),
    dcc.ConfirmDialog(
        id='confirm-restore-backup',
        message='Esto reemplaza la data actual por el backup seleccionado (sin borrar CSV). ¿Confirmás restaurar?'
    ),

    # Onboarding Modal (aparece solo si no hay datos)
    html.Div(
        id='onboarding-overlay',
        style={
            'display': 'flex',
            'position': 'fixed',
            'top': 0,
            'left': 0,
            'width': '100%',
            'height': '100%',
            'background': 'rgba(0, 0, 0, 0.85)',
            'zIndex': 10000,
            'justifyContent': 'center',
            'alignItems': 'center',
            'fontFamily': 'inherit',
        },
        children=[
            html.Div([
                # Close button
                html.Button(
                    '✕',
                    id='btn-onboarding-close',
                    style={
                        'position': 'absolute',
                        'top': '20px',
                        'right': '20px',
                        'background': 'transparent',
                        'border': 'none',
                        'color': SUBTEXT,
                        'fontSize': '28px',
                        'cursor': 'pointer',
                        'padding': '0',
                        'width': '40px',
                        'height': '40px',
                    },
                ),
                
                # Title
                html.H1(
                    '📊 Bienvenido a Portfolio Tracker',
                    style={
                        'color': ACCENT,
                        'margin': '0 0 10px 0',
                        'fontSize': '28px',
                        'fontWeight': '700',
                        'textAlign': 'center',
                    },
                ),
                html.P(
                    'Analiza tu portfolio de COCOS en tiempo real',
                    style={
                        'color': SUBTEXT,
                        'margin': '0 0 30px 0',
                        'fontSize': '16px',
                        'textAlign': 'center',
                    },
                ),
                
                # Content
                html.Div([
                    # Step 1
                    html.Div([
                        html.Div('1️⃣', style={'fontSize': '32px', 'marginRight': '15px'}),
                        html.Div([
                            html.H3('Descargar datos de COCOS', style={
                                'margin': '0 0 8px 0', 'color': TEXT, 'fontSize': '16px', 'fontWeight': '600'
                            }),
                            html.P([
                                html.B('Snapshots: '),
                                'COCOS → Reportes → "Cartera Actual" → Exportar CSV'
                            ], style={'margin': '0', 'color': SUBTEXT, 'fontSize': '14px'}),
                            html.P([
                                html.B('Movimientos: '),
                                'Recibirás por mail (movimientos_cuenta.csv)'
                            ], style={'margin': '5px 0 0 0', 'color': SUBTEXT, 'fontSize': '14px'}),
                        ], style={'flex': '1'}),
                    ], style={'display': 'flex', 'marginBottom': '20px', 'alignItems': 'flex-start'}),
                    
                    # Step 2
                    html.Div([
                        html.Div('2️⃣', style={'fontSize': '32px', 'marginRight': '15px'}),
                        html.Div([
                            html.H3('Guardar en carpeta', style={
                                'margin': '0 0 8px 0', 'color': TEXT, 'fontSize': '16px', 'fontWeight': '600'
                            }),
                            html.P([
                                html.B('TODOS los archivos → '),
                                html.Code('csv for ingest/', style={'background': PLOT_BG, 'padding': '2px 6px', 'borderRadius': '4px'}),
                            ], style={'margin': '0', 'color': SUBTEXT, 'fontSize': '14px'}),
                            html.P([
                                '✓ Snapshots (portfolio_report_*.csv)'
                            ], style={'margin': '8px 0 0 0', 'color': '#00d4aa', 'fontSize': '13px'}),
                            html.P([
                                '✓ Movimientos (movimientos_*.csv)'
                            ], style={'margin': '4px 0 0 0', 'color': '#00d4aa', 'fontSize': '13px'}),
                            html.P([
                                '⚠️ No importa el nombre - el sistema auto-detecta qué es cada uno'
                            ], style={'margin': '8px 0 0 0', 'color': '#ff9500', 'fontSize': '13px', 'fontStyle': 'italic'}),
                        ], style={'flex': '1'}),
                    ], style={'display': 'flex', 'marginBottom': '20px', 'alignItems': 'flex-start'}),
                    
                    # Step 3
                    html.Div([
                        html.Div('3️⃣', style={'fontSize': '32px', 'marginRight': '15px'}),
                        html.Div([
                            html.H3('Cargar todo', style={
                                'margin': '0 0 8px 0', 'color': TEXT, 'fontSize': '16px', 'fontWeight': '600'
                            }),
                            html.P(
                                'Click "[ACTUALIZAR] Datos desde csv for ingest/" → El sistema:',
                                style={'margin': '0 0 8px 0', 'color': SUBTEXT, 'fontSize': '14px'}
                            ),
                            html.P(
                                '[OK] Lee csv for ingest/, auto-detecta tipo, deduplica, organiza y carga',
                                style={'margin': '0', 'color': '#00d4aa', 'fontSize': '13px'}
                            ),
                        ], style={'flex': '1'}),
                    ], style={'display': 'flex', 'marginBottom': '0', 'alignItems': 'flex-start'}),
                ], style={
                    'background': PLOT_BG,
                    'border': f'1px solid {GRID}',
                    'borderRadius': '10px',
                    'padding': '20px',
                    'marginBottom': '25px',
                    'maxWidth': '500px',
                }),
                
                # CTA Button
                html.Button(
                    '✓ Entendido, ir al Dashboard',
                    id='btn-onboarding-done',
                    style={
                        'background': ACCENT,
                        'color': PLOT_BG,
                        'border': 'none',
                        'borderRadius': '8px',
                        'padding': '12px 28px',
                        'fontSize': '15px',
                        'cursor': 'pointer',
                        'fontFamily': 'inherit',
                        'fontWeight': '600',
                        'width': '100%',
                        'maxWidth': '500px',
                        'transition': 'opacity 0.2s',
                    },
                    title='Cierra este onboarding y accede al dashboard'
                ),
                
                html.P(
                    '💡 Puedes acceder a esta guía en cualquier momento haciendo clic en "? Help"',
                    style={
                        'color': SUBTEXT,
                        'margin': '15px 0 0 0',
                        'fontSize': '13px',
                        'textAlign': 'center',
                    },
                ),
            ], style={
                'background': CARD_BG,
                'border': f'2px solid {ACCENT}',
                'borderRadius': '12px',
                'padding': '40px',
                'maxWidth': '600px',
                'textAlign': 'center',
                'position': 'relative',
                'boxShadow': '0 20px 60px rgba(0, 0, 0, 0.5)',
            }),
        ],
    ),

    # Header
    html.Div([
        html.Div([
            html.H1("Portfolio Dashboard",
                    style={'color': TEXT, 'margin': '0', 'fontSize': '18px', 'fontWeight': '700'}),
            html.P("Lee directo de DuckDB · Auto-refresh 5 min",
                   style={'color': SUBTEXT, 'margin': '2px 0 0 0', 'fontSize': '11px'}),
        ]),
        html.Span(id='hdr-date', style={'color': SUBTEXT, 'fontSize': '12px'}),
    ], style={
        'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center',
        'padding': '14px 28px', 'background': CARD_BG, 'borderBottom': f'1px solid {GRID}',
    }),

    # ETL bar
    html.Div([
        html.Div([
            html.Button(
                '🔄 Actualizar datos desde csv for ingest/',
                id='btn-etl',
                n_clicks=0,
                style={
                    'background': ACCENT, 'color': PLOT_BG,
                    'border': 'none', 'borderRadius': '7px',
                    'padding': '8px 20px', 'fontSize': '13px', 'cursor': 'pointer',
                    'fontFamily': 'inherit', 'fontWeight': '700', 'letterSpacing': '0.3px',
                    'transition': 'opacity 0.2s',
                },
                title='Lee csv for ingest/ → auto-detecta tipo → deduplica → organiza y carga todo a la BD'
            ),
            html.Button(
                '❓ Qué hacer?',
                id='btn-help',
                n_clicks=0,
                style={
                    'background': 'transparent', 'color': '#00d4aa',
                    'border': f'1px solid #00d4aa', 'borderRadius': '7px',
                    'padding': '6px 18px', 'fontSize': '13px', 'cursor': 'pointer',
                    'fontFamily': 'inherit', 'fontWeight': '600', 'letterSpacing': '0.3px',
                    'marginLeft': '10px',
                },
            ),
        ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px'}),
        html.Div(id='etl-status', style={
            'flex': '1', 'marginLeft': '20px', 'display': 'flex', 'flexDirection': 'column', 'gap': '6px'
        }),
        html.Button(
            '⚙ Settings',
            id='btn-goto-settings',
            n_clicks=0,
            style={
                'background': 'transparent', 'color': SUBTEXT,
                'border': f'1px solid {GRID}', 'borderRadius': '7px',
                'padding': '6px 16px', 'fontSize': '13px', 'cursor': 'pointer',
                'fontFamily': 'inherit', 'fontWeight': '500',
                'marginLeft': 'auto',
            },
        ),
    ], style={
        'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between',
        'padding': '12px 28px', 'background': PLOT_BG,
        'borderBottom': f'1px solid {GRID}',
    }),

    # Help Modal (overlay style)
    html.Div(
        id='help-modal-overlay',
        style={
            'display': 'none', 'position': 'fixed', 'top': 0, 'left': 0,
            'width': '100%', 'height': '100%', 'background': 'rgba(0,0,0,0.7)',
            'zIndex': 999, 'justifyContent': 'center', 'alignItems': 'center',
        },
        children=[
            html.Div([
                html.Div([
                    html.H2('Ayuda — Portfolio Dashboard', style={'margin': 0, 'color': ACCENT}),
                    html.Button('✕', id='btn-help-close', 
                        style={'background': 'transparent', 'border': 'none', 'color': SUBTEXT,
                                'fontSize': '20px', 'cursor': 'pointer', 'padding': '0'}),
                ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center',
                         'marginBottom': '20px', 'paddingBottom': '12px', 'borderBottom': f'1px solid {GRID}'}),
                
                html.Div([
                    html.H3('� FLUJO DE USO (Primero!)', style={'color': '#ffd166', 'marginTop': '0', 'borderBottom': f'2px solid #ffd166', 'paddingBottom': '10px'}),
                    
                    html.Div([
                        html.H4('1️⃣ Descargar de COCOS', style={'color': ACCENT, 'marginBottom': '8px'}),
                        html.P('Reportes → "Cartera Actual" → Exportar como portfolio_report_YYYYMMDD.csv', style={'margin': '0 0 12px 0', 'color': TEXT, 'fontWeight': 'bold'}),
                        html.P('Guardá en: data/processed csv/snapshots/', style={'margin': '0 0 12px 0', 'color': SUBTEXT}),
                        
                        html.P('Movimientos por mail movimientos_cuenta.csv', style={'margin': '0 0 12px 0', 'color': TEXT, 'fontWeight': 'bold'}),
                        html.P('Guardá en: data/processed csv/transactions/ ← Se renombran automáticamente!', style={'margin': '0', 'color': SUBTEXT}),
                    ], style={'background': PLOT_BG, 'padding': '12px', 'borderRadius': '6px', 'marginBottom': '12px'}),
                    
                    html.Div([
                        html.H4('2️⃣ Click "🔄 Actualizar datos" (desde csv for ingest/)', style={'color': ACCENT, 'marginBottom': '8px'}),
                        html.P('✓ Auto-detecta si es snapshot o movimiento (sin importar el nombre del archivo)', style={'margin': '0 0 6px 0', 'color': '#00d4aa'}),
                        html.P('✓ Deduplica automáticamente (no crea registros duplicados)', style={'margin': '0 0 6px 0', 'color': '#00d4aa'}),
                        html.P('✓ Organiza en carpetas correctas (snapshots/, transactions/)', style={'margin': '0 0 6px 0', 'color': '#00d4aa'}),
                        html.P('✓ Importa TODO a la BD en una sola operación', style={'margin': '0', 'color': '#00d4aa'}),
                    ], style={'background': '#0a2a1a', 'padding': '12px', 'borderRadius': '6px', 'marginBottom': '20px', 'borderLeft': f'3px solid {ACCENT}'}),
                    
                    html.Div([
                        html.P('💡 Es el único botón que necesitas. Úsalo siempre que tengas nuevos archivos en csv for ingest/', style={'margin': '0', 'color': '#ffd166', 'fontStyle': 'italic'}),
                    ], style={'background': '#2a2014', 'padding': '12px', 'borderRadius': '6px', 'borderLeft': '3px solid #ffd166'}),
                    
                    html.Hr(style={'borderColor': GRID, 'margin': '20px 0'}),
                    
                    html.H3('📊 EXPLICA DE CADA TAB', style={'color': ACCENT, 'marginTop': '0'}),
                ], style={'marginBottom': '20px'}),
                
                html.Div([
                    html.H4('KPIs / Ganancia', style={'color': ACCENT, 'marginTop': '0'}),
                    html.P('Resumen de métricas principales: Valor Total del portfolio, Ganancia acumulada en USD, Capital Neto invertido, Retorno Anualizado sobre capital neto, Drawdown desde máximo histórico, y tasa de cambio USD/ARS (MEP).'),
                    
                    html.H4('💼 Portfolio Actual', style={'color': ACCENT}),
                    html.P('Tabla con posiciones actuales: ticker, cantidad, precio unitario, valor total, % del portfolio y sector. Usa esta vista para entender qué está pesando en tu portfolio hoy.'),
                    
                    html.H4('📈 P&L por Instrumento', style={'color': ACCENT}),
                    html.P('Ganancia/Pérdida en USD y %. Calcula el costo base como SUM de todas las compras convertidas a USD al MEP de cada transacción (no al precio actual).'),
                    
                    html.H4('📊 Holdings Evolución', style={'color': ACCENT}),
                    html.P('Gráfico apilado mostrando cómo evolucionó tu portafolio en USD a lo largo del tiempo. Cada color representa un instrumento.'),
                    
                    html.H4('🎯 Perf Base 100', style={'color': ACCENT}),
                    html.P('Cada instrumento normalizado a 100 desde su primer registro. Compara performance relativa sin importar cuándo entraste en cada activo.'),
                    
                    html.H4('🔍 Perf vs SPY (#portfolio)', style={'color': ACCENT}),
                    html.P('Performance relativa a SPY (benchmark). La línea roja gruesa "#portfolio" es tu Portfolio Index ponderado.'),
                    
                    html.H4('🏭 Sectores', style={'color': ACCENT}),
                    html.P('Gráfico de torta mostrando asignación por sector: Oil & Gas ARG, Banca ARG, Tech USA, ETF USA, Bonos, etc.'),
                    
                    html.H4('💰 Cashflow', style={'color': ACCENT}),
                    html.P('Evolución temporal: ganancia acumulada, capital neto invertido, y valor total del portfolio.'),
                ], style={'maxHeight': '50vh', 'overflowY': 'auto', 'paddingRight': '10px'}),
            ], style={'padding': '24px', 'background': CARD_BG, 'borderRadius': '8px', 'color': TEXT,
                     'maxWidth': '900px', 'boxShadow': '0 10px 40px rgba(0,0,0,0.8)',
                     'maxHeight': '85vh', 'overflow': 'auto'})
        ]
    ),

    # Setup banner (visible solo si DB vacía o no existe)
    html.Div(id='setup-banner'),

    # KPI row
    html.Div(id='kpi-row', style={
        'display': 'flex', 'gap': '14px', 'padding': '20px 28px', 'flexWrap': 'wrap',
    }),

    # Tabs
    dcc.Tabs(id='tabs', value='kpis', style={'margin': '0 28px'}, children=[
        dcc.Tab(label='KPIs / Ganancia',     value='kpis',      style=TAB_STYLE, selected_style=TAB_SELECTED),
        dcc.Tab(label='Portfolio Actual',    value='portfolio', style=TAB_STYLE, selected_style=TAB_SELECTED),
        dcc.Tab(label='P&L por Instrumento', value='pnl',       style=TAB_STYLE, selected_style=TAB_SELECTED),
        dcc.Tab(label='Holdings Evolución',  value='holdings',  style=TAB_STYLE, selected_style=TAB_SELECTED),
        dcc.Tab(label='Perf Base 100',       value='base100',   style=TAB_STYLE, selected_style=TAB_SELECTED),
        dcc.Tab(label='Perf vs SPY (#portfolio)',  value='perf_vs_spy', style=TAB_STYLE, selected_style=TAB_SELECTED),
        dcc.Tab(label='Sectores',            value='sectores',  style=TAB_STYLE, selected_style=TAB_SELECTED),
        dcc.Tab(label='Cashflow',            value='cashflow',  style=TAB_STYLE, selected_style=TAB_SELECTED),
    ]),

    # Store para persistir la fecha base entre tabs base100 y perf_vs_spy
    dcc.Store(id='base-date-store', data=None),

    html.Div(id='tab-content', style={'padding': '20px 28px'}),

], style={'background': BG, 'minHeight': '100vh', 'fontFamily': 'Inter, Segoe UI, Arial, sans-serif'})


# ─── CALLBACKS ────────────────────────────────────────────────────────────────

# Callback: Controlar visibilidad del onboarding
@app.callback(
    Output('onboarding-overlay', 'style'),
    Input('onboarding-dismissed', 'data'),
    Input('etl-done', 'data'),
    prevent_initial_call=False,
)
def toggle_onboarding(dismissed, etl_done):
    """
    Muestra onboarding solo si:
    - Usuario NO ha hecho clic "Entendido" (dismissed=False)
    - Y NO hay datos en la BD
    """
    if dismissed:
        # Usuario cerró el onboarding explícitamente
        return {'display': 'none', 'position': 'fixed', 'top': 0, 'left': 0,
                'width': '100%', 'height': '100%', 'background': 'rgba(0, 0, 0, 0.85)',
                'zIndex': 10000, 'justifyContent': 'center', 'alignItems': 'center',
                'fontFamily': 'inherit'}
    
    # Verificar si hay datos
    has_data = _check_has_data()
    if has_data:
        # Hay datos, ocultar onboarding
        return {'display': 'none', 'position': 'fixed', 'top': 0, 'left': 0,
                'width': '100%', 'height': '100%', 'background': 'rgba(0, 0, 0, 0.85)',
                'zIndex': 10000, 'justifyContent': 'center', 'alignItems': 'center',
                'fontFamily': 'inherit'}
    
    # No hay datos y no fue cerrado, mostrar
    return {'display': 'flex', 'position': 'fixed', 'top': 0, 'left': 0,
            'width': '100%', 'height': '100%', 'background': 'rgba(0, 0, 0, 0.85)',
            'zIndex': 10000, 'justifyContent': 'center', 'alignItems': 'center',
            'fontFamily': 'inherit'}


# Callback: Botón "Entendido"
@app.callback(
    Output('onboarding-dismissed', 'data'),
    Input('btn-onboarding-done', 'n_clicks'),
    prevent_initial_call=True,
)
def close_onboarding_by_button(n_clicks):
    """Usuario hizo clic en 'Entendido'"""
    if n_clicks and n_clicks > 0:
        return True
    return False


# Callback: Botón X para cerrar onboarding
@app.callback(
    Output('onboarding-dismissed', 'data', allow_duplicate=True),
    Input('btn-onboarding-close', 'n_clicks'),
    prevent_initial_call=True,
)
def close_onboarding_by_x(n_clicks):
    """Usuario hizo clic en X"""
    if n_clicks and n_clicks > 0:
        return True
    return False


@app.callback(
    Output('setup-banner', 'children'),
    Input('etl-done', 'data'),
)
def render_setup_banner(_etl_done):
    """Muestra guia de setup si la DB está vacía o no existe."""
    status = get_db_status()
    if status == 'ready':
        return []
    
    if status == 'no_db':
        msg = "📢 Base de datos no encontrada. Se creará automáticamente al presionar Actualizar Datos."
        detail = "Colocá tus archivos CSV y presioná el botón."
    else:  # empty
        msg = "📢 DB creada pero sin datos. Importá tus archivos CSV para comenzar."
        detail = "Colocá los CSVs y presioná Actualizar Datos."

    return html.Div([
        html.Div([
            html.H3(msg, style={'color': YELLOW, 'margin': '0 0 12px 0', 'fontSize': '15px'}),
            html.Div([
                html.Div([
                    html.Strong("Snapshots:", style={'color': ACCENT}),
                    html.Span(f" data/processed csv/snapshots/  →  portfolio_report_YYYYMMDD.csv",
                              style={'color': TEXT, 'fontFamily': 'monospace', 'fontSize': '13px'}),
                ], style={'margin': '4px 0'}),
                html.Div([
                    html.Strong("Movimientos:", style={'color': ACCENT}),
                    html.Span(f" data/processed csv/transactions/  →  movimientos_YYYYMM.csv",
                              style={'color': TEXT, 'fontFamily': 'monospace', 'fontSize': '13px'}),
                ], style={'margin': '4px 0'}),
            ]),
            html.P(detail, style={'color': SUBTEXT, 'marginTop': '10px', 'fontSize': '13px'}),
        ], style={
            'background': '#1e1a0a', 'border': f'1px solid {YELLOW}',
            'borderRadius': '10px', 'padding': '20px 28px', 'margin': '20px 28px',
        })
    ])


@app.callback(
    Output('etl-status', 'children'),
    Output('etl-done', 'data'),
    Input('btn-etl', 'n_clicks'),
    State('etl-done', 'data'),
    prevent_initial_call=True,
)
def run_etl(n_clicks, done_count):
    """Ejecuta ETL importando etl.py directamente con logging."""
    if not n_clicks:
        return '', done_count
    
    t0 = time.time()
    try:
        # Importar el módulo ETL actualizado
        import etl as _etl
        import importlib
        
        # Recargar para limpiar estado entre ejecuciones
        importlib.reload(_etl)
        
        # Ejecutar ETL (esto carga snapshots + transactions desde data/processed csv/)
        import duckdb as _duckdb
        from setup_db import create_schema
        
        db_path = BASE_DIR / "data" / "db" / "portfolio.duckdb"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = _duckdb.connect(str(db_path))
        create_schema(conn, reset=False)
        
        # Procesar archivos en 'csv for ingest/' 
        _etl.process_ingest_folder(conn, force=False)
        
        # Cargar datos procesados
        snap_loaded, snap_skipped, snap_errors = _etl.load_snapshots(conn, force=False)
        trans_loaded, trans_skipped, trans_errors = _etl.load_transactions(conn, force=False)
        fx_loaded = _etl._derive_fx_from_mep(conn)
        
        conn.close()
        
        elapsed = time.time() - t0
        
        # Crear mensaje de resumen
        status_parts = []
        if snap_loaded > 0 or snap_skipped > 0:
            status_parts.append(f"[SNAP] {snap_loaded} nuevos, {snap_skipped} ya existentes")
        if trans_loaded > 0 or trans_skipped > 0:
            status_parts.append(f"[TRANS] {trans_loaded} nuevos, {trans_skipped} ya existentes")
        if fx_loaded > 0:
            status_parts.append(f"[FX] {fx_loaded} fechas derivadas")
        if snap_errors > 0 or trans_errors > 0:
            status_parts.append(f"[ERR] {snap_errors + trans_errors} error(es)")
        
        summary = " | ".join(status_parts) if status_parts else "Sin cambios"
        
        # Crear status visual
        status_content = [
            html.Div([
                html.Div('[OK] Completado', style={'fontWeight': 'bold', 'color': '#00d4aa', 'fontSize': '13px'}),
                html.Div(f'{elapsed:.1f}s', style={'color': SUBTEXT, 'fontSize': '11px', 'background': PLOT_BG, 'padding': '2px 8px', 'borderRadius': '4px'}),
            ], style={'display': 'flex', 'gap': '8px', 'alignItems': 'center'}),
            html.Div(summary, style={'color': SUBTEXT, 'fontSize': '12px', 'lineHeight': '1.4'}),
        ]
        
        total_errors = snap_errors + trans_errors
        if total_errors > 0:
            status_content.append(html.Div(f"[WARN] {total_errors} errores - revisar ingest_errors/", style={'color': '#ff6b6b', 'fontSize': '11px'}))
        
        return status_content, (done_count or 0) + 1
    
    except Exception as e:
        elapsed = time.time() - t0
        return [
            html.Div(f'[ERROR] {str(e)[:80]}', style={'color': '#ff6b6b', 'fontSize': '12px'}),
            html.Div(f'{elapsed:.1f}s', style={'color': SUBTEXT, 'fontSize': '10px'})
        ], done_count


@app.callback(
    Output('hdr-date', 'children'),
    Output('kpi-row', 'children'),
    Input('iv', 'n_intervals'),
    Input('etl-done', 'data'),
)
def update_header_kpis(n, _etl_done):
    from datetime import datetime
    try:
        df = load_returns()
        cf = load_cashflow_evolution()

        if df.empty or cf.empty:
            cards = [html.P("Base de datos vacía. Cargá CSVs y presioná Actualizar Datos.", style={'color': YELLOW})]
            hdr = "Sin datos"
            return hdr, cards

        latest  = df.iloc[-1]
        cf_last = cf.iloc[-1]

        total_usd    = latest['total_usd']
        ganancia     = cf_last['ganancia_usd']
        ganancia_pct = cf_last['ganancia_pct']
        capital_neto = cf_last['capital_neto']
        drawdown     = latest['drawdown_usd_pct']
        usd_ars      = latest['usd_ars_rate']
        fecha_dato   = pd.Timestamp(latest['fecha']).strftime('%d/%m/%Y')

        _, anualizado = compute_twr_annualized()

        cards = [
            _kpi("Valor Total",          f"${total_usd:,.0f}",     f"dato: {fecha_dato}"),
            _kpi("Ganancia USD",          f"${ganancia:,.0f}",       f"{ganancia_pct:+.1f}% total", ganancia >= 0),
            _kpi("Capital Neto",          f"${capital_neto:,.0f}",   "dep - ret"),
            _kpi("Retorno Anualizado",    f"{anualizado:+.1f}%",     "sobre capital neto", anualizado >= 0),
            _kpi("Drawdown",              f"{drawdown:.1f}%",        "desde máx histórico", drawdown >= -5),
            _kpi("USD/ARS (MEP)",         f"{usd_ars:,.0f}",         "tipo de cambio"),
        ]
        hdr = f"Actualizado: {datetime.now().strftime('%H:%M:%S')}  ·  Dato: {fecha_dato}"
    except Exception as e:
        cards = [html.P(f"Error: {e}", style={'color': RED})]
        hdr = "Error al cargar"
    return hdr, cards


@app.callback(
    Output('tabs', 'value'),
    Input('btn-goto-settings', 'n_clicks'),
    prevent_initial_call=True,
)
def goto_settings(n_clicks):
    return 'settings'


@app.callback(
    Output('base-date-store', 'data'),
    Input({'type': 'base-date-picker-inline', 'tab': ALL}, 'date'),
    State('base-date-store', 'data'),
    prevent_initial_call=True,
)
def sync_base_date(dates, current):
    from dash import callback_context
    if not callback_context.triggered:
        return current
    val = callback_context.triggered[0].get('value')
    return val if val else current


@app.callback(
    Output('tab-content', 'children'),
    Input('tabs', 'value'),
    Input('iv', 'n_intervals'),
    Input('etl-done', 'data'),
    Input('base-date-store', 'data'),
)
def render_tab(tab, _n, _etl_done, base_date):
    try:
        if tab == 'kpis':        return _tab_kpis()
        if tab == 'portfolio':   return _tab_portfolio()
        if tab == 'pnl':         return _tab_pnl()
        if tab == 'holdings':    return _tab_holdings()
        if tab == 'base100':     return _tab_base100(base_date=base_date)
        if tab == 'perf_vs_spy': return _tab_perf_vs_spy(base_date=base_date)
        if tab == 'sectores':    return _tab_sectores()
        if tab == 'cashflow':    return _tab_cashflow()
        if tab == 'settings':    return _tab_settings()
    except Exception as e:
        return html.Div([
            html.P(f"Error cargando pestaña: {e}", style={'color': RED, 'fontFamily': 'monospace'}),
        ])
    return html.P("Seleccioná una pestaña")


@app.callback(
    Output('help-modal-overlay', 'style'),
    [Input('btn-help', 'n_clicks'), Input('btn-help-close', 'n_clicks')],
    [State('help-modal-overlay', 'style')],
)
def toggle_help_modal(btn_help, btn_close, current_style):
    """Open/close Help modal overlay when button is clicked."""
    if not (btn_help or btn_close):
        return current_style
    
    is_open = current_style.get('display', 'none') == 'flex'
    new_style = current_style.copy() if current_style else {}
    new_style['display'] = 'none' if is_open else 'flex'
    return new_style


# Callback: Guardar asignación de sectores
@app.callback(
    Output('sectors-refresh', 'data', allow_duplicate=True),
    Input({'type': 'sector-dropdown', 'index': ALL}, 'value'),
    State({'type': 'sector-dropdown', 'index': ALL}, 'id'),
    State('sectors-refresh', 'data'),
    prevent_initial_call=True,
)
def save_sector_assignment(values, dropdown_ids, refresh_counter):
    """Guarda cambio de sector cuando usuario selecciona uno."""
    import requests
    from dash import callback_context

    if not callback_context.triggered or not values or not dropdown_ids:
        return no_update

    triggered_id = callback_context.triggered_id
    if not isinstance(triggered_id, dict):
        return no_update

    ticker = triggered_id.get('index')
    if not ticker:
        return no_update

    sector_id = None
    for value, dropdown_id in zip(values, dropdown_ids):
        if dropdown_id and dropdown_id.get('index') == ticker:
            sector_id = value
            break

    if sector_id is None:
        return no_update

    try:
        resp = requests.post(
            'http://127.0.0.1:8050/api/sectors/assign',
            json={'ticker': ticker, 'sector_id': sector_id},
            timeout=2
        )
        if resp.status_code == 200:
            return (refresh_counter or 0) + 1
        return no_update
    except Exception as e:
        print(f"[save_sector_assignment] Error: {e}")
        return no_update


# Callback: Subtab dentro de Sectores
@app.callback(
    Output('sectors-subtab-content', 'children'),
    Input('sectors-subtab', 'value'),
    Input('iv', 'n_intervals'),
    Input('etl-done', 'data'),
    Input('sectors-refresh', 'data'),
)
def render_sectors_subtab(subtab, _n, _etl_done, _sectors_refresh):
    if subtab == 'gestionar':
        return html.Div(
            id={'type': 'sector-manage-view', 'context': 'sectores'},
            children=_render_sectors_modal_content(context='sectores')
        )
    return _tab_sectores_evolution()


# Callback: Crear nuevo sector (subtab Sectores > Gestionar)
@app.callback(
    Output({'type': 'input-new-sector-name', 'context': 'sectores'}, 'value'),
    Output({'type': 'sector-create-feedback', 'context': 'sectores'}, 'children'),
    Output('sectors-refresh', 'data', allow_duplicate=True),
    Input({'type': 'btn-create-sector', 'context': 'sectores'}, 'n_clicks'),
    State({'type': 'input-new-sector-name', 'context': 'sectores'}, 'value'),
    State({'type': 'input-new-sector-color', 'context': 'sectores'}, 'value'),
    State('sectors-refresh', 'data'),
    prevent_initial_call=True,
)
def create_new_sector_from_subtab(n_clicks, sector_name, sector_color, refresh_counter):
    if not n_clicks or not sector_name or not sector_name.strip():
        raise PreventUpdate

    import requests
    try:
        resp = requests.post(
            'http://127.0.0.1:8050/api/sectors',
            json={'name': sector_name.strip(), 'color': sector_color or '#4169e1'},
            timeout=2
        )
        payload = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {}
        if resp.status_code == 200 and payload.get('success'):
            msg = html.Span(
                f"Sector creado: {payload.get('name', sector_name.strip())}",
                style={'color': GREEN, 'fontSize': '12px'}
            )
            return '', msg, (refresh_counter or 0) + 1

        err = payload.get('error', resp.text) if isinstance(payload, dict) else resp.text
        msg = html.Span(f"No se pudo crear: {err}", style={'color': RED, 'fontSize': '12px'})
        return no_update, msg, no_update
    except Exception as e:
        msg = html.Span(f"No se pudo crear: {e}", style={'color': RED, 'fontSize': '12px'})
        return no_update, msg, no_update


# Callback: Eliminar sector (subtab Sectores > Gestionar)
@app.callback(
    Output('sectors-refresh', 'data', allow_duplicate=True),
    Input({'type': 'btn-delete-sector', 'context': 'sectores', 'index': ALL}, 'n_clicks_timestamp'),
    State('sectors-refresh', 'data'),
    prevent_initial_call=True,
)
def delete_sector_from_subtab(_click_timestamps, refresh_counter):
    import requests
    from dash import callback_context

    if not callback_context.triggered:
        return no_update

    try:
        triggered_value = callback_context.triggered[0].get('value')
        if not triggered_value:
            return no_update
    except Exception:
        return no_update

    triggered_id = callback_context.triggered_id
    if not isinstance(triggered_id, dict):
        return no_update

    sector_id = triggered_id.get('index')
    if not sector_id:
        return no_update

    try:
        requests.delete(
            f'http://127.0.0.1:8050/api/sectors/{sector_id}',
            timeout=2
        )
    except Exception as e:
        print(f"[delete_sector_from_subtab] Error: {e}")

    return (refresh_counter or 0) + 1


# ─────────────────────────────────────────────────────────────────────────────

def _tab_kpis():
    cf = load_cashflow_evolution()
    df = load_returns()

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.66, 0.34],
        subplot_titles=('Evolución del Portfolio', 'Drawdown desde Máximo Histórico (USD)'),
    )

    fig.add_trace(go.Scatter(
        x=cf['fecha'], y=cf['ganancia_usd'], name='Ganancia USD',
        line=dict(color=GREEN, width=2.5),
        fill='tozeroy', fillcolor='rgba(0,212,170,0.12)',
        hovertemplate='%{x|%d-%b-%y}<br>$%{y:,.0f}<extra>Ganancia</extra>',
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=cf['fecha'], y=cf['capital_neto'], name='Capital Neto',
        line=dict(color=ACCENT, width=1.5, dash='dash'),
        hovertemplate='%{x|%d-%b-%y}<br>$%{y:,.0f}<extra>Capital neto</extra>',
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=cf['fecha'], y=cf['portfolio_usd'], name='Portfolio USD',
        line=dict(color=YELLOW, width=2),
        hovertemplate='%{x|%d-%b-%y}<br>$%{y:,.0f}<extra>Portfolio</extra>',
    ), row=1, col=1)
    fig.add_hline(y=0, line_color=SUBTEXT, line_dash='dot', line_width=1, row=1, col=1)

    x_min = min(pd.to_datetime(cf['fecha']).min(), pd.to_datetime(df['fecha']).min())
    x_max = max(pd.to_datetime(cf['fecha']).max(), pd.to_datetime(df['fecha']).max())
    common_range = [x_min, x_max]

    # Drawdown absoluto: max_historico * (pct/100)
    df['max_usd'] = df['total_usd'] / (1 + df['drawdown_usd_pct'] / 100)
    df['drawdown_abs'] = df['max_usd'] * (df['drawdown_usd_pct'] / 100)  # negativo

    fig.add_trace(go.Scatter(
        x=df['fecha'], y=df['drawdown_abs'], name='Drawdown USD',
        line=dict(color=RED, width=1.5),
        fill='tozeroy', fillcolor='rgba(255,107,107,0.15)',
        customdata=np.column_stack([df['drawdown_usd_pct'], df['max_usd']]),
        hovertemplate=(
            '%{x|%d-%b-%y}<br>'
            'Caída: $%{y:,.0f}<br>'
            'Desde máx: %{customdata[0]:.1f}%<br>'
            'Máx histórico: $%{customdata[1]:,.0f}'
            '<extra>Drawdown</extra>'
        ),
        showlegend=False,
    ), row=2, col=1)
    fig.add_hline(y=0, line_color=SUBTEXT, line_dash='dot', line_width=1, row=2, col=1)

    # Línea: flujo neto acumulado desde Nov-2024 (depósitos − retiros)
    # Positivo = invertiste más, Negativo = retiraste más
    REF_DATE = pd.Timestamp('2024-11-01')
    cf['fecha'] = pd.to_datetime(cf['fecha'])

    # Capital neto en la fecha de referencia (último punto antes o igual a REF_DATE)
    ref_rows = cf[cf['fecha'] <= REF_DATE]
    capital_ref = float(ref_rows['capital_neto'].iloc[-1]) if not ref_rows.empty else 0.0

    # Delta acumulado desde REF_DATE: capital_neto_actual − capital_neto_ref
    cf_desde_ref = cf[cf['fecha'] >= REF_DATE].copy()
    cf_desde_ref['flujo_neto_acum'] = cf_desde_ref['capital_neto'] - capital_ref

    fig.add_trace(go.Scatter(
        x=cf_desde_ref['fecha'],
        y=cf_desde_ref['flujo_neto_acum'],
        name='Flujo neto desde Nov-24',
        line=dict(color=YELLOW, width=1.5, dash='dot'),
        customdata=cf_desde_ref[['capital_neto']].values,
        hovertemplate=(
            '%{x|%d-%b-%y}<br>'
            'Flujo acum: $%{y:+,.0f}<br>'
            'Capital neto total: $%{customdata[0]:,.0f}'
            '<extra>Flujo Nov-24</extra>'
        ),
        showlegend=True,
    ), row=2, col=1)

    fig.update_layout(
        **PLOT_LAYOUT,
        height=680,
    )
    fig.update_layout(
        margin=dict(l=55, r=150, t=70, b=40),
        legend=dict(
            orientation='v',
            x=1.01,
            xanchor='left',
            y=1,
            yanchor='top',
            bgcolor='rgba(0,0,0,0)',
            font=dict(color=TEXT, size=11),
        ),
    )
    fig.update_xaxes(range=common_range, row=1, col=1)
    fig.update_xaxes(range=common_range, row=2, col=1)
    fig.update_yaxes(ticksuffix='', row=1, col=1)
    fig.update_yaxes(tickprefix='$', ticksuffix='', row=2, col=1)
    # Evitar reticulado blanco en drawdown.
    fig.update_xaxes(showgrid=False, row=2, col=1)
    fig.update_yaxes(showgrid=False, row=2, col=1)

    return html.Div([dcc.Graph(figure=fig, config={'displayModeBar': False})])


def _tab_portfolio():
    df = load_positions_latest()
    if df.empty:
        return html.P("Sin datos")

    fecha = pd.Timestamp(df['fecha'].iloc[0]).strftime('%d/%m/%Y')
    df_chart = df[~df['tipo'].isin(['CASH'])].copy().sort_values('total_usd', ascending=False)

    total_sum = df_chart['total_usd'].sum()
    # Label visible solo para slices >= 3%, en formato "TICKER\nXX.X%"
    custom_text = [
        f"<b>{row['ticker']}</b><br>{row['total_usd'] / total_sum * 100:.1f}%"
        if row['total_usd'] / total_sum * 100 >= 3 else ''
        for _, row in df_chart.iterrows()
    ]
    colors = (px.colors.qualitative.Bold + px.colors.qualitative.Pastel + px.colors.qualitative.Safe)

    fig_donut = go.Figure(go.Pie(
        labels=df_chart['ticker'],
        values=df_chart['total_usd'],
        text=custom_text,
        customdata=df_chart['nombre'],
        hole=0.42,
        textinfo='text',
        textposition='inside',
        insidetextorientation='auto',
        marker=dict(colors=colors[:len(df_chart)], line=dict(color=PLOT_BG, width=1.5)),
        hovertemplate='<b>%{label}</b><br>%{customdata}<br>$%{value:,.0f} · %{percent:.1%}<extra></extra>',
        sort=False,
    ))
    fig_donut.update_layout(
        **{**PLOT_LAYOUT,
           'title': dict(text=f'Composición al {fecha}', font=dict(color=TEXT)),
           'height': 430,
           'margin': dict(l=10, r=200, t=45, b=10),
           'legend': dict(
               orientation='v', x=1.01, y=0.5,
               bgcolor='rgba(0,0,0,0)',
               font=dict(color=TEXT, size=11),
               itemsizing='constant',
           ),
           'showlegend': True,
        }
    )

    cols_show = ['ticker', 'nombre', 'tipo', 'cantidad', 'precio_ars', 'total_ars', 'total_usd', 'peso_pct']
    col_defs  = [
        {'name': 'Ticker',      'id': 'ticker',     'type': 'text'},
        {'name': 'Nombre',      'id': 'nombre',     'type': 'text'},
        {'name': 'Tipo',        'id': 'tipo',        'type': 'text'},
        {'name': 'Cantidad',    'id': 'cantidad',    'type': 'numeric', 'format': {'specifier': ',.2f'}},
        {'name': 'Precio ARS',  'id': 'precio_ars',  'type': 'numeric', 'format': {'specifier': ',.2f'}},
        {'name': 'Total ARS',   'id': 'total_ars',   'type': 'numeric', 'format': {'specifier': ',.0f'}},
        {'name': 'Total USD',   'id': 'total_usd',   'type': 'numeric', 'format': {'specifier': ',.2f'}},
        {'name': '% Portf.',    'id': 'peso_pct',    'type': 'numeric', 'format': {'specifier': '.2f'}},
    ]
    table = dash_table.DataTable(
        data=df[cols_show].to_dict('records'),
        columns=col_defs,
        style_table={'overflowX': 'auto'},
        style_cell={'backgroundColor': CARD_BG, 'color': TEXT, 'border': f'1px solid {GRID}',
                    'padding': '8px 12px', 'fontSize': '13px'},
        style_header={'backgroundColor': PLOT_BG, 'color': ACCENT, 'fontWeight': '700',
                      'border': f'1px solid {GRID}'},
        style_data_conditional=[
            {'if': {'row_index': 'odd'}, 'backgroundColor': PLOT_BG},
            {'if': {'filter_query': '{tipo} = "CASH"'}, 'color': SUBTEXT},
        ],
        sort_action='native',
        page_size=30,
    )

    return html.Div([
        dcc.Graph(figure=fig_donut, config={'displayModeBar': False}),
        html.Br(),
        table,
    ])


def _tab_pnl():
    df = load_pnl_by_ticker()
    if df.empty:
        return html.P("Sin datos de P&L — se necesitan transacciones de COMPRA registradas.")

    total_return, annualized = compute_twr_annualized()

    # ── KPIs de retorno ──────────────────────────────────────────────────────
    cf = load_cashflow_evolution()
    cf_last = cf.iloc[-1] if not cf.empty else None
    ganancia_usd = cf_last['ganancia_usd'] if cf_last is not None else 0

    kpi_strip = html.Div([
        _kpi("Ganancia Total USD",  f"${ganancia_usd:,.0f}", f"{total_return:+.1f}%", ganancia_usd >= 0),
        _kpi("Retorno Anualizado",  f"{annualized:+.1f}%",   "sobre capital neto", annualized >= 0),
        _kpi("Instrumentos",        str(len(df[df['costo_usd'] > 0])), "con costo registrado"),
    ], style={'display': 'flex', 'gap': '14px', 'marginBottom': '20px', 'flexWrap': 'wrap'})

    # ── Bar chart horizontal: P&L % por ticker ───────────────────────────────
    df_chart = df[df['pnl_pct'].notna() & (df['costo_usd'] > 0)].sort_values('pnl_pct')
    colors = [GREEN if v >= 0 else RED for v in df_chart['pnl_pct']]

    fig_bar = go.Figure(go.Bar(
        x=df_chart['pnl_pct'], y=df_chart['ticker'],
        orientation='h',
        marker_color=colors,
        text=[f"{v:+.1f}%" for v in df_chart['pnl_pct']],
        textposition='outside',
        hovertemplate='<b>%{y}</b><br>P&L: %{x:+.1f}%<br>$%{customdata:,.0f}<extra></extra>',
        customdata=df_chart['pnl_usd'],
    ))
    fig_bar.add_vline(x=0, line_color=SUBTEXT, line_dash='dot', line_width=1)
    fig_bar.update_layout(
        **PLOT_LAYOUT, title='P&L % por Instrumento (costo USD al momento de compra)',
        height=max(280, len(df_chart) * 32 + 80),
        xaxis_ticksuffix='%',
    )

    # ── Tabla detalle ─────────────────────────────────────────────────────────
    cols_show = ['ticker', 'nombre', 'tipo', 'costo_usd', 'valor_usd', 'pnl_usd', 'pnl_pct']
    col_defs = [
        {'name': 'Ticker',      'id': 'ticker',    'type': 'text'},
        {'name': 'Nombre',      'id': 'nombre',    'type': 'text'},
        {'name': 'Tipo',        'id': 'tipo',       'type': 'text'},
        {'name': 'Costo USD',   'id': 'costo_usd',  'type': 'numeric', 'format': {'specifier': ',.0f'}},
        {'name': 'Valor USD',   'id': 'valor_usd',  'type': 'numeric', 'format': {'specifier': ',.0f'}},
        {'name': 'P&L USD',     'id': 'pnl_usd',    'type': 'numeric', 'format': {'specifier': '+,.0f'}},
        {'name': 'P&L %',       'id': 'pnl_pct',    'type': 'numeric', 'format': {'specifier': '+.1f'}},
    ]
    table = dash_table.DataTable(
        data=df[cols_show].to_dict('records'),
        columns=col_defs,
        style_table={'overflowX': 'auto'},
        style_cell={'backgroundColor': CARD_BG, 'color': TEXT, 'border': f'1px solid {GRID}',
                    'padding': '8px 12px', 'fontSize': '13px'},
        style_header={'backgroundColor': PLOT_BG, 'color': ACCENT, 'fontWeight': '700',
                      'border': f'1px solid {GRID}'},
        style_data_conditional=[
            {'if': {'row_index': 'odd'}, 'backgroundColor': PLOT_BG},
            {'if': {'filter_query': '{pnl_usd} > 0', 'column_id': 'pnl_usd'}, 'color': GREEN, 'fontWeight': '600'},
            {'if': {'filter_query': '{pnl_usd} < 0', 'column_id': 'pnl_usd'}, 'color': RED, 'fontWeight': '600'},
            {'if': {'filter_query': '{pnl_pct} > 0', 'column_id': 'pnl_pct'}, 'color': GREEN, 'fontWeight': '600'},
            {'if': {'filter_query': '{pnl_pct} < 0', 'column_id': 'pnl_pct'}, 'color': RED, 'fontWeight': '600'},
        ],
        sort_action='native',
        page_size=25,
    )

    note = html.P(
        "⚠ P&L basado en transacciones de COMPRA registradas, convertidas al tipo MEP del día. "
        "Para posiciones previas al historial CSV el costo aparece en $0.",
        style={'color': SUBTEXT, 'fontSize': '11px', 'margin': '8px 0 0 0', 'fontStyle': 'italic'},
    )

    return html.Div([kpi_strip, dcc.Graph(figure=fig_bar, config={'displayModeBar': False}),
                     html.Br(), table, note])


def _tab_holdings():
    df = load_holdings_evolution()
    if df.empty:
        return html.P("Sin datos")

    tickers = sorted(df['ticker'].unique())
    label_map = {t: t for t in tickers}
    colors  = px.colors.qualitative.Bold + px.colors.qualitative.Pastel

    fig_abs = go.Figure()
    for i, ticker in enumerate(tickers):
        t_df = df[df['ticker'] == ticker].sort_values('fecha')
        label = label_map.get(ticker, ticker)
        fig_abs.add_trace(go.Scatter(
            x=t_df['fecha'], y=t_df['total_usd'], name=label,
            stackgroup='one', line=dict(width=0.5, color=colors[i % len(colors)]),
            hovertemplate='%{x|%d-%b-%y}<br>$%{y:,.0f}<extra>' + label + '</extra>',
        ))
    common_range = [pd.to_datetime(df['fecha']).min(), pd.to_datetime(df['fecha']).max()]
    fig_abs.update_layout(
        **PLOT_LAYOUT,
        title='Evolución de Holdings por Instrumento (USD)',
        height=430,
    )
    fig_abs.update_layout(
        margin=dict(l=55, r=150, t=60, b=40),
        legend=dict(
            orientation='v',
            x=1.01,
            xanchor='left',
            y=1,
            yanchor='top',
            bgcolor='rgba(0,0,0,0)',
            font=dict(color=TEXT, size=11),
        ),
    )
    fig_abs.update_xaxes(range=common_range)

    fig_pct = go.Figure()
    for i, ticker in enumerate(tickers):
        t_df = df[df['ticker'] == ticker].sort_values('fecha')
        label = label_map.get(ticker, ticker)
        fig_pct.add_trace(go.Scatter(
            x=t_df['fecha'], y=t_df['pct_portfolio'], name=label,
            stackgroup='one', showlegend=False,
            line=dict(width=0.5, color=colors[i % len(colors)]),
            hovertemplate='%{x|%d-%b-%y}<br>%{y:.1f}%<extra>' + label + '</extra>',
        ))
    fig_pct.update_layout(
        **PLOT_LAYOUT,
        title='Evolución de Holdings (% del Portfolio)',
        height=280,
    )
    fig_pct.update_layout(margin=dict(l=55, r=150, t=50, b=40))
    fig_pct.update_xaxes(range=common_range)

    return html.Div([
        dcc.Graph(figure=fig_abs, config={'displayModeBar': False}),
        dcc.Graph(figure=fig_pct, config={'displayModeBar': False}),
    ])


def _base_date_picker_row(tab: str, current: str | None) -> html.Div:
    """Fila con date picker para seleccionar fecha base, ubicada debajo del gráfico."""
    if current is None:
        try:
            with duckdb.connect(str(DB_PATH), read_only=False) as conn:
                row = conn.execute("SELECT MIN(snapshot_date) FROM snapshots").fetchone()
            current = str(row[0]) if row and row[0] else '2024-04-17'
        except Exception:
            current = '2024-04-17'

    return html.Div([
        html.Span('Fecha base:', style={
            'color': SUBTEXT, 'fontSize': '12px', 'marginRight': '10px',
        }),
        dcc.DatePickerSingle(
            id={'type': 'base-date-picker-inline', 'tab': tab},
            date=current,
            display_format='DD/MM/YYYY',
            first_day_of_week=1,
            style={'fontSize': '12px'},
        ),
        html.Span(
            'Todos los instrumentos se normalizan a 100 desde esta fecha.',
            style={'color': SUBTEXT, 'fontSize': '11px', 'marginLeft': '12px', 'fontStyle': 'italic'},
        ),
    ], style={
        'display': 'flex', 'alignItems': 'center',
        'padding': '10px 4px',
        'borderTop': f'1px solid {GRID}',
        'marginTop': '4px',
    })


def _tab_base100(base_date: str | None = None):
    print("[_tab_base100] Starting...")
    try:
        df = load_holdings_normalized(base_date=base_date)
        print(f"[_tab_base100] Loaded df: {df.shape}")
        if df.empty:
            print("[_tab_base100] DataFrame is empty, returning empty message")
            return html.P("Sin datos")

        tickers = sorted(df['ticker'].unique())
        print(f"[_tab_base100] Tickers: {tickers}")
        
        # Calcular #portfolio (portfolio-weighted index) en Base 100
        mso_data = []
        for fecha in sorted(df['fecha'].unique()):
            fecha_data = df[df['fecha'] == fecha]
            total_usd = fecha_data['total_usd'].sum()
            if total_usd > 0:
                mso_value = (fecha_data['indice_100'] * fecha_data['total_usd']).sum() / total_usd
                mso_data.append({'fecha': fecha, 'indice_100': mso_value, 'ticker': '#portfolio'})
        df_mso = pd.DataFrame(mso_data)
        print(f"[_tab_base100] MSO calculated: {len(df_mso)} records")
        
        # Generar gráfico directamente
        colors = px.colors.qualitative.Bold + px.colors.qualitative.Pastel
        fig = go.Figure()
        
        # Agregar instrumentos individuales
        for i, ticker in enumerate(tickers):
            t_df = df[df['ticker'] == ticker].sort_values('fecha')
            fig.add_trace(go.Scatter(
                x=t_df['fecha'], y=t_df['indice_100'], name=ticker,
                mode='lines', line=dict(width=1.8, color=colors[i % len(colors)]),
                hovertemplate='%{x|%d-%b-%y}<br>%{y:.1f}<extra>' + ticker + '</extra>',
            ))
        
        # Agregar #portfolio (línea gruesa en rojo)
        if not df_mso.empty:
            mso_sorted = df_mso.sort_values('fecha')
            fig.add_trace(go.Scatter(
                x=mso_sorted['fecha'], y=mso_sorted['indice_100'], name='#portfolio (Portfolio)',
                mode='lines', line=dict(width=3.2, color='#ff6b6b'),
                hovertemplate='%{x|%d-%b-%y}<br>%{y:.1f} (#portfolio)<extra></extra>',
            ))
        
        fig.add_hline(y=100, line_color=SUBTEXT, line_dash='dot', line_width=1.2,
                      annotation_text='Base 100', annotation_font_color=SUBTEXT)
        fig.update_layout(**PLOT_LAYOUT, title='Performance Normalizada — Base 100 por instrumento (con #portfolio)', height=550)
        
        print("[_tab_base100] Figure created successfully")
        return html.Div([
            dcc.Graph(figure=fig, config={'displayModeBar': False}),
            _base_date_picker_row(tab='base100', current=base_date),
        ])
        
    except Exception as e:
        print(f"[_tab_base100] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return html.Div([
            html.P(f"Error en _tab_base100: {e}", style={'color': RED, 'fontFamily': 'monospace', 'whiteSpace': 'pre-wrap'}),
        ])


def _list_backup_files() -> list[Path]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = list(BACKUP_DIR.glob('portfolio_bkp_*.duckdb'))
    for legacy in [
        BASE_DIR / 'data' / 'portfolio_bkp.duckdb',
        BASE_DIR / 'data' / 'db' / 'portfolio_bkp.duckdb',
    ]:
        if legacy.exists():
            backups.append(legacy)
    unique = {str(p.resolve()): p for p in backups}
    return sorted(unique.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def _backup_dropdown_options() -> tuple[list[dict], str | None]:
    files = _list_backup_files()
    options = []
    for p in files:
        stem = p.stem
        label = p.name
        parts = stem.split('_')
        if len(parts) >= 4:
            dt = f"{parts[-2]} {parts[-1]}"
            label = f"{dt} · {p.name}"
        if p.parent != BACKUP_DIR:
            label = f"{label} · {p.parent.name}/"
        options.append({'label': label, 'value': str(p.resolve())})
    default_value = options[0]['value'] if options else None
    return options, default_value


def _clear_core_tables(conn: duckdb.DuckDBPyConnection) -> None:
    for table in [
        'instrument_sectors',
        'sector_list',
        'scenario_overrides',
        'scenarios',
        'snapshots',
        'transactions',
        'fx_rates',
        'portfolio_history',
        'instruments',
    ]:
        conn.execute(f'DELETE FROM {table}')


def _clear_ingest_logs() -> int:
    removed = 0
    for folder in [BASE_DIR / 'data' / 'ingest_logs', BASE_DIR / 'data' / 'ingest_errors']:
        if not folder.exists():
            continue
        for p in folder.rglob('*'):
            if p.is_file():
                p.unlink(missing_ok=True)
                removed += 1
    return removed


def _restore_from_backup_file(backup_file: Path) -> list[str]:
    from setup_db import create_schema
    restored = []

    with duckdb.connect(str(DB_PATH), read_only=False) as conn:
        create_schema(conn, reset=False)
        _clear_core_tables(conn)

        conn.execute(f"ATTACH '{backup_file.as_posix()}' AS bkp")
        bkp_tables = {
            r[0] for r in conn.execute(
                "SELECT table_name FROM bkp.information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE'"
            ).fetchall()
        }

        for table in [
            'instruments',
            'snapshots',
            'transactions',
            'fx_rates',
            'portfolio_history',
            'scenarios',
            'scenario_overrides',
            'sector_list',
            'instrument_sectors',
        ]:
            if table in bkp_tables:
                conn.execute(f'INSERT INTO {table} SELECT * FROM bkp.{table}')
                restored.append(table)

        conn.execute('DETACH bkp')

        if 'sector_list' not in bkp_tables:
            from sector_manager import init_sectors
            init_sectors(conn)

    return restored


def _fmt_dt(value) -> str:
    if value is None:
        return '-'
    try:
        return value.strftime('%Y-%m-%d')
    except Exception:
        return str(value)


def _load_db_csv_transparency() -> dict:
    snap_csv_files = sorted(SNAPSHOTS_CSV_DIR.glob('portfolio_report_*.csv')) if SNAPSHOTS_CSV_DIR.exists() else []
    tx_csv_files = sorted(TRANSACTIONS_CSV_DIR.glob('movimientos_*.csv')) if TRANSACTIONS_CSV_DIR.exists() else []

    csv_snap_dates = set()
    for f in snap_csv_files:
        m = re.search(r'(\d{8})', f.name)
        if not m:
            continue
        d = m.group(1)
        csv_snap_dates.add(f'{d[:4]}-{d[4:6]}-{d[6:8]}')

    csv_tx_months = set()
    for f in tx_csv_files:
        csv_tx_months.update(_extract_tx_months_from_csv(f))

    with duckdb.connect(str(DB_PATH), read_only=False) as conn:
        db_snap = conn.execute(
            """
            SELECT
                COUNT(*) AS rows_n,
                COUNT(DISTINCT snapshot_date) AS dates_n,
                MIN(snapshot_date) AS min_d,
                MAX(snapshot_date) AS max_d
            FROM snapshots
            """
        ).fetchone()
        db_snap_dates = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT STRFTIME(snapshot_date, '%Y-%m-%d') FROM snapshots"
            ).fetchall() if r[0]
        }

        db_tx = conn.execute(
            """
            SELECT
                COUNT(*) AS rows_n,
                COUNT(DISTINCT STRFTIME(fecha_op, '%Y-%m')) AS months_n,
                MIN(fecha_op) AS min_d,
                MAX(fecha_op) AS max_d
            FROM transactions
            WHERE fecha_op IS NOT NULL
            """
        ).fetchone()
        db_tx_months = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT STRFTIME(fecha_op, '%Y-%m') FROM transactions WHERE fecha_op IS NOT NULL"
            ).fetchall() if r[0]
        }

    pending_csv = len(list(INGEST_DIR.glob('*.csv'))) if INGEST_DIR.exists() else 0

    missing_snap_dates = sorted(csv_snap_dates - db_snap_dates)
    missing_tx_months = sorted(csv_tx_months - db_tx_months)

    return {
        'snap_csv_files': len(snap_csv_files),
        'snap_csv_dates': len(csv_snap_dates),
        'snap_db_rows': int(db_snap[0] or 0),
        'snap_db_dates': int(db_snap[1] or 0),
        'snap_db_min': _fmt_dt(db_snap[2]),
        'snap_db_max': _fmt_dt(db_snap[3]),
        'tx_csv_files': len(tx_csv_files),
        'tx_csv_months': len(csv_tx_months),
        'tx_db_rows': int(db_tx[0] or 0),
        'tx_db_months': int(db_tx[1] or 0),
        'tx_db_min': _fmt_dt(db_tx[2]),
        'tx_db_max': _fmt_dt(db_tx[3]),
        'missing_snap_dates': missing_snap_dates,
        'missing_tx_months': missing_tx_months,
        'pending_ingest_csv': pending_csv,
    }


def _extract_tx_months_from_csv(filepath: Path) -> set[str]:
    """Extrae meses YYYY-MM desde FechaEjecucion de un CSV de movimientos."""
    try:
        df = pd.read_csv(filepath, sep=';', encoding='utf-8-sig', dtype=str, usecols=['FechaEjecucion'])
    except Exception:
        try:
            df = pd.read_csv(filepath, sep=';', encoding='utf-8-sig', dtype=str)
        except Exception:
            return set()

    cols = {c.lower(): c for c in df.columns}
    src_col = cols.get('fechaejecucion')
    if not src_col:
        return set()

    dates = pd.to_datetime(df[src_col], format='%d-%m-%Y', errors='coerce')
    return {d.strftime('%Y-%m') for d in dates.dropna()}


def _status_badge(ok: bool, text_ok: str = 'OK', text_warn: str = 'Revisar'):
    color = GREEN if ok else YELLOW
    label = text_ok if ok else text_warn
    return html.Span(
        label,
        style={
            'display': 'inline-block',
            'padding': '3px 8px',
            'borderRadius': '999px',
            'fontSize': '11px',
            'fontWeight': '700',
            'border': f'1px solid {color}',
            'color': color,
            'background': 'rgba(255,255,255,0.02)',
        },
    )


def _tab_transparency_panel(card_style: dict):
    try:
        info = _load_db_csv_transparency()
    except Exception as e:
        return html.Div([
            html.H3('Transparencia DB vs CSV', style={'margin': '0 0 8px 0', 'color': TEXT, 'fontSize': '15px'}),
            html.P(f'Error obteniendo estado de carga: {e}', style={'margin': 0, 'color': RED, 'fontSize': '12px'}),
        ], style=card_style)

    missing_snap = info['missing_snap_dates']
    missing_tx = info['missing_tx_months']
    snap_ok = len(missing_snap) == 0
    tx_ok = len(missing_tx) == 0
    ingest_ok = info['pending_ingest_csv'] == 0

    def _preview(items: list[str]) -> str:
        if not items:
            return 'ninguno'
        head = ', '.join(items[:8])
        if len(items) > 8:
            return f'{head} ... (+{len(items) - 8})'
        return head

    return html.Div([
        html.H3('Transparencia DB vs CSV', style={'margin': '0 0 8px 0', 'color': TEXT, 'fontSize': '15px'}),
        html.P(
            'Compara lo disponible en CSV procesados vs lo efectivamente cargado en DuckDB.',
            style={'margin': '0 0 12px 0', 'color': SUBTEXT, 'fontSize': '12px'}
        ),
        html.Div([
            html.Div([
                html.P('Snapshots', style={'margin': '0 0 4px 0', 'color': SUBTEXT, 'fontSize': '12px'}),
                _status_badge(snap_ok),
                html.P(f"CSV: {info['snap_csv_files']} archivos / {info['snap_csv_dates']} fechas", style={'margin': '8px 0 0 0', 'color': TEXT, 'fontSize': '12px'}),
                html.P(f"DB: {info['snap_db_rows']} filas / {info['snap_db_dates']} fechas", style={'margin': '2px 0 0 0', 'color': TEXT, 'fontSize': '12px'}),
                html.P(f"Rango DB: {info['snap_db_min']} → {info['snap_db_max']}", style={'margin': '2px 0 0 0', 'color': SUBTEXT, 'fontSize': '11px'}),
                html.P(f"Faltan en DB: {_preview(missing_snap)}", style={'margin': '6px 0 0 0', 'color': YELLOW if missing_snap else GREEN, 'fontSize': '11px'}),
            ], style={'flex': '1', 'minWidth': '280px', 'padding': '10px', 'border': f'1px solid {GRID}', 'borderRadius': '8px'}),
            html.Div([
                html.P('Transacciones', style={'margin': '0 0 4px 0', 'color': SUBTEXT, 'fontSize': '12px'}),
                _status_badge(tx_ok),
                html.P(f"CSV: {info['tx_csv_files']} archivos / {info['tx_csv_months']} meses", style={'margin': '8px 0 0 0', 'color': TEXT, 'fontSize': '12px'}),
                html.P(f"DB: {info['tx_db_rows']} filas / {info['tx_db_months']} meses", style={'margin': '2px 0 0 0', 'color': TEXT, 'fontSize': '12px'}),
                html.P(f"Rango DB: {info['tx_db_min']} → {info['tx_db_max']}", style={'margin': '2px 0 0 0', 'color': SUBTEXT, 'fontSize': '11px'}),
                html.P(f"Meses faltantes en DB: {_preview(missing_tx)}", style={'margin': '6px 0 0 0', 'color': YELLOW if missing_tx else GREEN, 'fontSize': '11px'}),
            ], style={'flex': '1', 'minWidth': '280px', 'padding': '10px', 'border': f'1px solid {GRID}', 'borderRadius': '8px'}),
            html.Div([
                html.P('Ingest Pendiente', style={'margin': '0 0 4px 0', 'color': SUBTEXT, 'fontSize': '12px'}),
                _status_badge(ingest_ok, text_ok='Sin pendiente', text_warn='Hay pendientes'),
                html.P(f"csv for ingest/: {info['pending_ingest_csv']} archivo(s)", style={'margin': '8px 0 0 0', 'color': TEXT, 'fontSize': '12px'}),
                html.P('Si hay pendientes, corré ETL para que impacte en DB.', style={'margin': '6px 0 0 0', 'color': SUBTEXT, 'fontSize': '11px'}),
            ], style={'flex': '1', 'minWidth': '240px', 'padding': '10px', 'border': f'1px solid {GRID}', 'borderRadius': '8px'}),
        ], style={'display': 'flex', 'gap': '10px', 'flexWrap': 'wrap'}),
    ], style=card_style)


def _tab_settings():
    """Configuración y tareas de mantenimiento."""
    card_style = {
        'background': CARD_BG,
        'border': f'1px solid {GRID}',
        'borderRadius': '10px',
        'padding': '16px',
        'marginBottom': '14px',
    }

    backup_options, backup_default = _backup_dropdown_options()

    return html.Div([
        html.H2('Settings', style={'margin': '0 0 14px 0', 'color': TEXT, 'fontSize': '20px'}),

        _tab_transparency_panel(card_style),

        html.Div([
            html.H3('Backups de Base de Datos', style={'margin': '0 0 8px 0', 'color': TEXT, 'fontSize': '15px'}),
            html.P(
                'Generá backups con fecha y restaurá seleccionando el archivo.',
                style={'margin': '0 0 12px 0', 'color': SUBTEXT, 'fontSize': '12px'}
            ),
            html.Div([
                html.Button(
                    '💾 Generar Backup',
                    id='btn-create-backup',
                    n_clicks=0,
                    style={
                        'background': 'rgba(74, 158, 255, 0.14)',
                        'color': ACCENT,
                        'border': f'1px solid {ACCENT}',
                        'borderRadius': '7px',
                        'padding': '8px 16px',
                        'fontSize': '13px',
                        'cursor': 'pointer',
                        'fontFamily': 'inherit',
                        'fontWeight': '700',
                        'marginRight': '8px',
                    },
                ),
                dcc.Dropdown(
                    id='backup-file-selector',
                    options=backup_options,
                    value=backup_default,
                    placeholder='Seleccionar backup para restaurar...',
                    clearable=False,
                    style={'minWidth': '380px', 'flex': '1'},
                ),
                html.Button(
                    '♻ Restaurar Seleccionado',
                    id='btn-restore-backup',
                    n_clicks=0,
                    style={
                        'background': 'rgba(255, 209, 102, 0.14)',
                        'color': YELLOW,
                        'border': f'1px solid {YELLOW}',
                        'borderRadius': '7px',
                        'padding': '8px 16px',
                        'fontSize': '13px',
                        'cursor': 'pointer',
                        'fontFamily': 'inherit',
                        'fontWeight': '700',
                        'marginLeft': '8px',
                    },
                ),
            ], style={'display': 'flex', 'gap': '8px', 'alignItems': 'center', 'flexWrap': 'wrap'}),
            html.Div(
                id='settings-backup-result',
                style={'marginTop': '10px', 'minHeight': '18px', 'color': SUBTEXT, 'fontSize': '12px'}
            ),
        ], style=card_style),

        html.Div([
            html.H3('Mantenimiento de Datos', style={'margin': '0 0 8px 0', 'color': TEXT, 'fontSize': '15px'}),
            html.P(
                'Borra solo data de tablas y logs de ingest. No elimina archivos CSV.',
                style={'margin': '0 0 14px 0', 'color': SUBTEXT, 'fontSize': '12px'}
            ),
            html.Button(
                '🧹 Borrar Data + Logs',
                id='btn-clear-data',
                n_clicks=0,
                style={
                    'background': 'rgba(255, 107, 107, 0.15)',
                    'color': RED,
                    'border': f'1px solid {RED}',
                    'borderRadius': '7px',
                    'padding': '8px 16px',
                    'fontSize': '13px',
                    'cursor': 'pointer',
                    'fontFamily': 'inherit',
                    'fontWeight': '700',
                },
            ),
            html.Div(
                id='settings-action-result',
                style={'marginTop': '10px', 'minHeight': '18px', 'color': SUBTEXT, 'fontSize': '12px'}
            ),
        ], style=card_style),
    ])


@app.callback(
    Output('confirm-clear-data', 'displayed'),
    Input('btn-clear-data', 'n_clicks'),
    prevent_initial_call=True,
)
def ask_confirm_clear_data(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    return True


@app.callback(
    Output('settings-action-result', 'children'),
    Output('etl-done', 'data', allow_duplicate=True),
    Output('sectors-refresh', 'data', allow_duplicate=True),
    Input('confirm-clear-data', 'submit_n_clicks'),
    State('etl-done', 'data'),
    State('sectors-refresh', 'data'),
    prevent_initial_call=True,
)
def clear_data_and_logs(submit_n_clicks, etl_done, sectors_refresh):
    if not submit_n_clicks:
        raise PreventUpdate

    try:
        with duckdb.connect(str(DB_PATH), read_only=False) as conn:
            _clear_core_tables(conn)

        logs_removed = _clear_ingest_logs()
        msg = f'OK: data de tablas limpiada y {logs_removed} archivos de log eliminados.'
        return msg, (etl_done or 0) + 1, (sectors_refresh or 0) + 1
    except Exception as e:
        return f'Error al limpiar data/logs: {e}', no_update, no_update


@app.callback(
    Output('confirm-restore-backup', 'displayed'),
    Output('settings-backup-result', 'children', allow_duplicate=True),
    Input('btn-restore-backup', 'n_clicks'),
    State('backup-file-selector', 'value'),
    prevent_initial_call=True,
)
def ask_confirm_restore_backup(n_clicks, selected_backup):
    if not n_clicks:
        raise PreventUpdate
    if not selected_backup:
        return False, 'Seleccioná un backup para restaurar.'
    return True, no_update


@app.callback(
    Output('settings-backup-result', 'children'),
    Output('backup-file-selector', 'options'),
    Output('backup-file-selector', 'value'),
    Output('etl-done', 'data', allow_duplicate=True),
    Output('sectors-refresh', 'data', allow_duplicate=True),
    Input('btn-create-backup', 'n_clicks'),
    Input('confirm-restore-backup', 'submit_n_clicks'),
    State('backup-file-selector', 'value'),
    State('etl-done', 'data'),
    State('sectors-refresh', 'data'),
    prevent_initial_call=True,
)
def handle_backup_actions(create_clicks, restore_submit_clicks, selected_backup, etl_done, sectors_refresh):
    from dash import callback_context

    triggered = callback_context.triggered_id
    if not triggered:
        raise PreventUpdate

    try:
        if triggered == 'btn-create-backup':
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime('%Y%m%d_%H%M%S')
            backup_path = BACKUP_DIR / f'portfolio_bkp_{ts}.duckdb'

            with duckdb.connect(str(DB_PATH), read_only=False) as conn:
                conn.execute('CHECKPOINT')
            shutil.copy2(DB_PATH, backup_path)

            options, value = _backup_dropdown_options()
            msg = f'Backup creado: {backup_path.name}'
            return msg, options, str(backup_path.resolve()), (etl_done or 0) + 1, (sectors_refresh or 0) + 1

        if triggered == 'confirm-restore-backup':
            if not restore_submit_clicks:
                raise PreventUpdate
            if not selected_backup:
                options, value = _backup_dropdown_options()
                return 'Seleccioná un backup para restaurar.', options, value, no_update, no_update

            backup_path = Path(selected_backup)
            if not backup_path.exists():
                options, value = _backup_dropdown_options()
                return f'No existe el backup seleccionado: {selected_backup}', options, value, no_update, no_update

            restored = _restore_from_backup_file(backup_path)
            options, value = _backup_dropdown_options()
            msg = f'Restore OK desde {selected_backup}. Tablas restauradas: {", ".join(restored) if restored else "ninguna"}.'
            return msg, options, selected_backup, (etl_done or 0) + 1, (sectors_refresh or 0) + 1

    except Exception as e:
        options, value = _backup_dropdown_options()
        return f'Error en backup/restore: {e}', options, value, no_update, no_update

    raise PreventUpdate


def _tab_perf_vs_spy(base_date: str | None = None):
    """Performance de cada instrumento vs SPY. SPY siempre en 100. Incluye índice MSO."""
    print("[_tab_perf_vs_spy] Starting...")
    try:
        df = load_performance_vs_spy(base_date=base_date)
        print(f"[_tab_perf_vs_spy] Loaded df: {df.shape}")
        
        if df.empty:
            print("[_tab_perf_vs_spy] DataFrame is empty, returning empty message")
            return html.P("Sin datos")

        # Separar MSO del resto de tickers
        df_instruments = df[df['ticker'] != 'MSO'].copy()
        df_mso_raw = df[df['ticker'] == 'MSO'].copy() if 'MSO' in df['ticker'].unique() else None

        # Calcular MSO manualmente si no está en la data
        if df_mso_raw is None or df_mso_raw.empty:
            # MSO = índice_100 ponderado por posición en cada momento
            mso_data = []
            for fecha in df_instruments['fecha'].unique():
                fecha_data = df_instruments[df_instruments['fecha'] == fecha]
                total_usd = fecha_data['total_usd'].sum()
                if total_usd > 0:
                    mso_value = (fecha_data['indice_100'] * fecha_data['total_usd']).sum() / total_usd
                    mso_data.append({'fecha': fecha, 'ticker': 'MSO', 'nombre': 'Portfolio Index', 
                                     'perf_vs_spy': mso_value})
            df_mso = pd.DataFrame(mso_data) if mso_data else pd.DataFrame()
        else:
            df_mso = df_mso_raw[['fecha', 'ticker', 'perf_vs_spy']].copy()

        tickers = sorted([t for t in df_instruments['ticker'].unique() if t != 'MSO'])
        colors  = px.colors.qualitative.Bold + px.colors.qualitative.Pastel

        fig = go.Figure()
        
        # Agregar SPY (siempre 100)
        spy_data = df_instruments[df_instruments['ticker'] == 'SPY']
        if not spy_data.empty:
            spy_sorted = spy_data.sort_values('fecha')
            fig.add_trace(go.Scatter(
                x=spy_sorted['fecha'], y=[100]*len(spy_sorted), name='SPY (Benchmark)',
                mode='lines', line=dict(width=2.5, color='#00d4aa', dash='dash'),
                hovertemplate='%{x|%d-%b-%y}<br>100.0 (Benchmark)<extra></extra>',
            ))
        
        # Agregar otros instrumentos
        for i, ticker in enumerate(tickers):
            if ticker == 'SPY':
                continue
            t_df = df_instruments[df_instruments['ticker'] == ticker].sort_values('fecha')
            if t_df.empty:
                continue
            fig.add_trace(go.Scatter(
                x=t_df['fecha'], y=t_df['perf_vs_spy'], name=ticker,
                mode='lines', line=dict(width=1.5, color=colors[i % len(colors)]),
                hovertemplate='%{x|%d-%b-%y}<br>%{y:.1f}<extra>' + ticker + '</extra>',
            ))
        
        # Agregar portfolio en resalte (línea gruesa)
        if not df_mso.empty:
            mso_sorted = df_mso.sort_values('fecha')
            fig.add_trace(go.Scatter(
                x=mso_sorted['fecha'], y=mso_sorted['perf_vs_spy'], name='#portfolio (Portfolio)',
                mode='lines', line=dict(width=3.2, color='#ff6b6b'),
                hovertemplate='%{x|%d-%b-%y}<br>%{y:.1f} (#portfolio)<extra></extra>',
            ))
        
        fig.add_hline(y=100, line_color=SUBTEXT, line_dash='dot', line_width=1.2,
                      annotation_text='SPY Base', annotation_font_color=SUBTEXT)
        fig.update_layout(**PLOT_LAYOUT, 
                         title='Performance vs SPY — Rendimiento relativo del portfolio (#portfolio)', 
                         height=550)
        
        print("[_tab_perf_vs_spy] Figure created successfully")
        return html.Div([
            dcc.Graph(figure=fig, config={'displayModeBar': False}),
            _base_date_picker_row(tab='perf_vs_spy', current=base_date),
        ])
        
    except Exception as e:
        print(f"[_tab_perf_vs_spy] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return html.Div([
            html.P(f"Error en _tab_perf_vs_spy: {e}", style={'color': RED, 'fontFamily': 'monospace', 'whiteSpace': 'pre-wrap'}),
        ])


def _render_sectors_modal_content(context='admin'):
    """Renderiza gestión de sectores para Administración o para modal."""
    import requests

    is_modal = context == 'modal'
    dropdown_type = 'sector-dropdown-modal' if is_modal else 'sector-dropdown'
    
    try:
        resp_sectors = requests.get('http://127.0.0.1:8050/api/sectors', timeout=2)
        resp_instruments = requests.get('http://127.0.0.1:8050/api/sectors/instruments', timeout=2)
        
        sectors = resp_sectors.json().get('data', []) if resp_sectors.status_code == 200 else []
        instruments = resp_instruments.json().get('data', []) if resp_instruments.status_code == 200 else []
    except Exception as e:
        return html.Div([html.P(f"Error: {e}", style={'color': RED})])
    
    # Contar instrumentos
    unassigned = [i for i in instruments if i.get('sector_id', 0) == 0]
    assigned = [i for i in instruments if i.get('sector_id', 0) > 0]
    
    # Tabla de instrumentos
    table_rows = []
    for inst in sorted(instruments, key=lambda x: x['ticker']):
        ticker = inst['ticker']
        sector_id = inst.get('sector_id', 0)
        
        sorted_sectors = sorted(sectors, key=lambda s: s.get('name', '').casefold())
        dropdown_options = [{'label': '--- Sin asignar ---', 'value': 0}]
        dropdown_options.extend([{'label': s['name'], 'value': s['id']} for s in sorted_sectors])
        
        row = html.Tr([
            html.Td(html.B(ticker, style={'color': ACCENT}), style={'width': '100px', 'fontWeight': '600', 'padding': '8px'}),
            html.Td(inst.get('nombre', '')[:40], style={'width': '280px', 'fontSize': '12px', 'color': SUBTEXT, 'padding': '8px'}),
            html.Td(
                dcc.Dropdown(
                    id={'type': dropdown_type, 'index': ticker},
                    options=dropdown_options,
                    value=sector_id,
                    style={'width': '100%'},
                    clearable=False,
                ),
                style={'width': '220px', 'padding': '6px'}
            ),
            html.Td(
                html.Span(
                    inst.get('sector_name', 'Sin sector'),
                    style={
                        'display': 'inline-block',
                        'padding': '4px 10px',
                        'borderRadius': '4px',
                        'background': inst.get('color', '#808080') + '33',
                        'color': inst.get('color', '#808080'),
                        'fontSize': '11px',
                        'fontWeight': '600',
                    }
                ),
                style={'width': '150px', 'padding': '8px'}
            ),
        ])
        table_rows.append(row)
    
    return html.Div([
        html.Div([
            html.H3('Asignar Sectores a Instrumentos', style={'margin': '0 0 12px 0', 'fontSize': '15px', 'color': TEXT, 'fontWeight': '600'}),
            html.P(f"{len(assigned)} asignados · {len(unassigned)} sin sector", style={'color': SUBTEXT, 'fontSize': '12px', 'margin': '0 0 16px 0'}),
        ]),
        
        html.Div([
            html.Table([
                html.Thead(
                    html.Tr([
                        html.Th('Ticker', style={'textAlign': 'left', 'padding': '8px', 'width': '100px', 'fontSize': '12px', 'color': SUBTEXT, 'fontWeight': '600', 'borderBottom': f'1px solid {GRID}'}),
                        html.Th('Instrumento', style={'textAlign': 'left', 'padding': '8px', 'width': '280px', 'fontSize': '12px', 'color': SUBTEXT, 'fontWeight': '600', 'borderBottom': f'1px solid {GRID}'}),
                        html.Th('Asignar Sector', style={'textAlign': 'left', 'padding': '8px', 'width': '220px', 'fontSize': '12px', 'color': SUBTEXT, 'fontWeight': '600', 'borderBottom': f'1px solid {GRID}'}),
                        html.Th('Sector Actual', style={'textAlign': 'left', 'padding': '8px', 'width': '150px', 'fontSize': '12px', 'color': SUBTEXT, 'fontWeight': '600', 'borderBottom': f'1px solid {GRID}'}),
                    ])
                ),
                html.Tbody(table_rows),
            ], style={
                'width': '100%',
                'borderCollapse': 'collapse',
                'fontSize': '13px',
            })
        ], style={
            'background': CARD_BG,
            'border': f'1px solid {GRID}',
            'borderRadius': '8px',
            'padding': '12px',
            'overflowX': 'auto',
        }),
        
        html.Div([
            html.H4('Gestión de Sectores', style={'margin': '0 0 16px 0', 'fontSize': '14px', 'color': TEXT, 'fontWeight': '600'}),
            
            # Crear nuevo sector
            html.Div([
                html.H5('Crear Nuevo Sector', style={'margin': '0 0 12px 0', 'fontSize': '12px', 'color': TEXT, 'fontWeight': '600'}),
                html.Div([
                    dcc.Input(
                        id={'type': 'input-new-sector-name', 'context': context},
                        type='text',
                        placeholder='Nombre del sector...',
                        style={
                            'flex': '1',
                            'padding': '8px',
                            'borderRadius': '4px',
                            'border': f'1px solid {GRID}',
                            'background': CARD_BG,
                            'color': TEXT,
                            'fontSize': '12px',
                        }
                    ),
                    dcc.Input(
                        id={'type': 'input-new-sector-color', 'context': context},
                        type='color',
                        value='#4169e1',
                        style={
                            'width': '50px',
                            'height': '36px',
                            'border': f'1px solid {GRID}',
                            'borderRadius': '4px',
                            'cursor': 'pointer',
                        }
                    ),
                    html.Button(
                        '+ Crear',
                        id={'type': 'btn-create-sector', 'context': context},
                        n_clicks=0,
                        style={
                            'padding': '8px 16px',
                            'background': ACCENT,
                            'color': '#000',
                            'border': 'none',
                            'borderRadius': '4px',
                            'cursor': 'pointer',
                            'fontWeight': '600',
                            'fontSize': '12px',
                        }
                    ),
                ], style={'display': 'flex', 'gap': '8px', 'alignItems': 'center'})
                ,
                html.Div(
                    id={'type': 'sector-create-feedback', 'context': context},
                    style={'marginTop': '8px', 'minHeight': '18px'}
                )
            ], style={'background': CARD_BG, 'padding': '12px', 'borderRadius': '6px', 'border': f'1px solid {GRID}', 'marginBottom': '16px'}),
            
            # Lista de sectores con opción de eliminar
            html.Div([
                html.H5('Sectores Existentes', style={'margin': '0 0 12px 0', 'fontSize': '12px', 'color': TEXT, 'fontWeight': '600'}),
                html.Div([
                    html.Div([
                        html.Span(
                            s['name'],
                            style={
                                'display': 'inline-block',
                                'padding': '6px 12px',
                                'borderRadius': '6px',
                                'background': s['color'] + '33',
                                'color': s['color'],
                                'fontSize': '12px',
                                'fontWeight': '600',
                                'marginRight': '12px',
                            }
                        ),
                        html.Button(
                            '✕ Eliminar',
                            id={'type': 'btn-delete-sector', 'context': context, 'index': s['id']},
                            style={
                                'padding': '4px 10px',
                                'fontSize': '11px',
                                'background': 'rgba(255, 107, 107, 0.15)',
                                'color': RED,
                                'border': f'1px solid {RED}',
                                'borderRadius': '4px',
                                'cursor': 'pointer',
                                'fontWeight': '600',
                            },
                            n_clicks=0,
                        ),
                    ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px', 'marginBottom': '8px'})
                    for s in sorted(sectors, key=lambda x: x['name'])
                ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '6px'})
            ], style={'background': CARD_BG, 'padding': '12px', 'borderRadius': '6px', 'border': f'1px solid {GRID}'}),
        ]),
    ])


def _tab_sectores_evolution():
    """Evolución de sectores con el mismo lenguaje visual de Holdings."""
    try:
        df = load_positions_evolution_with_sectors()
        if df.empty:
            return html.Div([html.P("Sin datos de sectores", style={'color': SUBTEXT})])

        df = df.copy()
        df['fecha'] = pd.to_datetime(df['fecha'])

        latest_date = df['fecha'].max()
        latest_data = df[df['fecha'] == latest_date]
        sector_sums = latest_data.groupby('sector_name', as_index=False).agg(
            total_usd=('total_usd', 'sum'),
            color=('color', 'first')
        ).sort_values('total_usd', ascending=False)

        sector_order = sector_sums['sector_name'].tolist()
        all_dates = pd.DatetimeIndex(sorted(df['fecha'].dropna().unique()))

        # Serie densa fecha x sector para evitar "dientes de sierra" por fechas faltantes.
        abs_matrix = (
            df.pivot_table(index='fecha', columns='sector_name', values='total_usd', aggfunc='sum')
            .reindex(index=all_dates, columns=sector_order)
            .fillna(0.0)
        )
        total_series = abs_matrix.sum(axis=1)
        pct_matrix = abs_matrix.div(total_series.where(total_series > 0, np.nan), axis=0).fillna(0.0) * 100.0

        fig_abs = go.Figure()
        for sector in sector_order:
            color_row = sector_sums[sector_sums['sector_name'] == sector]
            color = color_row.iloc[0]['color'] if not color_row.empty else '#808080'
            fig_abs.add_trace(go.Scatter(
                x=abs_matrix.index, y=abs_matrix[sector], name=sector,
                stackgroup='one', line=dict(width=0.5, color=color),
                hovertemplate='%{x|%d-%b-%y}<br>$%{y:,.0f}<extra>' + sector + '</extra>',
            ))
        common_range = [abs_matrix.index.min(), abs_matrix.index.max()]
        fig_abs.update_layout(
            **PLOT_LAYOUT,
            title='Evolución de Sectores (USD)',
            height=430,
            hovermode='x unified',
        )
        fig_abs.update_layout(
            margin=dict(l=55, r=150, t=60, b=40),
            legend=dict(
                orientation='v',
                x=1.01,
                xanchor='left',
                y=1,
                yanchor='top',
                bgcolor='rgba(0,0,0,0)',
                font=dict(color=TEXT, size=11),
            ),
        )
        fig_abs.update_xaxes(range=common_range)

        fig_pct = go.Figure()
        for sector in sector_order:
            color_row = sector_sums[sector_sums['sector_name'] == sector]
            color = color_row.iloc[0]['color'] if not color_row.empty else '#808080'
            fig_pct.add_trace(go.Scatter(
                x=pct_matrix.index, y=pct_matrix[sector], name=sector,
                stackgroup='one', showlegend=False,
                line=dict(width=0.5, color=color),
                hovertemplate='%{x|%d-%b-%y}<br>%{y:.1f}%<extra>' + sector + '</extra>',
            ))
        fig_pct.update_layout(
            **PLOT_LAYOUT,
            title='Evolución de Sectores (% del Portfolio)',
            height=280,
            hovermode='x unified',
        )
        fig_pct.update_layout(margin=dict(l=55, r=150, t=50, b=40))
        fig_pct.update_xaxes(range=common_range)

        fig_donut = go.Figure(go.Pie(
            labels=sector_sums['sector_name'],
            values=sector_sums['total_usd'],
            hole=0.42,
            sort=False,
            marker=dict(colors=sector_sums['color'], line=dict(color=PLOT_BG, width=1.5)),
            hovertemplate='<b>%{label}</b><br>$%{value:,.0f} · %{percent:.1%}<extra></extra>',
            textinfo='label+percent',
            textposition='inside',
        ))
        fig_donut.update_layout(
            **{**PLOT_LAYOUT,
               'title': 'Distribución Actual por Sector (USD)',
               'height': 430,
               'margin': dict(l=10, r=220, t=45, b=10),
               'legend': dict(
                   orientation='v', x=1.01, y=0.5,
                   bgcolor='rgba(0,0,0,0)',
                   font=dict(color=TEXT, size=11),
                   itemsizing='constant',
               ),
               'showlegend': True,
            }
        )

        return html.Div([
            dcc.Graph(figure=fig_donut, config={'displayModeBar': False}),
            dcc.Graph(figure=fig_abs, config={'displayModeBar': False}),
            dcc.Graph(figure=fig_pct, config={'displayModeBar': False}),
        ])
    except Exception as e:
        print(f"[_tab_sectores_evolution] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return html.Div([html.P(f"Error: {e}", style={'color': RED, 'fontFamily': 'monospace'})])


def _tab_sectores():
    """Contenedor de Sectores con subtab de Evolución y Gestionar."""
    return html.Div([
        dcc.Tabs(
            id='sectors-subtab',
            value='evolucion',
            style={'marginBottom': '14px'},
            children=[
                dcc.Tab(label='Evolución', value='evolucion', style=TAB_STYLE, selected_style=TAB_SELECTED),
                dcc.Tab(label='Gestionar Sectores', value='gestionar', style=TAB_STYLE, selected_style=TAB_SELECTED),
            ],
        ),
        html.Div(id='sectors-subtab-content'),
    ])


def _tab_cashflow():
    cf     = load_cashflow_evolution()
    events = load_cashflow_events()
    summ   = load_cashflow_summary()

    # ── Gráfico 1: evolución acumulada ─────────────────────────────────────────
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=cf['fecha'], y=cf['portfolio_usd'], name='Valor Portfolio',
        line=dict(color=YELLOW, width=2.5),
        hovertemplate='%{x|%d-%b-%y}<br>$%{y:,.0f}<extra>Portfolio</extra>',
    ))
    fig.add_trace(go.Scatter(
        x=cf['fecha'], y=cf['capital_neto'], name='Capital Neto (dep − ret)',
        line=dict(color=ACCENT, width=1.5, dash='dash'),
        hovertemplate='%{x|%d-%b-%y}<br>$%{y:,.0f}<extra>Capital neto</extra>',
    ))
    fig.add_trace(go.Scatter(
        x=cf['fecha'], y=cf['ganancia_usd'], name='Ganancia USD',
        line=dict(color=GREEN, width=2),
        fill='tozeroy', fillcolor='rgba(0,212,170,0.12)',
        hovertemplate='%{x|%d-%b-%y}<br>$%{y:,.0f}<extra>Ganancia</extra>',
    ))
    fig.add_hline(y=0, line_color=SUBTEXT, line_dash='dot', line_width=1)
    cf_min = pd.to_datetime(cf['fecha']).min() if not cf.empty else None
    cf_max = pd.to_datetime(cf['fecha']).max() if not cf.empty else None
    ev_min = pd.to_datetime(events['fecha']).min() if not events.empty else cf_min
    ev_max = pd.to_datetime(events['fecha']).max() if not events.empty else cf_max
    common_range = [min(cf_min, ev_min), max(cf_max, ev_max)] if cf_min is not None and cf_max is not None else None

    fig.update_layout(**PLOT_LAYOUT, title='Capital Neto vs Valor Portfolio vs Ganancia (USD)', height=380)
    fig.update_layout(margin=dict(l=55, r=150, t=45, b=40))
    if common_range:
        fig.update_xaxes(range=common_range)

    # ── Gráfico 2: timeline de entradas/salidas (bar chart) ──────────────────
    dep  = events[events['tipo_op'] == 'DEPOSITO']
    ext  = events[events['tipo_op'] == 'EXTRACCION']

    fig_bars = go.Figure()
    fig_bars.add_trace(go.Bar(
        x=dep['fecha'], y=dep['usd_equiv'],
        name='Ingreso / Capital',
        marker_color=ACCENT,
        hovertemplate='%{x|%d-%b-%y}<br><b>%{customdata}</b><br>$%{y:,.0f}<extra>Ingreso</extra>',
        customdata=dep['descripcion'],
    ))
    fig_bars.add_trace(go.Bar(
        x=ext['fecha'], y=ext['usd_equiv'],   # ya son negativos
        name='Extraccion',
        marker_color='rgba(255,107,107,0.85)',
        hovertemplate='%{x|%d-%b-%y}<br><b>%{customdata}</b><br>$%{y:,.0f}<extra>Extraccion</extra>',
        customdata=ext['descripcion'],
    ))
    fig_bars.add_hline(y=0, line_color=SUBTEXT, line_dash='dot', line_width=1)
    fig_bars.update_layout(
        **PLOT_LAYOUT,
        title='Timeline de Entradas / Salidas de Capital (USD)',
        height=300,
        barmode='overlay',
        bargap=0.3,
    )
    fig_bars.update_layout(margin=dict(l=55, r=150, t=45, b=40))
    if common_range:
        fig_bars.update_xaxes(range=common_range)

    # ── Tabla resumen ─────────────────────────────────────────────────────────
    TYPE_COLORS = {
        'DEPOSITO':        GREEN,
        'EXTRACCION':      RED,
    }
    # Fila de totales
    total_in  = summ.loc[summ['Tipo'] == 'DEPOSITO', 'Importe USD'].sum()
    total_out = summ.loc[summ['Tipo'] == 'EXTRACCION', 'Importe USD'].sum()
    total_net = total_in + total_out

    table = dash_table.DataTable(
        data=summ.to_dict('records'),
        columns=[
            {'name': 'Descripción', 'id': 'Descripción', 'type': 'text'},
            {'name': 'Tipo',         'id': 'Tipo',          'type': 'text'},
            {'name': 'Importe USD',  'id': 'Importe USD',   'type': 'numeric',
             'format': {'specifier': ',.2f'}},
        ],
        style_table={'overflowX': 'auto'},
        style_cell={'backgroundColor': CARD_BG, 'color': TEXT,
                    'border': f'1px solid {GRID}', 'padding': '8px 14px', 'fontSize': '13px'},
        style_header={'backgroundColor': PLOT_BG, 'color': ACCENT, 'fontWeight': '700',
                      'border': f'1px solid {GRID}'},
        style_data_conditional=[
            {'if': {'row_index': 'odd'}, 'backgroundColor': PLOT_BG},
            *[
                {'if': {'filter_query': f'{{Tipo}} = "{t}"', 'column_id': 'Importe USD'},
                 'color': c, 'fontWeight': '600'}
                for t, c in TYPE_COLORS.items()
            ],
        ],
        sort_action='native',
        page_size=20,
    )

    total_bar = html.Div([
        html.Span('Total ingresos:',  style={'color': SUBTEXT, 'marginRight': '6px', 'fontSize': '13px'}),
        html.Span(f'${total_in:,.0f}',  style={'color': ACCENT,  'fontWeight': '700', 'marginRight': '28px', 'fontSize': '14px'}),
        html.Span('Total salidas:',   style={'color': SUBTEXT, 'marginRight': '6px', 'fontSize': '13px'}),
        html.Span(f'${total_out:,.0f}', style={'color': RED,    'fontWeight': '700', 'marginRight': '28px', 'fontSize': '14px'}),
        html.Span('Capital neto:',    style={'color': SUBTEXT, 'marginRight': '6px', 'fontSize': '13px'}),
        html.Span(f'${total_net:,.0f}', style={'color': GREEN,  'fontWeight': '700', 'fontSize': '14px'}),
    ], style={'padding': '12px 4px 8px 4px'})

    return html.Div([
        dcc.Graph(figure=fig,      config={'displayModeBar': False}),
        dcc.Graph(figure=fig_bars, config={'displayModeBar': False}),
        total_bar,
        table,
    ])


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Portfolio Dashboard")
    parser.add_argument('--port',       type=int, default=8050)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: DB no encontrada en {DB_PATH}")
        print("Ejecutá primero: python etl.py")
        return

    print(f"\n  Portfolio Dashboard")
    print(f"  URL  : http://localhost:{args.port}")
    print(f"  DB   : {DB_PATH}")
    print(f"  Ctrl+C para detener\n")
    print(f"  Tableau 2026.2: Conectar → DuckDB → {DB_PATH}\n")

    app.run(debug=False, port=args.port, host='127.0.0.1')


if __name__ == '__main__':
    main()

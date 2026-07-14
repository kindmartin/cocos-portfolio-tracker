"""
setup_db.py — Crea el schema DuckDB para análisis de portfolio.
Uso:
  python setup_db.py           # crear schema (no borra datos)
  python setup_db.py --reset   # borrar todo y recrear
"""
import argparse
from pathlib import Path
import duckdb

# Detectar ruta base (funciona en .exe y script)
import sys
if getattr(sys, 'frozen', False):
    _base_dir = Path(sys.executable).parent
else:
    _base_dir = Path(__file__).parent
    if _base_dir.name == "code":
        _base_dir = _base_dir.parent

DB_PATH = _base_dir / "data" / "db" / "portfolio.duckdb"

DDL_TABLES = """
-- ============================================================
-- TABLAS CORE
-- ============================================================

CREATE TABLE IF NOT EXISTS instruments (
    ticker       VARCHAR PRIMARY KEY,
    nombre       VARCHAR,
    tipo         VARCHAR,       -- ACCION_ARG | CEDEAR | BONO_USD | BONO_ARS | LETRA_ARS | CASH | MEP | OTRO
    moneda_base  VARCHAR,       -- ARS | USD
    mercado      VARCHAR,
    activo       BOOLEAN DEFAULT TRUE
);

-- Snapshot semanal del portfolio (un row por instrumento por fecha)
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_date DATE    NOT NULL,
    ticker        VARCHAR NOT NULL,
    cantidad      DOUBLE,
    precio        DOUBLE,       -- en ARS (tal como viene del CSV)
    moneda        VARCHAR,      -- moneda del total_raw (ARS | USD | EXT)
    total_raw     DOUBLE,       -- total en moneda nativa
    PRIMARY KEY (snapshot_date, ticker)
);

-- Movimientos de cuenta (transacciones)
CREATE TABLE IF NOT EXISTS transactions (
    id              BIGINT PRIMARY KEY,
    fecha_op        DATE,
    fecha_liq       DATE,
    nro_ticket      VARCHAR,
    nro_comprobante VARCHAR,
    ticker          VARCHAR,
    instrumento_raw VARCHAR,
    tipo_op         VARCHAR,    -- COMPRA | VENTA | DIVIDENDO | MEP_BONO_ARS | MEP_BONO_USD | MEP_COMPRA_USD | MEP_VENTA_USD | DEPOSITO | EXTRACCION | AJUSTE | OTRO
    tipo_op_raw     VARCHAR,    -- string original del CSV
    moneda          VARCHAR,
    mercado         VARCHAR,
    cantidad        DOUBLE,
    precio          DOUBLE,
    monto_bruto     DOUBLE,
    comision        DOUBLE,
    iva             DOUBLE,
    total           DOUBLE
);

-- Tipos de cambio (CCL, MEP, oficial, blue)
CREATE TABLE IF NOT EXISTS fx_rates (
    fecha   DATE    NOT NULL,
    par     VARCHAR NOT NULL,   -- USD_ARS | MEP_BONO | CCL_CEDEAR | EXT_ARS
    tasa    DOUBLE,             -- cuántos ARS vale 1 unidad de moneda extranjera
    fuente  VARCHAR,            -- MEP_DERIVADO | MANUAL | BCRA | CCL
    PRIMARY KEY (fecha, par)
);

-- Escenarios what-if
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id  BIGINT PRIMARY KEY,
    nombre       VARCHAR NOT NULL,
    fecha_base   DATE    NOT NULL,
    descripcion  VARCHAR,
    created_at   TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS scenario_overrides (
    scenario_id        BIGINT  NOT NULL,
    ticker             VARCHAR NOT NULL,
    cantidad_override  DOUBLE,           -- NULL = usar posición actual
    precio_pct_change  DOUBLE,           -- % sobre precio base (ej: -20 = bajar 20%)
    PRIMARY KEY (scenario_id, ticker)
);

-- ============================================================
-- SECUENCIAS
-- ============================================================
CREATE SEQUENCE IF NOT EXISTS seq_tx_id     START 1;
CREATE SEQUENCE IF NOT EXISTS seq_sc_id     START 1;

-- ============================================================
-- INDICES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_snap_date   ON snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_snap_ticker ON snapshots(ticker);
CREATE INDEX IF NOT EXISTS idx_tx_fecha    ON transactions(fecha_op);
CREATE INDEX IF NOT EXISTS idx_tx_ticker   ON transactions(ticker);
CREATE INDEX IF NOT EXISTS idx_fx_fecha    ON fx_rates(fecha);

-- Historia de portfolio externa (pre-CSV: importada desde Excel u otras fuentes)
-- ID -1 en transactions se reserva para el DEPOSITO de capital inicial.
CREATE TABLE IF NOT EXISTS portfolio_history (
    fecha     DATE    NOT NULL PRIMARY KEY,
    total_usd DOUBLE,
    total_ars DOUBLE,
    ccl       DOUBLE,
    fuente    VARCHAR DEFAULT 'EXCEL',
    notas     VARCHAR
);

-- ============================================================
-- GESTIÓN DE SECTORES
-- ============================================================

-- Catálogo de sectores disponibles
CREATE TABLE IF NOT EXISTS sector_list (
    sector_id   INTEGER PRIMARY KEY,
    sector_name VARCHAR NOT NULL UNIQUE,
    color       VARCHAR DEFAULT '#808080',  -- color para visualización
    created_at  TIMESTAMP DEFAULT current_timestamp
);

-- Asignación de sectores a instrumentos (n a 1: un instrumento puede pertenecer a un sector)
CREATE TABLE IF NOT EXISTS instrument_sectors (
    ticker      VARCHAR PRIMARY KEY,
    sector_id   INTEGER,
    assigned_at TIMESTAMP DEFAULT current_timestamp,
    FOREIGN KEY (ticker) REFERENCES instruments(ticker),
    FOREIGN KEY (sector_id) REFERENCES sector_list(sector_id)
);

CREATE INDEX IF NOT EXISTS idx_inst_sector ON instrument_sectors(sector_id);
"""

DDL_VIEWS = """
-- ============================================================
-- VISTAS
-- ============================================================

-- Tipo de cambio más reciente disponible para cada fecha del portfolio
-- Jerarquía: MEP_BONO (operación real propia) > MEP_DIARIO (serie argentinadatos.com) > USD_ARS (fallback)
CREATE OR REPLACE VIEW v_fx_by_date AS
WITH all_dates AS (
    SELECT DISTINCT snapshot_date AS fecha FROM snapshots
    UNION
    SELECT DISTINCT fecha_op      AS fecha FROM transactions WHERE fecha_op IS NOT NULL
)
SELECT
    d.fecha,
    COALESCE(
        (SELECT tasa FROM fx_rates WHERE par = 'MEP_BONO'   AND fecha <= d.fecha ORDER BY fecha DESC LIMIT 1),
        (SELECT tasa FROM fx_rates WHERE par = 'MEP_DIARIO' AND fecha <= d.fecha ORDER BY fecha DESC LIMIT 1),
        (SELECT tasa FROM fx_rates WHERE par = 'USD_ARS'    AND fecha <= d.fecha ORDER BY fecha DESC LIMIT 1)
    ) AS usd_ars
FROM all_dates d;

-- ─────────────────────────────────────────────────────────────
-- Posiciones con conversión a ARS y USD
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_positions AS
SELECT
    s.snapshot_date,
    s.ticker,
    COALESCE(i.nombre, s.ticker)  AS nombre,
    COALESCE(i.tipo, 'OTRO')       AS tipo,
    COALESCE(i.moneda_base, 'ARS') AS moneda_base,
    s.cantidad,
    s.precio,
    s.moneda,
    s.total_raw,
    fx.usd_ars,
    CASE
        WHEN s.moneda = 'ARS'           THEN s.total_raw
        WHEN s.moneda IN ('USD','EXT')  THEN s.total_raw * COALESCE(fx.usd_ars, 0)
        ELSE s.total_raw
    END AS total_ars,
    CASE
        WHEN s.moneda IN ('USD','EXT')              THEN s.total_raw
        WHEN s.moneda = 'ARS' AND fx.usd_ars > 0   THEN s.total_raw / fx.usd_ars
        ELSE NULL
    END AS total_usd
FROM snapshots s
LEFT JOIN instruments  i  ON s.ticker = i.ticker
LEFT JOIN v_fx_by_date fx ON fx.fecha  = s.snapshot_date;

-- ─────────────────────────────────────────────────────────────
-- Valor total del portfolio por fecha
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_portfolio_value AS
SELECT
    snapshot_date,
    ROUND(SUM(total_ars), 2)       AS total_ars,
    ROUND(SUM(total_usd), 2)       AS total_usd,
    COUNT(DISTINCT ticker)          AS n_instrumentos,
    MIN(usd_ars)                    AS usd_ars_rate
FROM v_positions
GROUP BY snapshot_date
ORDER BY snapshot_date;

-- ─────────────────────────────────────────────────────────────
-- Valor + retornos + drawdown
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_portfolio_returns AS
SELECT
    snapshot_date,
    total_ars,
    total_usd,
    usd_ars_rate,
    n_instrumentos,
    LAG(total_ars) OVER (ORDER BY snapshot_date) AS prev_total_ars,
    LAG(total_usd) OVER (ORDER BY snapshot_date) AS prev_total_usd,
    ROUND(
        (total_ars - LAG(total_ars) OVER (ORDER BY snapshot_date))
        / NULLIF(LAG(total_ars) OVER (ORDER BY snapshot_date), 0) * 100, 2
    ) AS ret_sem_ars_pct,
    ROUND(
        (total_usd - LAG(total_usd) OVER (ORDER BY snapshot_date))
        / NULLIF(LAG(total_usd) OVER (ORDER BY snapshot_date), 0) * 100, 2
    ) AS ret_sem_usd_pct,
    MAX(total_ars) OVER (ORDER BY snapshot_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS peak_ars,
    MAX(total_usd) OVER (ORDER BY snapshot_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS peak_usd,
    ROUND(
        (total_ars - MAX(total_ars) OVER (ORDER BY snapshot_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))
        / NULLIF(MAX(total_ars) OVER (ORDER BY snapshot_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 0) * 100, 2
    ) AS drawdown_ars_pct,
    ROUND(
        (total_usd - MAX(total_usd) OVER (ORDER BY snapshot_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))
        / NULLIF(MAX(total_usd) OVER (ORDER BY snapshot_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 0) * 100, 2
    ) AS drawdown_usd_pct
FROM v_portfolio_value;

-- ─────────────────────────────────────────────────────────────
-- Allocación por tipo por fecha
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_allocation AS
SELECT
    p.snapshot_date,
    COALESCE(p.tipo, 'SIN_CLASIFICAR')  AS tipo,
    COUNT(DISTINCT p.ticker)             AS n_instrumentos,
    ROUND(SUM(p.total_ars), 0)           AS total_ars,
    ROUND(SUM(p.total_usd), 2)           AS total_usd,
    ROUND(
        SUM(p.total_ars)
        / NULLIF(SUM(SUM(p.total_ars)) OVER (PARTITION BY p.snapshot_date), 0) * 100, 2
    ) AS pct_ars
FROM v_positions p
GROUP BY p.snapshot_date, p.tipo
ORDER BY p.snapshot_date, total_ars DESC;

-- ─────────────────────────────────────────────────────────────
-- Transacciones enriquecidas (con tipo de instrumento y FX)
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_transactions AS
SELECT
    t.id,
    t.fecha_op,
    t.fecha_liq,
    t.ticker,
    COALESCE(i.tipo, 'OTRO')  AS instrumento_tipo,
    t.instrumento_raw,
    t.tipo_op,
    t.tipo_op_raw,
    t.moneda,
    t.mercado,
    t.cantidad,
    t.precio,
    t.monto_bruto,
    t.comision,
    t.iva,
    t.total,
    fx.usd_ars
FROM transactions t
LEFT JOIN instruments  i  ON t.ticker  = i.ticker
LEFT JOIN v_fx_by_date fx ON fx.fecha  = t.fecha_op;

-- ─────────────────────────────────────────────────────────────
-- Costo promedio ponderado por instrumento (acumulado)
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_cost_basis AS
WITH ops AS (
    SELECT
        ticker,
        fecha_op,
        id,
        cantidad,
        ABS(total)                                    AS costo_op,
        SIGN(cantidad)                                AS direccion,
        moneda
    FROM transactions
    WHERE tipo_op IN ('COMPRA', 'VENTA')
      AND ticker IS NOT NULL
      AND ticker NOT IN ('ARS','USD','EXT')
),
running AS (
    SELECT
        ticker,
        fecha_op,
        id,
        cantidad,
        costo_op,
        direccion,
        moneda,
        SUM(cantidad)                                  OVER w AS qty_acumulada,
        SUM(CASE WHEN cantidad > 0 THEN costo_op ELSE 0 END) OVER w AS costo_compras_acum
    FROM ops
    WINDOW w AS (PARTITION BY ticker ORDER BY fecha_op, id ROWS UNBOUNDED PRECEDING)
)
SELECT
    ticker,
    fecha_op,
    cantidad                                          AS delta_qty,
    qty_acumulada,
    ROUND(costo_compras_acum, 2)                      AS costo_compras_acum,
    ROUND(costo_compras_acum / NULLIF(qty_acumulada, 0), 4) AS costo_promedio_unit,
    moneda
FROM running
WHERE qty_acumulada >= 0
ORDER BY ticker, fecha_op;

-- ─────────────────────────────────────────────────────────────
-- Escenarios what-if: aplicar overrides a un snapshot base
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_scenario_result AS
SELECT
    sc.scenario_id,
    sc.nombre                                                  AS escenario,
    sc.fecha_base,
    s.ticker,
    COALESCE(i.tipo, 'OTRO')                                   AS tipo,
    COALESCE(i.nombre, s.ticker)                               AS instrumento,
    COALESCE(so.cantidad_override, s.cantidad)                 AS cantidad,
    s.moneda,
    s.precio                                                    AS precio_base,
    s.precio * (1 + COALESCE(so.precio_pct_change, 0) / 100.0) AS precio_scenario,
    so.precio_pct_change                                        AS cambio_precio_pct,
    ROUND(
        COALESCE(so.cantidad_override, s.cantidad)
        * s.precio * (1 + COALESCE(so.precio_pct_change, 0) / 100.0),
    0) AS total_ars_scenario
FROM scenarios sc
JOIN  snapshots         s   ON  s.snapshot_date = sc.fecha_base
LEFT JOIN instruments   i   ON  i.ticker = s.ticker
LEFT JOIN scenario_overrides so ON so.scenario_id = sc.scenario_id
                               AND so.ticker      = s.ticker;

-- ─────────────────────────────────────────────────────────────
-- Vista unificada: pre-historia (Excel) + snapshots CSV
-- CSV tiene precedencia cuando la misma fecha existe en ambas.
-- ─────────────────────────────────────────────────────────────
-- Vista unificada: pre-historia (Excel) + snapshots CSV
-- REGLA: solo se usa Excel para fechas ANTERIORES al primer snapshot CSV.
-- Evita artefactos por valuaciones Excel con FX diferente al MEP real.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_portfolio_history_full AS
SELECT
    fecha,
    total_usd,
    total_ars,
    ccl,
    fuente,
    notas
FROM portfolio_history
WHERE fecha < COALESCE(
    (SELECT MIN(snapshot_date)::DATE FROM snapshots),
    '9999-12-31'::DATE
)

UNION ALL

SELECT
    snapshot_date::DATE  AS fecha,
    total_usd,
    total_ars,
    usd_ars_rate         AS ccl,
    'CSV'                AS fuente,
    NULL                 AS notas
FROM v_portfolio_returns

ORDER BY fecha;
"""


def create_schema(conn: duckdb.DuckDBPyConnection, reset: bool = False):
    if reset:
        for tbl in ['scenario_overrides', 'scenarios', 'fx_rates',
                    'transactions', 'snapshots', 'instruments',
                    'portfolio_history']:
            conn.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
        for seq in ['seq_tx_id', 'seq_sc_id']:
            conn.execute(f"DROP SEQUENCE IF EXISTS {seq}")
        print("  Schema reseteado.")
    conn.execute(DDL_TABLES)
    conn.execute(DDL_VIEWS)
    print("  Schema OK.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--db', default=str(DB_PATH))
    args = parser.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    create_schema(conn, reset=args.reset)
    conn.close()
    print(f"  DB: {db_path}")


if __name__ == '__main__':
    main()

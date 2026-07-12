"""
etl.py — ETL mejorado con manejo automático de archivos CSV para ingestión.

Uso:
  python etl.py                  # procesa CSV desde 'csv for ingest' y mueve a carpetas finales
  python etl.py --snapshots      # solo snapshots
  python etl.py --transactions   # solo transacciones
  python etl.py --force          # fuerza recarga aunque el mes/fecha ya exista
  python etl.py --reset          # borra todo y recarga desde cero
  python etl.py --fx-csv ARCHIVO # carga FX rates desde CSV
  python etl.py --db ruta        # usa DB alternativa
"""
import re
import argparse
import shutil
from pathlib import Path
from datetime import datetime

import pandas as pd
import duckdb

from setup_db import DB_PATH, create_schema
from ingest_logger import logger

# Detectar ruta base
_base_dir = Path(__file__).parent
if _base_dir.name == "code":
    _base_dir = _base_dir.parent

# Rutas de entrada y salida
INGEST_DIR = _base_dir / "csv for ingest"           # 📥 Nuevos CSVs para procesar
PROCESSED_DIR = _base_dir / "data" / "processed csv"  # ✅ CSVs procesados
SNAPSHOTS_DIR = PROCESSED_DIR / "snapshots"          # portfolio_report_YYYYMMDD.csv
TRANSACTIONS_DIR = PROCESSED_DIR / "transactions"    # movimientos_*.csv
ERRORS_DIR = _base_dir / "data" / "ingest_errors"    # ❌ CSVs con errores

# Crear directorios si no existen
INGEST_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
TRANSACTIONS_DIR.mkdir(parents=True, exist_ok=True)
ERRORS_DIR.mkdir(parents=True, exist_ok=True)

# ── Clasificación de instrumentos ────────────────────────────────────────────

CASH_TICKERS = frozenset({'ARS', 'USD', 'EXT'})

USD_BOND_TICKERS = frozenset({
    'AL29', 'AL30', 'GD29', 'GD30', 'GD35', 'AL35',
    'AE38', 'GD38', 'GD41', 'GD46', 'DICP', 'PARA',
})

MEP_TICKERS = frozenset({'T661O'})   # bonos usados como vehículo MEP


def parse_num(value) -> float:
    """Parsea número en formato argentino (coma como decimal, punto como miles)."""
    if pd.isna(value):
        return 0.0
    s = str(value).strip().replace(' ', '')
    if s in ('', '-', 'nan'):
        return 0.0
    if ',' in s:
        # Formato argentino explícito: 255.551,44 → 255551.44
        s = s.replace('.', '').replace(',', '.')
    elif re.match(r'^-?\d{1,3}(\.\d{3})+$', s) and not s.lstrip('-').startswith('0.'):
        # Sin coma pero con separador de miles: 600.000 → 600000, 40.537 → 40537
        # Excluye valores como 0.076 (precio fraccionario)
        s = s.replace('.', '')
    try:
        return float(s)
    except ValueError:
        return 0.0


def extract_ticker(instrumento: str) -> str | None:
    """Extrae el ticker del nombre del instrumento (está entre paréntesis al final o es solo el ticker)."""
    instrumento = str(instrumento).strip()
    if instrumento in CASH_TICKERS:
        return instrumento
    m = re.search(r'\(([A-Z0-9]+)\)\s*$', instrumento)
    if m and m.group(1):
        return m.group(1)
    # Si no hay paréntesis pero la string es solo un ticker válido, asúmelo como ticker
    if re.match(r'^[A-Z0-9]+$', instrumento):
        return instrumento
    return None


def classify_instrument(nombre: str, ticker: str | None) -> tuple[str, str]:
    """Retorna (tipo, moneda_base)."""
    if ticker in CASH_TICKERS:
        return ('CASH', 'USD' if ticker in ('USD', 'EXT') else 'ARS')
    if ticker in MEP_TICKERS:
        return ('MEP', 'ARS')
    if ticker in USD_BOND_TICKERS:
        return ('BONO_USD', 'USD')
    n = str(nombre).upper()
    if 'CEDEAR' in n:
        return ('CEDEAR', 'USD')
    if 'BONO' in n or 'BONOS' in n:
        if 'U$S' in n or 'USD' in n:
            return ('BONO_USD', 'USD')
        return ('BONO_ARS', 'ARS')
    if 'LETRA' in n or 'LECAP' in n or 'LECER' in n:
        return ('LETRA_ARS', 'ARS')
    if 'DÓLAR' in n or 'DOLAR' in n:
        return ('CASH', 'USD')
    return ('ACCION_ARG', 'ARS')


# ── Normalización de tipo de operación ───────────────────────────────────────

def normalize_tipo_op(raw: str) -> str:
    r = str(raw).lower().strip()
    if 'compra bono' in r and 'mep ars' in r:   return 'MEP_BONO_ARS'
    if 'venta bono'  in r and 'mep ars' in r:   return 'MEP_BONO_ARS'
    if 'compra bono' in r and 'mep usd' in r:   return 'MEP_BONO_USD'
    if 'venta bono'  in r and 'mep usd' in r:   return 'MEP_BONO_USD'
    if 'registracion' in r and 'ars' in r:      return 'MEP_BONO_ARS'
    if 'registracion' in r and 'usd' in r:      return 'MEP_BONO_USD'
    if 'compra dolar mep' in r:                 return 'MEP_COMPRA_USD'
    if 'venta dolar mep'  in r:                 return 'MEP_VENTA_USD'
    if 'compra' in r and 'mep' not in r:        return 'COMPRA'
    if 'venta'  in r and 'mep' not in r:        return 'VENTA'
    if 'dividend' in r:                         return 'DIVIDENDO'
    if 'recibo de cobro' in r:                  return 'DEPOSITO'
    if 'orden de pago' in r:                    return 'EXTRACCION'
    if 'conversion' in r or 'nota de credito' in r: return 'AJUSTE'
    return 'OTRO'


def detect_csv_type(filepath: Path) -> str | None:
    """
    Auto-detecta el tipo de CSV:
    - 'snapshot': tiene columna 'instrumento' y patrón portfolio_report_*.csv
    - 'transaction': tiene columna 'FechaEjecucion' y patrón movimientos_*.csv
    - None: no se pudo determinar
    
    IMPORTANTE: Prioridad por nombre de archivo para evitar confusiones.
    """
    filename = filepath.name.lower()
    
    # [1] PRIORIDAD: Detectar por nombre de archivo
    if 'movimiento' in filename:
        return 'transaction'
    elif 'portfolio_report' in filename and re.match(r'^portfolio_report_\d{8}\.csv$', filename):
        return 'snapshot'
    
    # [2] FALLBACK: Leer el archivo y detectar por columnas
    for sep in [';', ',', '\t']:
        try:
            candidate = pd.read_csv(filepath, sep=sep, encoding='utf-8-sig', dtype=str, nrows=5)
            cols = [c.strip().lower() for c in candidate.columns]
            
            # Detectar por columnas: primero transacción, luego snapshot
            if 'fechaejecucion' in cols or 'tipooperacion' in cols:
                return 'transaction'
            elif 'instrumento' in cols:
                return 'snapshot'
            
            break
        except Exception:
            continue
    
    return None


def get_portfolio_epoch() -> str:
    """Detecta dinámicamente la fecha de inicio del portfolio."""
    min_date = None
    
    for f in SNAPSHOTS_DIR.glob("portfolio_report_*.csv"):
        m = re.search(r'(\d{8})', f.name)
        if m:
            d = m.group(1)
            date_str = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            if min_date is None or date_str < min_date:
                min_date = date_str
    
    for f in TRANSACTIONS_DIR.glob("movimientos_*.csv"):
        try:
            df = pd.read_csv(f, sep=';', encoding='utf-8-sig', usecols=['FechaEjecucion'], dtype=str, nrows=10000)
            if 'FechaEjecucion' not in df.columns:
                df = pd.read_csv(f, sep=';', encoding='utf-8-sig', dtype=str, nrows=10000)
                cols_lower = {c: c.lower() for c in df.columns}
                df.rename(columns=cols_lower, inplace=True)
                if 'fechaejecucion' not in df.columns:
                    continue
            
            try:
                dates = pd.to_datetime(df['fechaejecucion'], format='%d-%m-%Y', errors='coerce')
                min_f = dates.min()
                if pd.notna(min_f):
                    date_str = min_f.strftime('%Y-%m-%d')
                    if min_date is None or date_str < min_date:
                        min_date = date_str
            except Exception:
                pass
        except Exception:
            pass
    
    if min_date is None:
        min_date = '2024-07-17'
    
    return min_date


# ── Snapshots ─────────────────────────────────────────────────────────────────

def load_snapshots(conn: duckdb.DuckDBPyConnection, force: bool = False) -> tuple[int, int, int]:
    """Carga snapshots desde SNAPSHOTS_DIR. Retorna (loaded, skipped, errors)."""
    snap_files = sorted(
        f for f in SNAPSHOTS_DIR.glob("portfolio_report_*.csv")
        if re.match(r'^portfolio_report_\d{8}\.csv$', f.name)
    )

    existing = set()
    if not force:
        rows = conn.execute(
            "SELECT DISTINCT CAST(snapshot_date AS VARCHAR) FROM snapshots"
        ).fetchall()
        existing = {r[0] for r in rows}

    loaded = skipped = errors = 0
    for f in snap_files:
        m = re.search(r'(\d{8})', f.name)
        if not m:
            continue
        d = m.group(1)
        date_str = f"{d[:4]}-{d[4:6]}-{d[6:8]}"

        if date_str in existing:
            skipped += 1
            continue

        try:
            df = _parse_snapshot(f, date_str)
            if df is None or df.empty:
                errors += 1
                continue

            for _, row in df.iterrows():
                conn.execute(
                    "INSERT INTO instruments (ticker, nombre, tipo, moneda_base) "
                    "VALUES (?,?,?,?) ON CONFLICT (ticker) DO NOTHING",
                    [row.ticker, row.nombre, row.tipo, row.moneda_base]
                )

            conn.executemany(
                "INSERT INTO snapshots "
                "(snapshot_date, ticker, cantidad, precio, moneda, total_raw) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT (snapshot_date, ticker) DO UPDATE SET "
                "cantidad=excluded.cantidad, precio=excluded.precio, "
                "moneda=excluded.moneda, total_raw=excluded.total_raw",
                df[['snapshot_date', 'ticker', 'cantidad', 'precio', 'moneda', 'total_raw']].values.tolist()
            )
            loaded += 1
        except Exception as e:
            print(f"    ERROR {f.name}: {e}")
            errors += 1

    return loaded, skipped, errors


def _parse_snapshot(filepath: Path, date_str: str) -> pd.DataFrame | None:
    df = None
    for sep in [';', '\t', ',']:
        try:
            candidate = pd.read_csv(
                filepath, sep=sep, encoding='utf-8-sig', dtype=str
            )
            cols = [c.strip().lower() for c in candidate.columns]
            if 'instrumento' in cols:
                candidate.columns = cols
                df = candidate
                break
        except Exception:
            continue

    if df is None or 'instrumento' not in df.columns:
        return None

    df['instrumento'] = df['instrumento'].fillna('').str.strip()
    df['cantidad_f']  = df.get('cantidad', pd.Series(['0'] * len(df))).apply(parse_num)
    df['precio_f']    = df.get('precio',   pd.Series(['0'] * len(df))).apply(parse_num)
    df['total_f']     = df.get('total',    pd.Series(['0'] * len(df))).apply(parse_num)
    df['ticker']      = df['instrumento'].apply(extract_ticker)

    # Descartar filas sin ticker
    df = df[df['ticker'].notna() & (df['ticker'] != '')]
    # Descartar solo si precio=0 Y total=0 Y cantidad=0 (derechos/basura)
    # Mantener posiciones reales con precio=0 pero cantidad>0 (bonos sin precio publicado)
    df = df[~(
        (df['precio_f'] == 0) &
        (df['total_f']  == 0) &
        (df['cantidad_f'] == 0) &
        (~df['ticker'].isin(CASH_TICKERS))
    )]

    if df.empty:
        return None

    classif = df.apply(
        lambda r: pd.Series(
            classify_instrument(r['instrumento'], r['ticker']),
            index=['tipo', 'moneda_base']
        ), axis=1
    )
    df = pd.concat([df, classif], axis=1)

    moneda = df.get('moneda', pd.Series(['ARS'] * len(df)))
    moneda = moneda.fillna('ARS').str.strip().replace('0', 'ARS')

    return pd.DataFrame({
        'snapshot_date': date_str,
        'ticker':        df['ticker'],
        'nombre':        df['instrumento'],
        'tipo':          df['tipo'],
        'moneda_base':   df['moneda_base'],
        'cantidad':      df['cantidad_f'],
        'precio':        df['precio_f'],
        'moneda':        moneda,
        'total_raw':     df['total_f'],
    }).reset_index(drop=True)


# ── Transacciones ─────────────────────────────────────────────────────────────

def load_transactions(conn: duckdb.DuckDBPyConnection, force: bool = False) -> tuple[int, int, int]:
    """Carga transacciones desde TRANSACTIONS_DIR. Retorna (loaded, skipped, errors)."""
    mov_files = sorted(TRANSACTIONS_DIR.glob("movimientos_*.csv"))

    existing_periods = set()
    if not force:
        rows = conn.execute(
            "SELECT DISTINCT LEFT(CAST(fecha_op AS VARCHAR), 7) FROM transactions"
        ).fetchall()
        existing_periods = {r[0] for r in rows}

    loaded = skipped = errors = 0
    for f in mov_files:
        months_in_file = _extract_transaction_months_from_file(f)
        if not force and months_in_file and set(months_in_file).issubset(existing_periods):
            skipped += 1
            continue

        try:
            n = _load_transaction_file(conn, f)
            loaded += 1
        except Exception as e:
            print(f"    ERROR {f.name}: {e}")
            errors += 1

    return loaded, skipped, errors


def _extract_transaction_months_from_file(filepath: Path) -> list[str]:
    """Extrae meses YYYY-MM presentes en un CSV de movimientos para controlar recargas idempotentes."""
    try:
        df = pd.read_csv(filepath, sep=';', encoding='utf-8-sig', dtype=str, usecols=['FechaEjecucion'])
    except Exception:
        try:
            df = pd.read_csv(filepath, sep=';', encoding='utf-8-sig', dtype=str)
        except Exception:
            return []

    cols = {c.lower(): c for c in df.columns}
    src_col = cols.get('fechaejecucion')
    if not src_col:
        return []

    dates = pd.to_datetime(df[src_col], format='%d-%m-%Y', errors='coerce')
    months = sorted({d.strftime('%Y-%m') for d in dates.dropna()})
    return months


def _load_transaction_file(conn: duckdb.DuckDBPyConnection, filepath: Path) -> int:
    if filepath.stat().st_size == 0:
        return 0

    df = pd.read_csv(filepath, sep=';', encoding='utf-8-sig', dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]

    # Parsear fechas
    for col_name in ['fechaejecucion', 'fechaliquidacion']:
        if col_name in df.columns:
            df[col_name] = pd.to_datetime(
                df[col_name], format='%d-%m-%Y', errors='coerce'
            )

    df = df[df.get('fechaejecucion', pd.Series([pd.NaT] * len(df))).notna()]
    if df.empty:
        return 0

    # Parsear numéricos
    for col in ['cantidad', 'precio', 'montobruto', 'comision', 'ddmm', 'iva', 'otros', 'total']:
        if col in df.columns:
            df[col] = df[col].apply(parse_num)

    df['instrumento_raw'] = df.get('instrumento', pd.Series(['']*len(df))).fillna('').str.strip()
    df['ticker']    = df['instrumento_raw'].apply(extract_ticker)
    df['tipo_op']   = df.get('tipooperacion', pd.Series(['OTRO']*len(df))).apply(normalize_tipo_op)
    df['tipo_raw']  = df.get('tipooperacion', pd.Series(['']*len(df))).fillna('')
    df['moneda']    = df.get('moneda',   pd.Series(['ARS']*len(df))).fillna('ARS').str.strip()
    df['mercado']   = df.get('mercado',  pd.Series(['']*len(df))).fillna('')

    # Eliminar rows existentes del mismo período para re-carga idempotente
    min_d = df['fechaejecucion'].min().date()
    max_d = df['fechaejecucion'].max().date()
    conn.execute(
        "DELETE FROM transactions WHERE fecha_op BETWEEN ? AND ?",
        [str(min_d), str(max_d)]
    )

    rows = []
    for _, r in df.iterrows():
        rows.append([
            str(r['fechaejecucion'].date())   if pd.notna(r.get('fechaejecucion'))  else None,
            str(r['fechaliquidacion'].date())  if pd.notna(r.get('fechaliquidacion')) and 'fechaliquidacion' in r else None,
            str(r.get('nroticket', '') or '').strip() or None,
            str(r.get('nrocomprobante', '') or '').strip() or None,
            r['ticker'],
            r['instrumento_raw'] or None,
            r['tipo_op'],
            r['tipo_raw'] or None,
            r['moneda'],
            r['mercado'] or None,
            float(r.get('cantidad',    0) or 0),
            float(r.get('precio',      0) or 0),
            float(r.get('montobruto',  0) or 0),
            float(r.get('comision',    0) or 0),
            float(r.get('iva',         0) or 0),
            float(r.get('total',       0) or 0),
        ])

    if rows:
        conn.executemany(
            "INSERT INTO transactions "
            "(id, fecha_op, fecha_liq, nro_ticket, nro_comprobante, "
            " ticker, instrumento_raw, tipo_op, tipo_op_raw, "
            " moneda, mercado, cantidad, precio, "
            " monto_bruto, comision, iva, total) "
            "VALUES (nextval('seq_tx_id'),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows
        )

    # Registrar nuevos tickers en instruments
    for _, r in df[df['ticker'].notna()].iterrows():
        t = r['ticker']
        if t not in CASH_TICKERS:
            tipo, moneda_base = classify_instrument(r['instrumento_raw'], t)
            conn.execute(
                "INSERT INTO instruments (ticker, nombre, tipo, moneda_base) "
                "VALUES (?,?,?,?) ON CONFLICT (ticker) DO NOTHING",
                [t, r['instrumento_raw'], tipo, moneda_base]
            )

    return len(rows)


def _derive_fx_from_mep(conn: duckdb.DuckDBPyConnection) -> int:
    """
    Deriva tipos de cambio ARS/USD desde dos fuentes y guarda tres pares:
    - MEP_BONO   : tasa real de operaciones con T661O (dólar MEP puro).
    - CCL_CEDEAR : tasa implícita de CEDEARs/acciones (ARS snapshot / USD tx).
    - USD_ARS    : compuesto; prefiere MEP_BONO cuando disponible, sino CCL_CEDEAR.
    """
    CCL_MIN, CCL_MAX = 500.0, 5000.0
    mep_bono_rates:   dict[str, list[float]] = {}
    ccl_cedear_rates: dict[str, list[float]] = {}

    # ── Fuente 1: T661O → MEP_BONO ───────────────────────────────────────────
    # Emparejar cada fila ARS con su fila USD por cantidad (misma sesión)
    t661o = conn.execute("""
        WITH ops AS (
            SELECT fecha_op,
                   ROUND(ABS(cantidad), 3) AS qty,
                   tipo_op, moneda,
                   ABS(total) AS monto
            FROM transactions
            WHERE ticker = 'T661O'
              AND tipo_op IN ('MEP_BONO_ARS', 'MEP_BONO_USD')
              AND ABS(total) > 0
        )
        SELECT a.fecha_op,
               ROUND(a.monto / u.monto, 2) AS tasa
        FROM ops a
        JOIN ops u ON a.fecha_op = u.fecha_op
                   AND a.qty    = u.qty
        WHERE a.tipo_op = 'MEP_BONO_ARS' AND a.moneda = 'ARS'
          AND u.tipo_op = 'MEP_BONO_USD' AND u.moneda = 'USD'
          AND u.monto > 0
    """).fetchall()

    for fecha, tasa in t661o:
        if CCL_MIN < tasa < CCL_MAX:
            mep_bono_rates.setdefault(str(fecha), []).append(tasa)

    # ── Fuente 2: CEDEARs/acciones → CCL_CEDEAR ──────────────────────────────
    # precio_ars del snapshot más cercano / precio_usd_por_accion de la tx
    stock_mep = conn.execute("""
        WITH tx AS (
            SELECT t.fecha_op,
                   t.ticker,
                   ABS(t.cantidad)              AS qty,
                   ABS(t.total)                 AS usd_total
            FROM transactions t
            WHERE t.tipo_op IN ('MEP_COMPRA_USD', 'MEP_VENTA_USD')
              AND t.moneda   = 'USD'
              AND ABS(t.cantidad) > 0.001
              AND ABS(t.total)    > 5
        ),
        nearest_snap AS (
            SELECT t.fecha_op, t.ticker, t.qty, t.usd_total,
                   s.precio AS ars_precio,
                   ROW_NUMBER() OVER (
                       PARTITION BY t.fecha_op, t.ticker
                       ORDER BY ABS(s.snapshot_date - t.fecha_op)
                   ) AS rn
            FROM tx t
            JOIN snapshots s ON s.ticker = t.ticker
                             AND s.precio > 0
        )
        SELECT fecha_op,
               ROUND((qty * ars_precio) / usd_total, 2) AS tasa
        FROM nearest_snap
        WHERE rn = 1
          AND usd_total > 0
    """).fetchall()

    for fecha, tasa in stock_mep:
        if CCL_MIN < tasa < CCL_MAX:
            ccl_cedear_rates.setdefault(str(fecha), []).append(tasa)

    def _median(vals: list[float]) -> float:
        s = sorted(vals); n = len(s)
        return s[n // 2] if n % 2 else (s[n//2-1] + s[n//2]) / 2

    saved = 0

    # ── Guardar MEP_BONO ─────────────────────────────────────────────────────
    for fecha_str, vals in mep_bono_rates.items():
        conn.execute(
            "INSERT INTO fx_rates (fecha, par, tasa, fuente) "
            "VALUES (?, 'MEP_BONO', ?, 'MEP_BONO') "
            "ON CONFLICT (fecha, par) DO UPDATE SET tasa=excluded.tasa, fuente=excluded.fuente",
            [fecha_str, round(_median(vals), 2)]
        )
        saved += 1

    # ── Guardar CCL_CEDEAR ───────────────────────────────────────────────────
    for fecha_str, vals in ccl_cedear_rates.items():
        conn.execute(
            "INSERT INTO fx_rates (fecha, par, tasa, fuente) "
            "VALUES (?, 'CCL_CEDEAR', ?, 'CCL_CEDEAR') "
            "ON CONFLICT (fecha, par) DO UPDATE SET tasa=excluded.tasa, fuente=excluded.fuente",
            [fecha_str, round(_median(vals), 2)]
        )
        saved += 1

    # ── Guardar USD_ARS compuesto (MEP_BONO si disponible, sino CCL_CEDEAR) ──
    all_dates = set(mep_bono_rates.keys()) | set(ccl_cedear_rates.keys())
    for fecha_str in all_dates:
        rate = round(_median(mep_bono_rates[fecha_str] if fecha_str in mep_bono_rates
                             else ccl_cedear_rates[fecha_str]), 2)
        conn.execute(
            "INSERT INTO fx_rates (fecha, par, tasa, fuente) "
            "VALUES (?, 'USD_ARS', ?, 'MEP_DERIVADO') "
            "ON CONFLICT (fecha, par) DO UPDATE SET tasa=excluded.tasa, fuente=excluded.fuente",
            [fecha_str, rate]
        )
        saved += 1

    return saved


def load_fx_csv(conn: duckdb.DuckDBPyConnection, filepath: Path) -> int:
    """
    Carga tipos de cambio ARS/USD desde un CSV externo.
    Formatos aceptados:
      fecha;tasa           (sep=; decimal=,)
      fecha,tasa           (sep=, decimal=.)
    La columna 'fecha' puede llamarse: fecha, date, Fecha, Date.
    La columna 'tasa' puede llamarse:  tasa, ccl, usd_ars, rate, Rate, CCL.
    """
    for sep in [';', ',']:
        try:
            df = pd.read_csv(filepath, sep=sep, encoding='utf-8-sig', dtype=str)
            df.columns = [c.strip().lower() for c in df.columns]
            if any(c in df.columns for c in ['fecha', 'date']):
                break
        except Exception:
            continue
    else:
        raise ValueError(f"No se pudo leer {filepath}")

    col_fecha = next((c for c in df.columns if c in ('fecha', 'date')), None)
    if col_fecha is None:
        raise ValueError(f"No se encontró columna de fecha en {filepath}. Columnas: {list(df.columns)}")
    # Buscar columna de tasa: nombres exactos conocidos, luego startswith, luego primera numérica
    _RATE_NAMES = ('tasa', 'ccl', 'usd_ars', 'rate', 'cierre', 'ultimo', 'close', 'last', 'valor')
    col_tasa = next((c for c in df.columns if c in _RATE_NAMES), None)
    if col_tasa is None:
        col_tasa = next((c for c in df.columns if any(c.startswith(n) for n in _RATE_NAMES)), None)
    if col_tasa is None:
        # último recurso: primera columna no-fecha con datos numéricos
        for c in df.columns:
            if c == col_fecha:
                continue
            try:
                pd.to_numeric(df[c].apply(parse_num))
                col_tasa = c
                break
            except Exception:
                continue
    if col_tasa is None:
        raise ValueError(f"No se encontró columna de tasa en {filepath}. Columnas: {list(df.columns)}")

    df['_fecha'] = pd.to_datetime(df[col_fecha], dayfirst=True, errors='coerce')
    df['_tasa']  = df[col_tasa].apply(parse_num)
    df = df[df['_fecha'].notna() & (df['_tasa'] > 0)]

    loaded = 0
    for _, row in df.iterrows():
        conn.execute(
            "INSERT INTO fx_rates (fecha, par, tasa, fuente) "
            "VALUES (?, 'USD_ARS', ?, 'CSV_MANUAL') "
            "ON CONFLICT (fecha, par) DO UPDATE SET tasa=excluded.tasa, fuente=excluded.fuente",
            [str(row['_fecha'].date()), float(row['_tasa'])]
        )
        loaded += 1
    return loaded


def process_ingest_folder(conn: duckdb.DuckDBPyConnection, force: bool = False) -> None:
    """
    Procesa CSVs en 'csv for ingest':
    - Auto-detecta tipo (snapshot vs transaction)
    - Mueve a carpeta correcta después de procesar
    - Si hay error, mueve a ingest_errors
    """
    csv_files = sorted(INGEST_DIR.glob("*.csv"))
    
    if not csv_files:
        print("  (no hay archivos en 'csv for ingest')")
        logger.log_event("(sistema)", "detect", "No se encontraron archivos en csv for ingest")
        return
    
    snapshots_to_load = []
    transactions_to_load = []
    
    for csv_file in csv_files:
        try:
            csv_type = detect_csv_type(csv_file)
            logger.log_event(csv_file.name, "detect", f"Detectado como {csv_type}")
            
            if csv_type == 'snapshot':
                snapshots_to_load.append(csv_file)
            elif csv_type == 'transaction':
                transactions_to_load.append(csv_file)
            else:
                # No se pudo detectar
                shutil.move(str(csv_file), str(ERRORS_DIR / csv_file.name))
                error_file = ERRORS_DIR / f"{csv_file.name}.error"
                with open(error_file, 'w') as f:
                    f.write(f"No se pudo detectar tipo de CSV: {csv_file.name}\n")
                logger.log_event(csv_file.name, "error", "Tipo desconocido -> ingest_errors")
                print(f"    [ERROR] {csv_file.name}: tipo desconocido -> ingest_errors")
                continue
            
            print(f"    [OK] {csv_file.name}: detectado como {csv_type}")
        
        except Exception as e:
            # Error durante detección
            shutil.move(str(csv_file), str(ERRORS_DIR / csv_file.name))
            error_file = ERRORS_DIR / f"{csv_file.name}.error"
            with open(error_file, 'w') as f:
                f.write(f"Error detectando tipo: {str(e)}\n")
            logger.log_event(csv_file.name, "error", f"Error detectando tipo: {str(e)}")
            print(f"    [FAIL] {csv_file.name}: error -> ingest_errors")
    
    # Mover snapshots detectados a snapshots_dir
    for f in snapshots_to_load:
        dest = SNAPSHOTS_DIR / f.name
        if not dest.exists():
            shutil.move(str(f), str(dest))
            logger.log_event(f.name, "move", "Movido a snapshots/")
            print(f"    -> {f.name} movido a snapshots/")
        else:
            logger.log_event(f.name, "error", "Ya existe en snapshots/ - omitido")
            print(f"    [SKIP] {f.name} ya existe en snapshots/, omitiendo")
    
    # Mover transactions detectadas a transactions_dir
    for f in transactions_to_load:
        dest = TRANSACTIONS_DIR / f.name
        if not dest.exists():
            shutil.move(str(f), str(dest))
            logger.log_event(f.name, "move", "Movido a transactions/")
            print(f"    -> {f.name} movido a transactions/")
        else:
            logger.log_event(f.name, "error", "Ya existe en transactions/ - omitido")
            print(f"    [SKIP] {f.name} ya existe en transactions/, omitiendo")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ETL: carga datos en la DB de portfolio")
    parser.add_argument('--snapshots',    action='store_true', help='Solo snapshots')
    parser.add_argument('--transactions', action='store_true', help='Solo transacciones (movimientos)')
    parser.add_argument('--force',        action='store_true', help='Fuerza recarga aunque el mes ya exista')
    parser.add_argument('--reset',        action='store_true', help='Borra y recarga todo')
    parser.add_argument('--fx-csv',       default=None, metavar='ARCHIVO.csv',
                        help='Carga FX rates ARS/USD desde CSV (fecha;tasa)')
    parser.add_argument('--db',           default=str(DB_PATH))
    args = parser.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    create_schema(conn, reset=args.reset)

    do_all = not args.snapshots and not args.transactions and not args.fx_csv
    force  = args.reset or args.force

    # Iniciar sesión de logging
    session_id = logger.start_session()
    print(f"\n[LOG] Sesion: {session_id}\n")

    print("\n> Procesando 'csv for ingest'...")
    process_ingest_folder(conn, force=force)

    if do_all or args.snapshots:
        print("\n> Cargando snapshots...")
        loaded, skipped, errors = load_snapshots(conn, force=force)
        print(f"  Snapshots: {loaded} cargados, {skipped} ya existían, {errors} errores")
        logger.log_event("(snapshots)", "load", f"{loaded} cargados, {skipped} ya existían, {errors} errores")

    if do_all or args.transactions:
        print("\n> Cargando transacciones...")
        loaded, skipped, errors = load_transactions(conn, force=force)
        print(f"  Transacciones: {loaded} cargados, {skipped} ya existían, {errors} errores")
        logger.log_event("(transacciones)", "load", f"{loaded} cargados, {skipped} ya existían, {errors} errores")
        
        # Derivar FX rates desde MEP
        n_fx = _derive_fx_from_mep(conn)
        if n_fx:
            print(f"  FX rates derivadas de MEP T661O: {n_fx} fechas")
            logger.log_event("(fx_rates)", "load", f"{n_fx} FX rates derivadas")

    if args.fx_csv:
        print(f"\n> Cargando FX rates desde {args.fx_csv}...")
        n = load_fx_csv(conn, Path(args.fx_csv))
        print(f"  FX rates cargadas: {n}")
        logger.log_event("(fx_csv)", "load", f"{n} FX rates cargadas")

    # Resumen final
    n_snap  = conn.execute("SELECT COUNT(DISTINCT snapshot_date) FROM snapshots").fetchone()[0]
    n_pos   = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    n_tx    = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    n_inst  = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
    n_fx    = conn.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0]

    print(f"\n{'='*50}")
    print(f"DB             : {db_path}")
    print(f"Snapshots      : {n_snap} fechas  |  {n_pos} posiciones")
    print(f"Transacciones  : {n_tx}")
    print(f"Instrumentos   : {n_inst}")
    print(f"FX rates       : {n_fx}")
    print(f"{'='*50}")
    
    # Finalizar sesión con resumen
    status = "success" if errors == 0 else "partial"
    session_summary = logger.end_session(status)
    print(f"\n[SUCCESS] Resumen: {session_summary['files_success']} exitosos, {session_summary['files_error']} errores")
    
    conn.close()


if __name__ == '__main__':
    main()

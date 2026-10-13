"""Acceso a PostgreSQL (Render).

- La URL se toma de DATABASE_URL (variable de entorno o st.secrets) o de DEFAULT_DATABASE_URL.
- Render exige SSL en conexiones externas: se fuerza sslmode=require.
- Pool de conexiones con keepalives, verificación de conexiones ociosas y
  reintentos. Esto evita el error "SSL connection has been closed unexpectedly"
  y que se acumulen conexiones abiertas (el plan gratuito tiene muy pocas).
- Las fechas se guardan como hora local "de pared" (Argentina). La sesión se fija
  en UTC para que Postgres no aplique conversiones de zona horaria.
"""
import os
import time
from contextlib import contextmanager

import psycopg2
import streamlit as st
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor

# Si existe la variable DATABASE_URL (o el secret), tiene prioridad sobre esta URL.
DEFAULT_DATABASE_URL = (
    "postgresql://bella:y5eg7N4rtj4uH5CR3lAogmzkq9MGvHXF"
    "@dpg-db740he7bikc73a3oeqg-a.virginia-postgres.render.com/belladb_i62l"
)

_BROKEN = (psycopg2.OperationalError, psycopg2.InterfaceError)
_IDLE_CHECK_SECONDS = 60
_last_used = {}


class DBError(RuntimeError):
    """Error de base de datos con un mensaje apto para mostrar en pantalla."""


def database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            url = st.secrets.get("DATABASE_URL")
        except Exception:  # no existe secrets.toml
            url = None
    return url or DEFAULT_DATABASE_URL


def _friendly(error):
    detail = (str(error).strip().splitlines() or [error.__class__.__name__])[0]
    if isinstance(error, _BROKEN):
        return (
            "No se pudo conectar con la base de datos de Render. Verificá que la base esté "
            "activa en el panel de Render (las bases gratuitas vencen) y que DATABASE_URL "
            f"sea la *External Database URL*. Detalle: {detail}"
        )
    return detail


@st.cache_resource(show_spinner=False)
def _pool():
    url = database_url()
    if not url:
        raise DBError(
            "Falta configurar DATABASE_URL (variable de entorno o .streamlit/secrets.toml)."
        )
    return pg_pool.ThreadedConnectionPool(
        0,
        8,
        url,
        sslmode=os.environ.get("DB_SSLMODE", "require"),
        connect_timeout=10,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
        application_name="bella-app",
        options="-c timezone=UTC",
    )


def _discard(pool, conn):
    _last_used.pop(id(conn), None)
    try:
        pool.putconn(conn, close=True)
    except Exception:
        pass


def _is_alive(conn):
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.rollback()
        return True
    except _BROKEN:
        return False


def _checkout(pool, attempts=3):
    error = None
    for attempt in range(attempts):
        conn = None
        try:
            conn = pool.getconn()
            last = _last_used.get(id(conn))
            idle = last is not None and time.monotonic() - last > _IDLE_CHECK_SECONDS
            if conn.closed or (idle and not _is_alive(conn)):
                raise psycopg2.OperationalError("la conexión estaba cerrada")
            return conn
        except _BROKEN as e:
            error = e
            if conn is not None:
                _discard(pool, conn)
            time.sleep(0.5 * (attempt + 1))
        except pg_pool.PoolError as e:
            raise DBError("Hay demasiadas conexiones abiertas. Probá de nuevo en unos segundos.") from e
    raise DBError(_friendly(error)) from error


@contextmanager
def _connection():
    pool = _pool()
    conn = _checkout(pool)
    broken = False
    try:
        yield conn
        conn.commit()
    except _BROKEN:
        broken = True
        raise
    except Exception:
        try:
            conn.rollback()
        except _BROKEN:
            broken = True
        raise
    finally:
        if broken or conn.closed:
            _discard(pool, conn)
        else:
            _last_used[id(conn)] = time.monotonic()
            pool.putconn(conn)


def fetch(sql, params=None, attempts=3):
    """Lectura. Se reintenta si la conexión se cae."""
    for attempt in range(attempts):
        try:
            with _connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
        except _BROKEN as e:
            if attempt == attempts - 1:
                raise DBError(_friendly(e)) from e
            time.sleep(0.5 * (attempt + 1))
        except psycopg2.Error as e:
            raise DBError(_friendly(e)) from e


def fetch_one(sql, params=None):
    rows = fetch(sql, params)
    return rows[0] if rows else None


@contextmanager
def transaction():
    """Escritura en una transacción. No se reintenta para no duplicar datos."""
    try:
        with _connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
    except psycopg2.Error as e:
        raise DBError(_friendly(e)) from e


def execute(sql, params=None):
    with transaction() as cur:
        cur.execute(sql, params)
        return cur.fetchone() if cur.description else cur.rowcount


# Migraciones idempotentes: solo agregan tablas/columnas, no borran datos.
_MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS clientes (
        id SERIAL PRIMARY KEY, nombre TEXT NOT NULL, apellido TEXT NOT NULL,
        edad INTEGER, telefono TEXT, email TEXT)""",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS fecha_nacimiento DATE",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS origen TEXT",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS domicilio TEXT",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS acepta_mensajes BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP",
    "ALTER TABLE clientes ALTER COLUMN creado_en SET DEFAULT (now() AT TIME ZONE 'America/Argentina/Buenos_Aires')",
    """CREATE TABLE IF NOT EXISTS historias_clinicas (
        cliente_id INTEGER PRIMARY KEY REFERENCES clientes(id) ON DELETE CASCADE, notas TEXT)""",
    """CREATE TABLE IF NOT EXISTS tratamientos (
        id SERIAL PRIMARY KEY, nombre TEXT NOT NULL, precio NUMERIC(12,2) NOT NULL DEFAULT 0)""",
    "ALTER TABLE tratamientos ADD COLUMN IF NOT EXISTS duracion_min INTEGER NOT NULL DEFAULT 60",
    "ALTER TABLE tratamientos ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE tratamientos ADD COLUMN IF NOT EXISTS descripcion TEXT",
    """CREATE TABLE IF NOT EXISTS turnos (
        id SERIAL PRIMARY KEY, cliente_id INTEGER NOT NULL REFERENCES clientes(id),
        fecha_inicio TIMESTAMP NOT NULL, fecha_fin TIMESTAMP, profesional TEXT)""",
    "ALTER TABLE turnos ADD COLUMN IF NOT EXISTS servicios TEXT",
    "ALTER TABLE turnos ADD COLUMN IF NOT EXISTS estado TEXT NOT NULL DEFAULT 'reservado'",
    "ALTER TABLE turnos ADD COLUMN IF NOT EXISTS notas TEXT",
    "ALTER TABLE turnos ADD COLUMN IF NOT EXISTS total NUMERIC(12,2)",
    "ALTER TABLE turnos ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP",
    "ALTER TABLE turnos ALTER COLUMN creado_en SET DEFAULT (now() AT TIME ZONE 'America/Argentina/Buenos_Aires')",
    "ALTER TABLE turnos ADD COLUMN IF NOT EXISTS sena_monto NUMERIC(12,2)",
    "ALTER TABLE turnos ADD COLUMN IF NOT EXISTS sena_fecha TIMESTAMP",
    "ALTER TABLE turnos ADD COLUMN IF NOT EXISTS sena_medio TEXT",
    "UPDATE turnos SET fecha_fin = fecha_inicio + INTERVAL '1 hour' WHERE fecha_fin IS NULL",
    "CREATE INDEX IF NOT EXISTS turnos_fecha_inicio_idx ON turnos (fecha_inicio)",
    "CREATE INDEX IF NOT EXISTS turnos_cliente_idx ON turnos (cliente_id)",
    """CREATE TABLE IF NOT EXISTS turno_tratamientos (
        turno_id INTEGER NOT NULL REFERENCES turnos(id) ON DELETE CASCADE,
        tratamiento_id INTEGER NOT NULL REFERENCES tratamientos(id),
        precio NUMERIC(12,2),
        PRIMARY KEY (turno_id, tratamiento_id))""",
    "CREATE TABLE IF NOT EXISTS configuracion (clave TEXT PRIMARY KEY, valor TEXT NOT NULL)",
    # Historia clínica: antecedentes fijos por cliente + entradas fechadas que no se pisan.
    "ALTER TABLE historias_clinicas ADD COLUMN IF NOT EXISTS alergias TEXT",
    "ALTER TABLE historias_clinicas ADD COLUMN IF NOT EXISTS medicacion TEXT",
    "ALTER TABLE historias_clinicas ADD COLUMN IF NOT EXISTS contraindicaciones TEXT",
    "ALTER TABLE historias_clinicas ADD COLUMN IF NOT EXISTS antecedentes TEXT",
    "ALTER TABLE historias_clinicas ADD COLUMN IF NOT EXISTS consentimiento_fecha DATE",
    "ALTER TABLE historias_clinicas ADD COLUMN IF NOT EXISTS actualizado_en TIMESTAMP",
    """CREATE TABLE IF NOT EXISTS historia_entradas (
        id SERIAL PRIMARY KEY,
        cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
        fecha TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'America/Argentina/Buenos_Aires'),
        tipo TEXT NOT NULL DEFAULT 'nota',
        texto TEXT NOT NULL,
        autor TEXT,
        turno_id INTEGER UNIQUE REFERENCES turnos(id) ON DELETE SET NULL)""",
    "CREATE INDEX IF NOT EXISTS historia_entradas_cliente_idx ON historia_entradas (cliente_id, fecha DESC)",
    # El texto libre de la versión anterior pasa a ser la primera entrada de cada cliente.
    """INSERT INTO historia_entradas (cliente_id, tipo, texto, autor)
       SELECT cliente_id, 'nota', notas, 'Historia anterior'
       FROM historias_clinicas WHERE COALESCE(notas, '') <> ''""",
    "UPDATE historias_clinicas SET notas = NULL WHERE COALESCE(notas, '') <> ''",
]


@st.cache_resource(show_spinner="Conectando con la base de datos…")
def ensure_schema():
    with transaction() as cur:
        cur.execute(
            """SELECT 1 FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = 'turnos'
                 AND column_name = 'servicios'"""
        )
        had_servicios = cur.fetchone() is not None
        for statement in _MIGRATIONS:
            cur.execute(statement)
        if not had_servicios:
            # La versión anterior guardaba los tratamientos en la columna "profesional".
            cur.execute(
                "UPDATE turnos SET servicios = profesional, profesional = NULL WHERE servicios IS NULL"
            )
    return True

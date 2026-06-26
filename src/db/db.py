"""
GRA — Database connection and schema management (PostgreSQL / Supabase).

Public API
----------
open_db()           → psycopg2 connection  (reads DATABASE_URL from env)
init_db()           → psycopg2 connection  (creates schema + seeds data)
check_version(conn)
build_record_url(source, record) → str | None

Constants
---------
SCHEMA_VERSION      int     (imported from src.constants)
SCHEMA_SQL          Path
SEED_SQL            Path
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from src.constants import SCHEMA_VERSION

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCHEMA_SQL = Path(__file__).parent / "schema.sql"
SEED_SQL   = Path(__file__).parent / "seed.sql"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def open_db() -> psycopg2.extensions.connection:
    """
    Open a connection to the PostgreSQL database.

    Reads DATABASE_ENVIRONMENT to determine local vs. cloud:
      - local: uses DATABASE_URL_LOCAL (localhost:5432)
      - cloud: uses DATABASE_URL_CLOUD (Supabase)

    If DATABASE_ENVIRONMENT is not set, defaults to 'local'.

    Returns a psycopg2 connection using RealDictCursor as the default
    cursor factory, so rows support dict-style key access: row["col"].

    Raises EnvironmentError if the selected URL is not set.
    """
    env = os.environ.get("DATABASE_ENVIRONMENT", "local").lower().strip()

    if env == "cloud":
        url = os.environ.get("DATABASE_URL_CLOUD")
        if not url:
            raise EnvironmentError(
                "DATABASE_ENVIRONMENT=cloud but DATABASE_URL_CLOUD is not set.\n"
                "Add DATABASE_URL_CLOUD to your .env file.\n"
                "  Format: postgresql://postgres:[password]@[host]:5432/postgres"
            )
    else:  # default to local
        url = os.environ.get("DATABASE_URL_LOCAL")
        if not url:
            raise EnvironmentError(
                "DATABASE_ENVIRONMENT=local but DATABASE_URL_LOCAL is not set.\n"
                "Add DATABASE_URL_LOCAL to your .env file.\n"
                "  Format: postgresql://[user]@[host]:5432/[database]"
            )

    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn


def _execute_sql_file(cur: Any, sql: str) -> None:
    """
    Execute a multi-statement SQL file.

    PostgreSQL allows executing multiple statements in one execute() call,
    so we just pass the entire file contents. Comments are preserved and
    handled correctly by the PostgreSQL parser.
    """
    cur.execute(sql)


def init_db() -> psycopg2.extensions.connection:
    """
    Initialise a fresh database: create schema, insert seed data, record version.

    Safe to call on a blank Supabase project. Raises if gra_meta already exists
    (indicates the database has already been initialised).

    Rolls back and closes the connection on any failure so the caller is never
    left with a half-initialised database or a dangling connection.
    """
    conn = open_db()
    try:
        with conn.cursor() as cur:
            # Guard: refuse to re-initialise an existing GRA database.
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'gra_meta'
                )
            """)
            if cur.fetchone()["exists"]:
                raise RuntimeError(
                    "Database already contains a gra_meta table — it appears to have been "
                    "initialised already. Drop the schema manually before reinitialising."
                )

            _execute_sql_file(cur, SCHEMA_SQL.read_text())
            _execute_sql_file(cur, SEED_SQL.read_text())
            cur.execute(
                "INSERT INTO gra_meta (key, value) VALUES (%s, %s)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    print(f"Initialised database (schema v{SCHEMA_VERSION // 10}.{SCHEMA_VERSION % 10}).")
    return conn


def check_version(conn: psycopg2.extensions.connection) -> None:
    """Raise RuntimeError if the database schema version does not match SCHEMA_VERSION."""
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM gra_meta WHERE key = 'schema_version'")
        row = cur.fetchone()

    if row is None:
        raise RuntimeError(
            "gra_meta table is empty — cannot determine schema version. "
            "Reinitialise the database with 'python -m src.cli init'."
        )

    version = int(row["value"])
    if version != SCHEMA_VERSION:
        raise RuntimeError(
            f"Schema version mismatch: expected {SCHEMA_VERSION}, got {version}. "
            "Run migrations before using this database."
        )


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------


def build_record_url(source: dict, record: dict) -> str | None:
    """
    Construct a deep link URL for a Record by merging source_parameters
    (Source-level constants) with record_parameters (Record-level values)
    and substituting into the record_url_template.

    Returns None if the source has no record_url_template.
    Raises ValueError if any placeholder remains unresolved after the merge.
    """
    template = source.get("record_url_template")
    if not template:
        return None

    params: dict[str, Any] = {}

    raw_sp = source.get("source_parameters")
    if raw_sp:
        sp = json.loads(raw_sp) if isinstance(raw_sp, str) else raw_sp
        if sp:
            params.update(sp)

    raw_rp = record.get("record_parameters")
    if raw_rp:
        rp = json.loads(raw_rp) if isinstance(raw_rp, str) else raw_rp
        if rp:
            params.update(rp)

    try:
        return template.format(**params)
    except KeyError as e:
        raise ValueError(
            f"Unresolved placeholder {e} in URL template '{template}' "
            f"after merging source_parameters and record_parameters."
        ) from e

"""
GRA — Database connection and schema management helpers.

Extracted from src/db.py (Commit 1 refactor).

Public API
----------
open_db(path)       → sqlite3.Connection
init_db(path)       → sqlite3.Connection
check_version(conn)
build_record_url(source, record) → str | None

Constants
---------
SCHEMA_VERSION      int
DEFAULT_DB          str
SCHEMA_SQL          Path
SEED_SQL            Path
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Schema version and paths
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 30
DEFAULT_DB = "genealogy.db"
SCHEMA_SQL = Path(__file__).parent / "schema.sql"
SEED_SQL = Path(__file__).parent / "seed.sql"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def open_db(path: str = DEFAULT_DB) -> sqlite3.Connection:
    """Open a connection with required PRAGMAs set."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def init_db(path: str = DEFAULT_DB) -> sqlite3.Connection:
    """Initialise a fresh database: create schema then insert seed data."""
    if Path(path).exists():
        raise FileExistsError(
            f"Database already exists at '{path}'. "
            "Delete it manually before reinitialising."
        )
    conn = open_db(path)
    conn.executescript(SCHEMA_SQL.read_text())
    conn.executescript(SEED_SQL.read_text())
    conn.commit()
    print(f"Initialised database at '{path}' (schema v{SCHEMA_VERSION // 10}.{SCHEMA_VERSION % 10}).")
    return conn


def check_version(conn: sqlite3.Connection) -> None:
    """Raise if the database schema version does not match the expected version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
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

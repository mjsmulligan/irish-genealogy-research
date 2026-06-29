"""
GRA — Database connection and repository factory.

Uses the Repository pattern to abstract database choice.
Business logic uses Repository interface, not database-specific code.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

try:
    from supabase import create_client
except ImportError:
    create_client = None

from src.constants import SCHEMA_VERSION
from src.db.repository import Repository
from src.db.postgres_repo import PostgresRepository
from src.db.supabase_repo import SupabaseRepository

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCHEMA_SQL = Path(__file__).parent / "schema.sql"
SEED_SQL = Path(__file__).parent / "seed.sql"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def open_db() -> Repository:
    """
    Open a database connection and return a Repository.

    Reads DATABASE_ENVIRONMENT to determine local vs. cloud:
      - local: PostgreSQL via psycopg2
      - cloud: Supabase via REST API

    Defaults to 'local' if not set.
    """
    env = os.environ.get("DATABASE_ENVIRONMENT", "local").lower().strip()

    if env == "cloud":
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SECRET_KEY")
        if not url or not key:
            raise EnvironmentError(
                "DATABASE_ENVIRONMENT=cloud but SUPABASE_URL or SUPABASE_SECRET_KEY not set.\n"
                "Add to .env:\n"
                "  SUPABASE_URL=https://[project-id].supabase.co\n"
                "  SUPABASE_SECRET_KEY=your_service_role_key"
            )
        if not create_client:
            raise ImportError("supabase package not installed")
        client = create_client(url, key)
        return SupabaseRepository(client)
    else:
        url = os.environ.get("DATABASE_URL_LOCAL")
        if not url:
            raise EnvironmentError(
                "DATABASE_ENVIRONMENT=local but DATABASE_URL_LOCAL not set.\n"
                "Add to .env:\n"
                "  DATABASE_URL_LOCAL=postgresql://[user]@[host]:5432/[database]"
            )
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = False
        return PostgresRepository(conn)


def _execute_sql_file(cur, sql: str) -> None:
    """Execute multi-statement SQL file."""
    cur.execute(sql)


def init_db() -> Repository:
    """
    Initialise a fresh database: create schema, insert seed data, record version.

    Safe to call on a blank Supabase project. Raises if gra_meta already exists.
    """
    env = os.environ.get("DATABASE_ENVIRONMENT", "local").lower().strip()

    if env == "cloud":
        return _init_db_cloud()
    else:
        return _init_db_local()


def _init_db_local() -> Repository:
    """Initialize local PostgreSQL database."""
    repo = open_db()

    try:
        # Check if already initialized
        result = repo.fetch_one("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'gra_meta'
            ) AS exists
        """)
        if result and result.get("exists"):
            raise RuntimeError(
                "Database already contains gra_meta table.\n"
                "Drop the schema manually before reinitialising."
            )

        # Create schema and seed
        schema_sql = SCHEMA_SQL.read_text()
        seed_sql = SEED_SQL.read_text()

        # Execute as raw SQL
        repo.execute(schema_sql)
        repo.execute(seed_sql)

        # Record version
        repo.execute(
            "INSERT INTO gra_meta (key, value) VALUES (%s, %s)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        repo.commit()
    except Exception:
        repo.rollback()
        repo.close()
        raise

    print(f"Initialised database (schema v{SCHEMA_VERSION // 10}.{SCHEMA_VERSION % 10}).")
    return repo


def _init_db_cloud() -> Repository:
    """Verify Supabase cloud database is initialized (schema must exist already)."""
    repo = open_db()

    try:
        result = repo.fetch_one("SELECT * FROM gra_meta LIMIT 1")
        if result:
            print("Cloud database already initialized.")
            return repo
    except Exception as e:
        raise RuntimeError(
            "Could not find gra_meta table. Schema not initialized.\n"
            "Initialize via Supabase SQL Editor:\n"
            "1. Go to https://app.supabase.com → select project\n"
            "2. SQL Editor → New query\n"
            "3. Copy schema.sql and seed.sql, run each\n"
            f"Error: {e}"
        )

    return repo


def check_version(repo: Repository) -> None:
    """Raise RuntimeError if schema version does not match."""
    result = repo.fetch_one(
        "SELECT value FROM gra_meta WHERE key = 'schema_version'"
    )

    if not result:
        raise RuntimeError(
            "gra_meta table is empty.\n"
            "Reinitialise with 'python -m src.cli init'."
        )

    version = int(result["value"])
    if version != SCHEMA_VERSION:
        raise RuntimeError(
            f"Schema version mismatch: expected {SCHEMA_VERSION}, got {version}.\n"
            "Run migrations before using this database."
        )


def build_record_url(source: dict, record: dict) -> str | None:
    """Construct a deep link URL for a Record."""
    import json

    template = source.get("record_url_template")
    if not template:
        return None

    params: dict = {}

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
            f"Unresolved placeholder {e} in URL template '{template}'"
        ) from e

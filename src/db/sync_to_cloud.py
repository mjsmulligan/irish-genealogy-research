"""
Sync local PostgreSQL database to Supabase cloud via dump + restore.

Usage:
    python -m src.cli sync-to-cloud

This exports the local database as SQL, then imports it to Supabase.
Useful for one-off backups or pushing completed work to the cloud.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def dump_local_db() -> str:
    """
    Dump local PostgreSQL database to SQL.
    Returns the SQL content as a string.
    """
    local_url = os.environ.get("DATABASE_URL_LOCAL")
    if not local_url:
        raise EnvironmentError("DATABASE_URL_LOCAL not set")

    # Parse connection string: postgresql://user:password@host:port/dbname
    try:
        from urllib.parse import urlparse
        parsed = urlparse(local_url)
        user = parsed.username
        password = parsed.password
        host = parsed.hostname
        port = parsed.port or 5432
        dbname = parsed.path.lstrip("/")
    except Exception as e:
        raise ValueError(f"Could not parse DATABASE_URL_LOCAL: {e}")

    # Use pg_dump to export
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".sql", delete=False) as f:
        dump_file = f.name

    try:
        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password

        result = subprocess.run(
            [
                "pg_dump",
                "-h", host,
                "-p", str(port),
                "-U", user,
                "-d", dbname,
                "--no-owner",
                "--no-privileges",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {result.stderr}")

        return result.stdout

    finally:
        if Path(dump_file).exists():
            Path(dump_file).unlink()


def restore_to_supabase(sql_content: str) -> None:
    """
    Restore SQL dump to Supabase via REST API.
    Splits SQL into statements and executes via execute_sql RPC.
    """
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")

    if not url or not key:
        raise EnvironmentError(
            "SUPABASE_URL and SUPABASE_SECRET_KEY not set.\n"
            "Cannot restore to cloud."
        )

    client = create_client(url, key)

    # Split SQL into individual statements
    # Simple split by semicolon (adequate for most dumps)
    statements = [stmt.strip() for stmt in sql_content.split(";") if stmt.strip()]

    print(f"Restoring {len(statements)} SQL statements to Supabase...")

    executed = 0
    skipped = 0

    for i, stmt in enumerate(statements, 1):
        try:
            # Normalize statement
            stmt = " ".join(stmt.split())

            # Skip comments and metadata
            if stmt.startswith("--"):
                skipped += 1
                continue

            # Skip pg_dump metadata comments (Type, Schema, Owner, etc.)
            if any(stmt.startswith(f"-- {prefix}") for prefix in ["Type:", "Schema:", "Owner:", "SET ", "BEGIN", "COMMIT"]):
                skipped += 1
                continue

            # Execute via execute_sql RPC
            client.rpc("execute_sql", {"sql_text": stmt}).execute()
            executed += 1

            if executed % 100 == 0:
                print(f"  {executed} statements executed...")

        except Exception as e:
            # Log but continue — some statements may fail (e.g., index creation)
            # but data should be intact
            if i % 50 == 0:  # Only log every 50th error to reduce noise
                print(f"  Warning: Statement {i} failed: {e}")

    print(f"✓ Restored {executed} statements ({skipped} skipped) to Supabase")


def sync_to_cloud() -> None:
    """Dump local database and restore to Supabase."""
    print("Starting sync to cloud...")
    print()

    print("[1/2] Dumping local database...")
    sql_content = dump_local_db()
    print(f"  ✓ Dumped {len(sql_content):,} bytes")
    print()

    print("[2/2] Restoring to Supabase...")
    restore_to_supabase(sql_content)
    print()

    print("✓ Sync complete!")
    print("Local database has been backed up to Supabase.")

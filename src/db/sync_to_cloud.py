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
                "--data-only",
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
    Converts COPY statements to INSERTs (pg_dump --data-only uses COPY FROM stdin).
    """
    from supabase import create_client
    import re

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")

    if not url or not key:
        raise EnvironmentError(
            "SUPABASE_URL and SUPABASE_SECRET_KEY not set.\n"
            "Cannot restore to cloud."
        )

    client = create_client(url, key)

    # Parse COPY statements and convert to INSERTs
    insert_statements = []
    lines = sql_content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for COPY statement
        copy_match = re.match(r'^COPY\s+public\.(\w+)\s*\((.*?)\)\s+FROM\s+stdin', line)
        if copy_match:
            table_name = copy_match.group(1)
            columns = [col.strip() for col in copy_match.group(2).split(",")]

            i += 1
            # Read data lines until we hit \. (terminator)
            data_lines = []
            while i < len(lines) and not lines[i].strip().startswith("\\"):
                if lines[i].strip():
                    data_lines.append(lines[i])
                i += 1

            # Convert each data line to INSERT
            for data_line in data_lines:
                values = data_line.split("\t")
                # Quote and escape string values
                quoted_values = []
                for v in values:
                    if v == "\\N":
                        quoted_values.append("NULL")
                    else:
                        # Escape single quotes
                        escaped = v.replace("'", "''")
                        quoted_values.append(f"'{escaped}'")

                insert_stmt = f"INSERT INTO public.{table_name} ({', '.join(columns)}) OVERRIDING SYSTEM VALUE VALUES ({', '.join(quoted_values)}) ON CONFLICT DO NOTHING"
                insert_statements.append(insert_stmt)

        i += 1

    print(f"Converted COPY statements to {len(insert_statements)} INSERT statements")
    print(f"Restoring to Supabase...")

    executed = 0
    failed = 0

    for i, stmt in enumerate(insert_statements, 1):
        try:
            client.rpc("execute_sql", {"sql_text": stmt}).execute()
            executed += 1

            if executed % 500 == 0:
                print(f"  {executed} rows inserted...")

        except Exception as e:
            failed += 1
            if failed <= 10:  # Only log first 10 errors
                print(f"  Warning: Row {i} failed: {str(e)[:100]}")

    print(f"✓ Restored {executed} rows to Supabase ({failed} failed)")


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

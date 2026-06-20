# Archived SQLite migrations

These migration scripts applied incremental schema changes to the SQLite
database used in GRA v1.x–v3.0.

They are retained for historical reference only. With the migration to
PostgreSQL (Supabase) in v3.1, the SQLite schema and all associated
migrations are retired. The canonical schema is now `src/db/schema.sql`
(PostgreSQL). Future migrations will target PostgreSQL from v3.1 onwards.

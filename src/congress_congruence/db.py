"""Database connection and schema migrations.

Migrations are the .sql files in sql/, applied once each in filename order.
Applied files are recorded in core.schema_migration so re-running is safe.

Usage:
    python -m congress_congruence.db migrate
"""

import sys
from pathlib import Path

import psycopg

from . import config

SQL_DIR = config.PROJECT_ROOT / "sql"


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or config.database_url())


def migrate(conn: psycopg.Connection, sql_dir: Path = SQL_DIR) -> list[str]:
    """Apply any .sql files not yet applied. Returns the names applied this time."""
    with conn.cursor() as cur:
        cur.execute("create schema if not exists core")
        cur.execute(
            """create table if not exists core.schema_migration (
                   filename   text primary key,
                   applied_at timestamptz not null default now())"""
        )
        cur.execute("select filename from core.schema_migration")
        done = {row[0] for row in cur.fetchall()}
    conn.commit()

    applied = []
    for path in sorted(sql_dir.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(path.read_text())
            cur.execute("insert into core.schema_migration (filename) values (%s)", (path.name,))
        applied.append(path.name)
    return applied


def main(argv: list[str]) -> int:
    if argv[1:] != ["migrate"]:
        print(__doc__)
        return 2
    with connect() as conn:
        applied = migrate(conn)
    print("Applied:", ", ".join(applied) if applied else "nothing (already up to date)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

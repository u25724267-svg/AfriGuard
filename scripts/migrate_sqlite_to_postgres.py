"""Copy the current AfriGuard SQLite database into PostgreSQL.

This script is intentionally conservative:
- It never modifies the source SQLite database.
- It creates missing Postgres tables from the SQLAlchemy ORM metadata.
- It refuses to copy into non-empty Postgres tables unless --replace is used.

Usage:
    venv/bin/python scripts/migrate_sqlite_to_postgres.py \
      --postgres-url postgresql+psycopg2://user:pass@host:5432/afriguard
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterable

from sqlalchemy import create_engine, delete, func, insert, select
from sqlalchemy.engine import Engine

from src.config.env import load_project_env
from src.storage.db import Base


DEFAULT_SQLITE_URL = "sqlite:///./afriguard.db"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate AfriGuard data from SQLite into PostgreSQL."
    )
    parser.add_argument(
        "--sqlite-url",
        default=os.environ.get("SQLITE_DATABASE_URL", DEFAULT_SQLITE_URL),
        help=f"Source SQLite SQLAlchemy URL. Default: {DEFAULT_SQLITE_URL}",
    )
    parser.add_argument(
        "--postgres-url",
        default=os.environ.get("POSTGRES_DATABASE_URL"),
        help=(
            "Destination Postgres SQLAlchemy URL. Can also be provided via "
            "POSTGRES_DATABASE_URL."
        ),
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing rows in destination tables before copying.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print source/destination row counts without copying.",
    )
    return parser.parse_args()


def _engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url)


def _row_count(engine: Engine, table) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())


def _table_counts(engine: Engine, tables: Iterable) -> dict[str, int]:
    return {table.name: _row_count(engine, table) for table in tables}


def _print_counts(label: str, counts: dict[str, int]) -> None:
    print(label)
    for table_name, count in counts.items():
        print(f"  {table_name}: {count}")


def main() -> None:
    load_project_env()
    args = _parse_args()

    if not args.postgres_url:
        raise SystemExit(
            "Missing --postgres-url or POSTGRES_DATABASE_URL. "
            "Example: postgresql+psycopg2://user:pass@localhost:5432/afriguard"
        )
    if not args.sqlite_url.startswith("sqlite"):
        raise SystemExit(f"--sqlite-url must be a SQLite URL, got: {args.sqlite_url}")
    if not args.postgres_url.startswith("postgresql"):
        raise SystemExit(
            "--postgres-url must start with postgresql or postgresql+psycopg2."
        )

    source = _engine(args.sqlite_url)
    dest = _engine(args.postgres_url)
    tables = list(Base.metadata.sorted_tables)

    Base.metadata.create_all(bind=dest)

    source_counts = _table_counts(source, tables)
    dest_counts = _table_counts(dest, tables)
    _print_counts("Source SQLite counts:", source_counts)
    _print_counts("Destination Postgres counts:", dest_counts)

    non_empty = {name: count for name, count in dest_counts.items() if count}
    if args.dry_run:
        print("Dry run complete; no data copied.")
        return
    if non_empty and not args.replace:
        print("Destination has existing data:")
        for table_name, count in non_empty.items():
            print(f"  {table_name}: {count}")
        raise SystemExit(
            "Refusing to copy into non-empty Postgres tables. "
            "Use --replace to delete destination rows first."
        )

    with dest.begin() as dest_conn:
        if args.replace:
            for table in reversed(tables):
                dest_conn.execute(delete(table))

        with source.connect() as source_conn:
            for table in tables:
                rows = [dict(row._mapping) for row in source_conn.execute(select(table))]
                if not rows:
                    print(f"Copied {table.name}: 0")
                    continue
                dest_conn.execute(insert(table), rows)
                print(f"Copied {table.name}: {len(rows)}")

    final_counts = _table_counts(dest, tables)
    _print_counts("Final Postgres counts:", final_counts)
    print("Migration complete. Update DATABASE_URL in .env after verifying counts.")


if __name__ == "__main__":
    main()

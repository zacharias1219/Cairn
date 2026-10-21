"""Plain-SQL migrations, applied in filename order and recorded once each."""

from __future__ import annotations

from importlib import resources

import psycopg
from psycopg import sql

from cairn.config import get_settings


def _migration_files() -> list[tuple[str, str]]:
    pkg = resources.files("cairn.db") / "migrations"
    files = sorted(p for p in pkg.iterdir() if p.name.endswith(".sql"))
    return [(p.name, p.read_text()) for p in files]


def ensure_app_role(conn: psycopg.Connection, password: str | None) -> None:
    """Create the RLS-bound app role, keeping its password in step with CAIRN_DATABASE_URL."""
    exists = conn.execute("select 1 from pg_roles where rolname = 'cairn_app'").fetchone()
    if not exists:
        conn.execute("create role cairn_app login nosuperuser nobypassrls")
    if password:
        conn.execute(sql.SQL("alter role cairn_app password {}").format(sql.Literal(password)))
    conn.execute(
        sql.SQL("grant connect on database {} to cairn_app").format(
            sql.Identifier(conn.info.dbname)
        )
    )
    conn.execute("grant usage on schema public to cairn_app")
    conn.execute("grant select, insert, update, delete on all tables in schema public to cairn_app")
    conn.execute("grant usage, select on all sequences in schema public to cairn_app")
    conn.execute("grant execute on all functions in schema public to cairn_app")
    # The schema bookkeeping table is not tenant data.
    conn.execute("revoke all on schema_migrations from cairn_app")


def migrate(admin_url: str | None = None, *, verbose: bool = True) -> list[str]:
    s = get_settings()
    url = admin_url or s.admin_db_url
    applied: list[str] = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "create table if not exists schema_migrations "
            "(name text primary key, applied_at timestamptz not null default now())"
        )
        done = {r[0] for r in conn.execute("select name from schema_migrations").fetchall()}
        for name, body in _migration_files():
            if name in done:
                continue
            with conn.transaction():
                conn.execute(body)
                conn.execute("insert into schema_migrations (name) values (%s)", (name,))
            applied.append(name)
            if verbose:
                print(f"  applied {name}")
        ensure_app_role(conn, s.app_role_password)
    return applied


def reset(admin_url: str | None = None) -> None:
    """Development only: drop every table and start from an empty schema."""
    url = admin_url or get_settings().admin_db_url
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
        conn.execute("grant all on schema public to public")

"""Database access.

Two pools:

* the **app pool** connects as `cairn_app`, which is subject to row-level
  security. Every unit of work runs inside ``tenant_tx(tenant_id)``, which
  sets ``app.tenant_id`` for that transaction only.
* the **system pool** connects as the schema owner. It is used for
  migrations, provisioning tenants, and claiming jobs across tenants, and
  never to serve a request on behalf of a tenant.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb, JsonbDumper, set_json_dumps
from psycopg_pool import AsyncConnectionPool

from cairn.config import get_settings


def _default(o: Any) -> Any:
    if isinstance(o, (uuid.UUID,)):
        return str(o)
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return float(o)
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def dumps(o: Any) -> str:
    return json.dumps(o, default=_default, separators=(",", ":"))


set_json_dumps(dumps)


class _DictJsonbDumper(JsonbDumper):
    """Lets plain dicts be passed as jsonb parameters."""


async def _configure(conn: AsyncConnection) -> None:
    conn.adapters.register_dumper(dict, _DictJsonbDumper)
    await conn.set_autocommit(True)


_app_pool: AsyncConnectionPool | None = None
_system_pool: AsyncConnectionPool | None = None


async def open_pools(min_size: int = 1, max_size: int = 10) -> None:
    global _app_pool, _system_pool
    s = get_settings()
    if _app_pool is None:
        _app_pool = AsyncConnectionPool(
            s.app_db_url, min_size=min_size, max_size=max_size,
            kwargs={"row_factory": dict_row}, configure=_configure, open=False,
        )
        await _app_pool.open(wait=True)
    if _system_pool is None:
        _system_pool = AsyncConnectionPool(
            s.admin_db_url, min_size=1, max_size=4,
            kwargs={"row_factory": dict_row}, configure=_configure, open=False,
        )
        await _system_pool.open(wait=True)


async def close_pools() -> None:
    global _app_pool, _system_pool
    for p in (_app_pool, _system_pool):
        if p is not None:
            await p.close()
    _app_pool = _system_pool = None


@asynccontextmanager
async def tenant_tx(tenant_id: uuid.UUID | str) -> AsyncIterator[AsyncConnection]:
    """A transaction scoped to one tenant. RLS sees only that tenant's rows."""
    assert _app_pool is not None, "pools not open"
    async with _app_pool.connection() as conn:
        async with conn.transaction():
            await conn.execute("select set_config('app.tenant_id', %s, true)", (str(tenant_id),))
            yield conn


@asynccontextmanager
async def anon_tx() -> AsyncIterator[AsyncConnection]:
    """A transaction with no tenant set: sees zero rows, may call auth_* functions."""
    assert _app_pool is not None, "pools not open"
    async with _app_pool.connection() as conn:
        async with conn.transaction():
            yield conn


@asynccontextmanager
async def system_tx() -> AsyncIterator[AsyncConnection]:
    assert _system_pool is not None, "pools not open"
    async with _system_pool.connection() as conn:
        async with conn.transaction():
            yield conn


async def fetch_one(conn: AsyncConnection, sql: str, params: Any = None) -> dict | None:
    cur = await conn.execute(sql, params)
    return await cur.fetchone()


async def fetch_all(conn: AsyncConnection, sql: str, params: Any = None) -> list[dict]:
    cur = await conn.execute(sql, params)
    return await cur.fetchall()


def vec(v: list[float]) -> str:
    """pgvector literal."""
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


__all__ = [
    "Jsonb", "tenant_tx", "anon_tx", "system_tx", "fetch_one", "fetch_all",
    "open_pools", "close_pools", "dumps", "vec",
]

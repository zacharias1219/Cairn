"""A Postgres-backed job queue (section 9: one database, one queue).

Jobs are claimed with ``FOR UPDATE SKIP LOCKED`` so several workers can
run safely. Failed jobs retry with exponential backoff.
"""

from __future__ import annotations

import datetime as dt
import uuid

from psycopg import AsyncConnection

from cairn.db.core import Jsonb, fetch_one, system_tx


async def enqueue(conn: AsyncConnection, tenant_id: uuid.UUID, kind: str, payload: dict | None = None,
                  run_at: dt.datetime | None = None) -> int:
    row = await fetch_one(conn, "insert into jobs (tenant_id, kind, payload, run_at) values (%s,%s,%s,coalesce(%s, now())) "
                                "returning id", (tenant_id, kind, Jsonb(payload or {}), run_at))
    return row["id"]


async def claim() -> dict | None:
    async with system_tx() as conn:
        return await fetch_one(conn, """
            update jobs set status='running', locked_at=now(), attempts=attempts+1
            where id = (select id from jobs where status='queued' and run_at <= now()
                        order by run_at limit 1 for update skip locked)
            returning *""")


async def complete(job_id: int) -> None:
    async with system_tx() as conn:
        await conn.execute("update jobs set status='done' where id=%s", (job_id,))


async def fail(job: dict, error: str, max_attempts: int = 5) -> None:
    async with system_tx() as conn:
        if job["attempts"] >= max_attempts:
            await conn.execute("update jobs set status='failed', last_error=%s where id=%s", (error, job["id"]))
        else:
            await conn.execute("update jobs set status='queued', last_error=%s, "
                               "run_at = now() + make_interval(secs => %s) where id=%s",
                               (error, 2 ** job["attempts"], job["id"]))

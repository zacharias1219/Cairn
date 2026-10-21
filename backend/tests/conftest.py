"""Test setup: a dedicated database, migrated from scratch, with two tenants."""

from __future__ import annotations

import os

import psycopg
import pytest

# Server URLs without a database name. Credentials come from the environment
# (CI uses trust auth, so none are needed there).
BASE = os.environ.get("CAIRN_TEST_PG", "postgresql://postgres@localhost:5432")
APP_BASE = os.environ.get("CAIRN_TEST_APP_PG", "postgresql://cairn_app@localhost:5432")
DB = os.environ.get("CAIRN_TEST_DB", "cairn_test")
os.environ["CAIRN_ADMIN_DATABASE_URL"] = f"{BASE}/{DB}"
os.environ["CAIRN_DATABASE_URL"] = f"{APP_BASE}/{DB}"
os.environ["CAIRN_ENV"] = "test"
os.environ["CAIRN_MODEL_MODE"] = "sandbox"
os.environ["CAIRN_RUN_WORKER"] = "false"


def _create_db() -> None:
    with psycopg.connect(f"{BASE}/postgres", autocommit=True) as conn:
        if not conn.execute("select 1 from pg_database where datname=%s", (DB,)).fetchone():
            conn.execute(f'create database "{DB}"')


@pytest.fixture(scope="session", autouse=True)
async def database():
    _create_db()
    from cairn.db.core import close_pools, open_pools
    from cairn.db.migrate import migrate, reset

    reset()
    migrate(verbose=False)
    await open_pools()
    yield
    await close_pools()


@pytest.fixture(scope="session")
async def acme(database):
    from cairn.tenancy import provision_demo

    return await provision_demo("acme")


@pytest.fixture(scope="session")
async def globex(database):
    from cairn.tenancy import provision_demo

    return await provision_demo("globex")


@pytest.fixture
def sandbox():
    from cairn.tools import sandbox_commerce

    box = sandbox_commerce.CommerceSandbox()
    token = sandbox_commerce.current.set(box)
    yield box
    sandbox_commerce.current.reset(token)


@pytest.fixture
async def client(acme):
    import httpx

    from cairn.api.app import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/auth/login", json={"email": "admin@acme.test", "password": "cairn-demo"})
        assert r.status_code == 200
        yield c

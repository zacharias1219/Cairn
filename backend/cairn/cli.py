"""Command line: `cairn <command>`.

    cairn db migrate           apply migrations and grant the app role
    cairn seed                 provision the Acme Outfitters sandbox tenant
    cairn demo-traffic         generate realistic history for the console
    cairn eval run             run every evaluation; exit 1 if a gate fails
    cairn serve                run the API (and the in-process worker)
    cairn worker               run the job worker on its own
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from cairn.config import get_settings


def _print_eval(report: dict) -> None:
    s = report["summary"]
    print()
    print(f"  Cairn evaluation · {s['cases']} cases · {s['duration_s']}s")
    print(f"  {s['passed']}/{s['cases']} passed · critical {s['critical_passed']}/{s['critical_total']}")
    print()
    for g in report["gates"]:
        mark = "PASS" if g["passed"] else "FAIL"
        print(f"  [{mark}] {g['gate']:<16} {g['value']:<28} {g['condition']}")
    if report["failures"]:
        print("\n  Failing cases:")
        for f in report["failures"][:40]:
            tag = "CRITICAL " if f["critical"] else ""
            print(f"   - {tag}{f['key']}")
            for x in f["failures"][:4]:
                print(f"       {x}")
    print(f"\n  Release gate: {'PASSED' if report['passed'] else 'BLOCKED'}  (run {report['run_id']})\n")


async def _with_pools(coro_fn):
    from cairn.db.core import close_pools, open_pools

    await open_pools()
    try:
        return await coro_fn()
    finally:
        await close_pools()


async def _tenant(slug: str):
    from cairn.db.core import fetch_one, system_tx

    async with system_tx() as conn:
        row = await fetch_one(conn, "select id from tenants where slug=%s", (slug,))
    if row is None:
        raise SystemExit(f"tenant {slug!r} not found; run `cairn seed` first")
    return row["id"]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="cairn", description="Cairn: every agent leaves a trail.")
    sub = p.add_subparsers(dest="cmd", required=True)
    db = sub.add_parser("db")
    db.add_argument("action", choices=["migrate", "reset"])
    seed = sub.add_parser("seed")
    seed.add_argument("--slug", default="acme")
    dt = sub.add_parser("demo-traffic")
    dt.add_argument("--slug", default="acme")
    dt.add_argument("--conversations", type=int, default=140)
    ev = sub.add_parser("eval")
    ev.add_argument("action", choices=["run"])
    ev.add_argument("--slug", default="acme")
    ev.add_argument("--suite", action="append", choices=["scenario", "critical", "adversarial"])
    ev.add_argument("--json", action="store_true")
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    sub.add_parser("worker")
    args = p.parse_args(argv)

    if args.cmd == "db":
        from cairn.db.migrate import migrate, reset

        if args.action == "reset":
            reset()
        applied = migrate()
        print(f"migrations applied: {len(applied)}")
    elif args.cmd == "seed":
        from cairn.tenancy import provision_demo

        tid = asyncio.run(_with_pools(lambda: provision_demo(args.slug)))
        print(f"tenant {args.slug} ready: {tid}")
        print("  sign in as admin@acme.test / cairn-demo (also builder@ and viewer@)")
    elif args.cmd == "demo-traffic":
        from cairn.demo import generate

        async def go():
            return await generate(await _tenant(args.slug), args.conversations)

        n = asyncio.run(_with_pools(go))
        print(f"generated {n} conversations")
    elif args.cmd == "eval":
        from cairn.evals.harness import run_suite

        async def go():
            return await run_suite(await _tenant(args.slug), trigger="cli", suites=args.suite)

        report = asyncio.run(_with_pools(go))
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            _print_eval(report)
        sys.exit(0 if report["passed"] else 1)
    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("cairn.api.app:app", host=args.host, port=args.port, reload=args.reload)
    elif args.cmd == "worker":
        from cairn.jobs.worker import run_forever

        get_settings()
        asyncio.run(_with_pools(run_forever))


if __name__ == "__main__":
    main()

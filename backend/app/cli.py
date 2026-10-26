"""``ledgerline`` command line."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer

from app.config import get_settings

app = typer.Typer(help="Ledgerline — autonomous revenue operations for PayPal merchants.", no_args_is_help=True)
sim = typer.Typer(help="Sandbox simulator and fixture replay.")
app.add_typer(sim, name="sim")


def _session():
    from app.db import session_scope

    return session_scope()


def _paypal():
    from app.paypal.client import PayPalClient

    s = get_settings()
    if not s.paypal_configured:
        typer.secho("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET not set", fg="red")
        raise typer.Exit(2)
    return PayPalClient()


@app.command()
def migrate():
    """Apply database migrations."""
    subprocess.check_call([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=Path(__file__).resolve().parent.parent)


@app.command()
def api(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """Run the API (and the built dashboard, if present)."""
    import uvicorn

    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


@app.command()
def worker():
    """Run the job worker + poller."""
    from app.worker.main import main

    main()


@app.command()
def reconcile(dispatch: bool = typer.Option(True, help="Queue agent runs for new breaks")):
    """Run every rule over the whole ledger."""
    from app.recon.engine import reconcile_all
    from app.worker import queue

    with _session() as s:
        new = reconcile_all(s)
        if dispatch:
            for b in new:
                if b.severity in ("critical", "warn"):
                    queue.enqueue(s, "run_agent", dedupe_key=f"break:{b.id}", payload={"break_id": b.id})
        typer.echo(f"new breaks: {len(new)}")
        for b in new:
            typer.echo(f"  [{b.severity}] {b.rule}: {b.title}")


@app.command()
def rebuild():
    """Drop projections and replay every ledger event."""
    from app.ledger.store import rebuild_projections

    with _session() as s:
        n = rebuild_projections(s)
    typer.echo(f"replayed {n} events")


@app.command()
def drain(max_passes: int = 50):
    """Process queued jobs once (useful without a long-running worker)."""
    from app.agents.runner import ensure_checkpointer
    from app.paypal.client import PayPalClient
    from app.worker.main import _handlers, run_once

    ensure_checkpointer()
    pp = PayPalClient() if get_settings().paypal_configured else None
    handlers = _handlers()
    total = 0
    for _ in range(max_passes):
        n = run_once(handlers, pp)
        total += n
        if n == 0:
            break
    typer.echo(f"processed {total} jobs")


@app.command()
def reset(yes: bool = typer.Option(False, "--yes", help="Skip confirmation")):
    """Truncate every Ledgerline table (dev only)."""
    from sqlalchemy import text

    if get_settings().app_env == "prod" and not yes:
        typer.secho("refusing to reset in prod without --yes", fg="red")
        raise typer.Exit(2)
    if not yes and not typer.confirm("Truncate all ledger, break, run and approval tables?"):
        raise typer.Exit(1)
    with _session() as s:
        s.execute(
            text(
                "TRUNCATE ledger_events, orders, captures, refunds, authorizations, payout_items, disputes, invoices, "
                "transactions, breaks, agent_runs, approvals, jobs, webhook_inbox RESTART IDENTITY"
            )
        )
        for t in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
            s.execute(text(f"TRUNCATE {t}"))
    typer.echo("reset done")


# ---------------------------------------------------------------- sim


@sim.command()
def replay(
    fixture: Path = typer.Argument(None, help="JSONL fixture (default: bundled demo)"),
    drain_after: bool = typer.Option(True, help="Run queued agent jobs after replay"),
):
    """Replay recorded PayPal inputs through the pipeline. No network needed."""
    from app.sim.replay import FIXTURES, replay_file

    path = fixture or FIXTURES / "demo.jsonl"
    with _session() as s:
        counts = replay_file(s, path)
    typer.echo(json.dumps(counts))
    if drain_after:
        drain()
    _print_breaks()


@sim.command()
def seed(orders: int = 6):
    """Create real activity in the PayPal sandbox and record it in the ledger."""
    from app.sim.seed import seed as _seed

    pp = _paypal()
    with _session() as s:
        res = _seed(s, pp, n_orders=orders)
    typer.echo(json.dumps(res, indent=2))
    (Path.cwd() / ".ledgerline-seed.json").write_text(json.dumps(res))


@sim.command()
def inject(seed_file: Path = Path(".ledgerline-seed.json")):
    """Make ledger and PayPal diverge (silent refund, duplicate refund record, ghost capture)."""
    from app.sim.seed import inject as _inject

    pp = _paypal()
    order_ids = json.loads(seed_file.read_text())["orders"]
    with _session() as s:
        res = _inject(s, pp, order_ids)
    typer.echo(json.dumps(res, indent=2))
    _print_breaks()


@sim.command()
def record(out: Path = Path("recorded.jsonl"), hours: int = 72):
    """Pull the sandbox's recent transactions and disputes into a replayable fixture."""
    from datetime import datetime, timedelta, timezone

    pp = _paypal()
    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(hours=hours)
    fmt = "%Y-%m-%dT%H:%M:%S-0000"
    lines = []
    res = pp.list_transactions(start.strftime(fmt), end.strftime(fmt))
    for item in res.get("transaction_details") or []:
        lines.append(json.dumps({"kind": "transaction", **item}))
    out.write_text("\n".join(lines) + "\n")
    typer.echo(f"wrote {len(lines)} records to {out}")


def _print_breaks():
    from sqlalchemy import select

    from app.domain.models import Break

    with _session() as s:
        rows = s.execute(select(Break).order_by(Break.severity.desc(), Break.id)).scalars().all()
        typer.echo(f"\n{len(rows)} breaks:")
        for b in rows:
            typer.echo(f"  [{b.severity:8}] {b.status:17} {b.rule:26} {b.title}")


if __name__ == "__main__":
    app()

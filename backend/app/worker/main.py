"""Worker process: drains the job queue and runs the periodic poller.

Run with ``ledgerline worker`` or ``python -m app.worker.main``. Multiple instances are safe.
"""
from __future__ import annotations

import signal
import time
import traceback
from collections.abc import Callable

from app.config import get_settings
from app.db import session_scope
from app.logging import configure_logging, get_logger
from app.paypal.client import PayPalClient
from app.worker import queue

log = get_logger("worker")
_running = True


def _handlers() -> dict[str, Callable]:
    # Imported lazily so the worker can start even if the agent stack is misconfigured.
    from app.agents.runner import run_agent_job
    from app.ingest.pipeline import process_webhook
    from app.ingest.poller import poll_disputes, poll_transactions
    from app.recon.engine import reconcile_all

    def _poll(session, payload, paypal):
        if paypal is None:
            return
        poll_transactions(session, paypal)
        poll_disputes(session, paypal)
        for b in reconcile_all(session):
            if b.severity in ("critical", "warn"):
                queue.enqueue(session, "run_agent", dedupe_key=f"break:{b.id}", payload={"break_id": b.id})

    def _recon_all(session, payload, paypal):
        reconcile_all(session)

    return {
        "process_webhook": process_webhook,
        "run_agent": run_agent_job,
        "poll": _poll,
        "reconcile_all": _recon_all,
    }


def run_once(handlers: dict[str, Callable], paypal: PayPalClient | None) -> int:
    s = get_settings()
    with session_scope() as session:
        jobs = queue.claim(session, s.job_batch_size)
    done = 0
    for job in jobs:
        handler = handlers.get(job.kind)
        try:
            if handler is None:
                raise RuntimeError(f"no handler for job kind {job.kind}")
            with session_scope() as session:
                handler(session, job.payload, paypal)
                queue.complete(session, job.id)
            done += 1
            log.info("job.done", id=job.id, kind=job.kind)
        except Exception as exc:  # noqa: BLE001
            err = f"{exc}\n{traceback.format_exc()}"
            log.error("job.failed", id=job.id, kind=job.kind, attempt=job.attempts, error=str(exc))
            with session_scope() as session:
                queue.fail(session, job, err)
    return done


def main() -> None:
    configure_logging()
    s = get_settings()
    paypal = PayPalClient() if s.paypal_configured else None
    handlers = _handlers()
    from app.agents.runner import ensure_checkpointer

    ensure_checkpointer()

    def _stop(*_):
        global _running
        _running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    last_poll = 0.0
    log.info("worker.start", paypal=bool(paypal), poll_interval=s.poll_interval_seconds)
    while _running:
        if paypal and time.time() - last_poll > s.poll_interval_seconds:
            with session_scope() as session:
                queue.enqueue(session, "poll", dedupe_key=f"poll:{int(time.time() // s.poll_interval_seconds)}")
            last_poll = time.time()
        n = run_once(handlers, paypal)
        if n == 0:
            time.sleep(1.0)
    log.info("worker.stop")


if __name__ == "__main__":
    main()

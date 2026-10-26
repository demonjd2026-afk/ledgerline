"""Tests run against a real Postgres (same engine as prod). Set TEST_DATABASE_URL to override.

Each test gets truncated tables; the stub LLM and dry-run executor are forced on so nothing
needs network access.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text

os.environ.setdefault("APP_ENV", "test")
os.environ["LLM_MODEL"] = "stub"
os.environ["PAYPAL_DRY_RUN"] = "true"
os.environ.pop("PAYPAL_CLIENT_ID", None)
os.environ.pop("PAYPAL_CLIENT_SECRET", None)
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

TABLES = (
    "ledger_events, orders, captures, refunds, authorizations, payout_items, disputes, invoices, transactions, "
    "breaks, agent_runs, approvals, jobs, webhook_inbox"
)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    import subprocess
    import sys
    from pathlib import Path

    subprocess.check_call([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=Path(__file__).resolve().parent.parent)
    from app.agents.runner import ensure_checkpointer

    ensure_checkpointer()


@pytest.fixture(autouse=True)
def clean_db():
    from app.db import session_scope

    with session_scope() as s:
        s.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY"))
        for t in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
            s.execute(text(f"TRUNCATE {t}"))
    yield


@pytest.fixture
def session():
    from app.db import session_scope

    with session_scope() as s:
        yield s

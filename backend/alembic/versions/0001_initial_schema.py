"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-26 06:54:48.466900
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.create_table('agent_runs',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('break_id', sa.BigInteger(), nullable=False),
    sa.Column('thread_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('specialist', sa.String(length=32), nullable=True),
    sa.Column('model', sa.String(length=80), nullable=True),
    sa.Column('trace', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('proposal', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('outcome', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('thread_id')
    )
    op.create_index(op.f('ix_agent_runs_break_id'), 'agent_runs', ['break_id'], unique=False)
    op.create_index(op.f('ix_agent_runs_status'), 'agent_runs', ['status'], unique=False)
    op.create_table('approvals',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agent_run_id', sa.BigInteger(), nullable=False),
    sa.Column('break_id', sa.BigInteger(), nullable=False),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('proposal', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('policy_version', sa.Integer(), nullable=False),
    sa.Column('policy_decision', sa.String(length=16), nullable=False),
    sa.Column('policy_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('decided_by', sa.String(length=120), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('execution_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key')
    )
    op.create_index(op.f('ix_approvals_agent_run_id'), 'approvals', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_approvals_break_id'), 'approvals', ['break_id'], unique=False)
    op.create_index(op.f('ix_approvals_status'), 'approvals', ['status'], unique=False)
    op.create_table('authorizations',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('order_id', sa.String(length=80), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_event_id', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_authorizations_order_id'), 'authorizations', ['order_id'], unique=False)
    op.create_table('breaks',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('fingerprint', sa.String(length=200), nullable=False),
    sa.Column('rule', sa.String(length=48), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('resource_type', sa.String(length=24), nullable=False),
    sa.Column('resource_id', sa.String(length=80), nullable=False),
    sa.Column('correlation_id', sa.String(length=80), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('expected', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('observed', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('delta_minor', sa.BigInteger(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolution', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('fingerprint')
    )
    op.create_index(op.f('ix_breaks_correlation_id'), 'breaks', ['correlation_id'], unique=False)
    op.create_index(op.f('ix_breaks_rule'), 'breaks', ['rule'], unique=False)
    op.create_index(op.f('ix_breaks_status'), 'breaks', ['status'], unique=False)
    op.create_table('captures',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('order_id', sa.String(length=80), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('fee_minor', sa.BigInteger(), nullable=True),
    sa.Column('net_minor', sa.BigInteger(), nullable=True),
    sa.Column('final_capture', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_event_id', sa.BigInteger(), nullable=False),
    sa.Column('api_status', sa.String(length=24), nullable=True),
    sa.Column('api_amount_minor', sa.BigInteger(), nullable=True),
    sa.Column('settled_tx_id', sa.String(length=80), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_captures_order_id'), 'captures', ['order_id'], unique=False)
    op.create_table('disputes',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('transaction_id', sa.String(length=80), nullable=True),
    sa.Column('order_id', sa.String(length=80), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('reason', sa.String(length=60), nullable=True),
    sa.Column('stage', sa.String(length=40), nullable=True),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('seller_response_due', sa.DateTime(timezone=True), nullable=True),
    sa.Column('evidence_submitted', sa.Boolean(), nullable=False),
    sa.Column('outcome', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_event_id', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_disputes_order_id'), 'disputes', ['order_id'], unique=False)
    op.create_index(op.f('ix_disputes_transaction_id'), 'disputes', ['transaction_id'], unique=False)
    op.create_table('invoices',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('invoice_number', sa.String(length=80), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('recipient_email', sa.String(length=200), nullable=True),
    sa.Column('paid_amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_event_id', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('jobs',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('dedupe_key', sa.String(length=200), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kind', 'dedupe_key', name='uq_jobs_kind_dedupe')
    )
    op.create_index(op.f('ix_jobs_kind'), 'jobs', ['kind'], unique=False)
    op.create_index(op.f('ix_jobs_run_after'), 'jobs', ['run_after'], unique=False)
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_table('ledger_events',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('event_key', sa.String(length=200), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('event_type', sa.String(length=40), nullable=False),
    sa.Column('resource_type', sa.String(length=24), nullable=False),
    sa.Column('resource_id', sa.String(length=80), nullable=False),
    sa.Column('correlation_id', sa.String(length=80), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_key')
    )
    op.create_index('ix_ledger_corr', 'ledger_events', ['correlation_id'], unique=False)
    op.create_index('ix_ledger_occurred', 'ledger_events', ['occurred_at'], unique=False)
    op.create_index('ix_ledger_resource', 'ledger_events', ['resource_type', 'resource_id'], unique=False)
    op.create_table('orders',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('intent', sa.String(length=16), nullable=True),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('payer_email', sa.String(length=200), nullable=True),
    sa.Column('payer_id', sa.String(length=40), nullable=True),
    sa.Column('custom_id', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_event_id', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('payout_items',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('batch_id', sa.String(length=80), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('fee_minor', sa.BigInteger(), nullable=True),
    sa.Column('receiver', sa.String(length=200), nullable=True),
    sa.Column('sender_item_id', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_event_id', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_payout_items_batch_id'), 'payout_items', ['batch_id'], unique=False)
    op.create_table('refunds',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('capture_id', sa.String(length=80), nullable=True),
    sa.Column('order_id', sa.String(length=80), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_event_id', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_refunds_capture_id'), 'refunds', ['capture_id'], unique=False)
    op.create_index(op.f('ix_refunds_order_id'), 'refunds', ['order_id'], unique=False)
    op.create_table('transactions',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('event_code', sa.String(length=8), nullable=True),
    sa.Column('status', sa.String(length=4), nullable=True),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('fee_minor', sa.BigInteger(), nullable=True),
    sa.Column('paypal_reference_id', sa.String(length=80), nullable=True),
    sa.Column('initiated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_event_id', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transactions_paypal_reference_id'), 'transactions', ['paypal_reference_id'], unique=False)
    op.create_table('webhook_inbox',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('paypal_event_id', sa.String(length=64), nullable=False),
    sa.Column('event_type', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('headers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('paypal_event_id')
    )
    op.create_index(op.f('ix_webhook_inbox_event_type'), 'webhook_inbox', ['event_type'], unique=False)



def downgrade() -> None:

    op.drop_index(op.f('ix_webhook_inbox_event_type'), table_name='webhook_inbox')
    op.drop_table('webhook_inbox')
    op.drop_index(op.f('ix_transactions_paypal_reference_id'), table_name='transactions')
    op.drop_table('transactions')
    op.drop_index(op.f('ix_refunds_order_id'), table_name='refunds')
    op.drop_index(op.f('ix_refunds_capture_id'), table_name='refunds')
    op.drop_table('refunds')
    op.drop_index(op.f('ix_payout_items_batch_id'), table_name='payout_items')
    op.drop_table('payout_items')
    op.drop_table('orders')
    op.drop_index('ix_ledger_resource', table_name='ledger_events')
    op.drop_index('ix_ledger_occurred', table_name='ledger_events')
    op.drop_index('ix_ledger_corr', table_name='ledger_events')
    op.drop_table('ledger_events')
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_run_after'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_kind'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_table('invoices')
    op.drop_index(op.f('ix_disputes_transaction_id'), table_name='disputes')
    op.drop_index(op.f('ix_disputes_order_id'), table_name='disputes')
    op.drop_table('disputes')
    op.drop_index(op.f('ix_captures_order_id'), table_name='captures')
    op.drop_table('captures')
    op.drop_index(op.f('ix_breaks_status'), table_name='breaks')
    op.drop_index(op.f('ix_breaks_rule'), table_name='breaks')
    op.drop_index(op.f('ix_breaks_correlation_id'), table_name='breaks')
    op.drop_table('breaks')
    op.drop_index(op.f('ix_authorizations_order_id'), table_name='authorizations')
    op.drop_table('authorizations')
    op.drop_index(op.f('ix_approvals_status'), table_name='approvals')
    op.drop_index(op.f('ix_approvals_break_id'), table_name='approvals')
    op.drop_index(op.f('ix_approvals_agent_run_id'), table_name='approvals')
    op.drop_table('approvals')
    op.drop_index(op.f('ix_agent_runs_status'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_break_id'), table_name='agent_runs')
    op.drop_table('agent_runs')


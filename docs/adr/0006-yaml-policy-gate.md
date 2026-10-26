# ADR 0006 — Deterministic YAML policy between proposal and execution

**Status:** accepted · **Date:** 2026-10

## Context

Which actions may run unattended is a merchant decision, not a model decision, and it must be
auditable after the fact: "why did this refund go out at 2 a.m. with nobody watching?"

Putting the rule in the prompt ("only auto-refund under $25") is not a control; a model can
misread it, and nobody can prove what version of the prompt was in force.

## Decision

`policy.yaml` is a versioned file shipped with the code. The `policy_gate` node is plain
Python: it reads the proposal and the ledger, evaluates the policy, and returns `auto` or
`requires_human` with a list of reasons. The approval row stores the policy version and the
reasons. Changing the policy is a commit, reviewed like any other code.

The policy expresses: per-action auto-approve limits (amount ceiling, order age, exclusions
such as an open dispute, a prior refund, a blocklisted payer), a hard list of actions that
never run unattended, a global refund ceiling even for humans, and a confidence floor below
which nothing runs unattended.

## Consequences

* The model's confidence is an input to the gate, never the gate itself.
* Every unattended action can be explained with a file version and three reasons.
* Merchants cannot edit policy from the console in this build. Accepted for auditability; a
  console editor that writes a new policy *version* (not an edit in place) is the planned
  path.

# F-Selling project instructions

Superpowers handles planning and execution when explicitly invoked. This file
only defines repository-wide safety and verification boundaries.

## Safety

- Do not read or modify `.env`, databases, user data, uploads, or sensitive logs.
- Preserve unrelated and user-owned changes.
- Codex may stage exactly the files changed for the current task and commit them
  automatically after the required verification passes. Never include unrelated
  or user-owned changes in that commit.
- Do not push, deploy, or change external services unless the user explicitly
  requests that action.
- Do not run `test-commit.ps1` automatically; it runs the full suite, stages all
  changes, and commits.

## Context

- Read only the relevant sections of `KIEN_TRUC.md` for the area being changed.
- Treat money, payments, debt, permissions, data integrity, and migrations as
  high-risk; preserve their invariants and focused regression coverage.

## Verification

- After a group of edits, run syntax checks and focused tests for the changed
  area.
- Before finishing, run regression tests appropriate to the task scope.
- Run the full suite once before merge/release, or when shared high-risk code
  changes. When a full suite is required, do not start or poll it from Codex.
  Give the user this command to run in their own terminal instead:

  `.\test-commit.ps1 -TestOnly`

  Wait for the user to report exit code 0. If relevant code has not changed
  since that successful run, accept the result, do not rerun it, and commit
  automatically.
- For ordinary scoped changes, focused tests are sufficient before the automatic
  commit; do not require the full suite for every commit.
- Do not rerun a passing test when relevant code has not changed.
- Use browser UAT only when UI or browser behavior changes.
- For any shorter test Codex runs itself, wait on one process with backoff; do
  not poll continuously or start duplicate runs.

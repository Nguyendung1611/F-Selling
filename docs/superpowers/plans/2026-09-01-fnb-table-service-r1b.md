# F&B Table Service R1B — Implementation Plan

Date: 2026-09-01

## Outcome

Extend the committed R1A session flow with product stations, atomic batch send,
Kitchen/Bar queues, exact stock/cost provenance, sent-item cancellation and
one-use manager approval. Retail POS, R1C checkout, deployment, Gemini and TTS
remain outside this plan.

## Minimal architecture

- Reuse the existing shop write lock, session revision, operation fingerprint,
  action log and HTTP polling. Do not add WebSocket, a job queue or a new POS
  controller.
- Add `Product.fnb_station` and snapshot station on each session line.
- A send transaction groups every currently unsent quantity by station, checks
  all stock before writing, deducts exact Product/batch cost pools once, creates
  at most one Kitchen ticket and one Bar ticket, records Direct allocations,
  then advances line/session/floor revisions.
- Allocation rows are immutable provenance. Partial cancellation splits the
  affected provenance deterministically; it never guesses a replacement batch.
- Add KITCHEN and BAR staff presets. Owner/MANAGER may view either queue.
- Manager approval tokens are random, stored hashed, one-use, short-lived and
  bound to actor/shop/action/session/revision. PIN values are bcrypt hashes and
  never enter logs or responses.

## Task 1 — schema and invariants

- Migration `0010_fnb_kitchen_stock_r1b` and ORM models.
- Add product station; line station/sent counters; tickets/items; stock
  allocations; manager PIN hash and one-use approval records.
- Verifier rejects invalid stations/statuses, cross-shop references, sent/cancel
  counters outside their bounds, duplicate ticket sequence and invalid
  allocation state/source.
- TDD: migration/head/checksum/model tests red then green.

## Task 2 — station, send and queue API

- `PATCH /api/fnb/menu-items/{product_id}/station`.
- `POST /api/fnb/sessions/{session_id}/send`.
- `GET /api/fnb/stations/{station}/tickets?shop_id=&after_revision=`.
- `POST /api/fnb/tickets/{ticket_id}/start|done|out-of-stock`.
- Gate: all-or-nothing stock check, retry does not duplicate tickets or stock,
  Kitchen/Bar isolation, stale revision returns authoritative snapshot.

## Task 3 — sent cancellation and manager approval

- Configure/rotate a manager PIN for the authenticated owner/MANAGER.
- Issue a one-use approval for a bound cancellation after constant-time/bcrypt
  verification and rate limiting.
- Unsent cancellation remains the R1A path. Sent NEW quantities restore their
  exact Product/batch allocation. IN_PROGRESS/DONE requires approval and an
  explicit `RESTOCK` or `WASTE` decision plus reason.
- Gate: partial cancellation preserves cost totals; retry never restores twice;
  no PIN/approval token is logged in action payloads.

## Task 4 — UI and release gate

- Replace the disabled R1B CTA with `Gửi Bếp/Bar`; show unsent and sent sections
  without allowing sent quantity/note edits.
- Add `/fnb/station/{kitchen|bar}` responsive queue with `Nhận làm`, `Xong` and
  `Báo hết món`, including loading/empty/poll-error/offline/conflict states.
- Add owner product-station editing and staff-role choices for Kitchen/Bar.
- Browser smoke: multi-tab send, queue convergence, timeout retry, long content,
  320px/200% zoom and permission loss.
- Focused tests, provider/config OFF gates, then mandatory `test-commit.ps1`.

## Fortify state contract

| State | User sees | Recovery |
| --- | --- | --- |
| No unsent items | Send button disabled with explanation | Add a new item |
| Sending | Only send controls disabled; explicit status | Wait; no optimistic success |
| Timeout/offline | Items remain `Chưa gửi` | Retry same operation ID |
| Insufficient stock | Exact item and available quantity | Edit/cancel draft, resend |
| Revision conflict | Latest session plus retained draft | Review then send again |
| Empty queue | `Chưa có phiếu mới` | Poll continues |
| Queue poll error | Existing tickets stay visible | Manual retry |
| Ticket changed elsewhere | Latest ticket state | Continue from allowed action |
| Sent cancellation | Impact on stock is explicit | PIN flow only when required |

## Boundaries

No bill/check/payment, Order creation, inventory deduction at payment, kitchen
printer, recipe ingredients, offline confirmation, deployment, AI provider or
TTS runtime changes.

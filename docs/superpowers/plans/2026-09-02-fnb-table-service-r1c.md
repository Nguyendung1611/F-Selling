# F&B Table Service R1C — Implementation Plan

## Scope

Complete the approved R1 contract with temporary checks, split-by-item/quantity,
per-check discount and service charge, checkout into the existing Order/payment
ledger without deducting stock twice, and safe table closure.

## Tasks

1. Add forward-only revision 0011 and models for service checks, check lines and
   immutable allocation-to-order transfers.
2. Add checkout permission plus strict request schemas and tenant-safe routes.
3. Implement check creation/read, split preview/confirm and adjustments using
   integer VND, revisions and the existing F&B operation log.
4. Implement cash, transfer and debt checkout. Build Order/OrderItem provenance
   from R1B allocations; never call retail `create_order()` or deduct inventory.
5. Synchronize transfer payment status, close only fully settled sessions, and
   keep new sent/cancelled quantities coherent with the main open check.
6. Add the smallest UI needed to print a clearly marked temporary check, split,
   adjust, pay and close; retain polling, retry and offline/error states.
7. Run migration/API/UI focused tests, browser smoke and the mandatory full gate.

## Non-goals

- No provider, deployment, billing, WebSocket, job queue or new dependency.
- No changes to retail POS stock deduction.
- No tax/e-invoice claim; the pre-payment document is a temporary check only.


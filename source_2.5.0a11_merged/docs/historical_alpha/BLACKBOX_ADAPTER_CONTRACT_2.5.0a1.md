# Wallet / BlackBox Adapter Contract — 2.5.0a5

## Ownership

- BlackBox owns canonical validation, append-only storage, chain verification, closed views, and append receipts.
- Wallet owns custody policy, Human Intent, event meaning, redaction, delivery requirements, and the durable Wallet outbox.
- Oubliette owns static inspection meaning through its own adapter but never custody authority.

## Client contract

Wallet depends on `bbx1-client/1` through:

- capability discovery;
- event submission;
- recorder status;
- canonical verification;
- append-receipt verification.

The current transport is local and in-process. Hosts do not access evidence files directly through the client contract.

## Delivery states

- `acknowledged`: BlackBox accepted the fact and Wallet persisted the acknowledgement.
- `pending`: delivery was unavailable or temporarily failed; the fact remains in the verified outbox.
- `rejected`: BlackBox permanently rejected the fact or operation conflict; it is not retried silently.
- `not_configured`: no witness client is attached; program policy decides whether the originating operation may continue.
- acknowledgement persistence failure: BlackBox accepted the fact, but Wallet did not persist the local acknowledgement. Retry is idempotent and must resolve to the original canonical record.

## Authority

The adapter cannot mint Human Intent, move custody, promote a generation, or decide trust. It may translate and deliver facts only.

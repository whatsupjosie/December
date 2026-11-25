# BlackBox Plugin Architecture — Current Canonical View

## Authority direction

```text
Human identity / intent / ceremony
            |
            v
Wallet Gatekeeper ----authorizes----> Wallet custody transition
            |                                  |
            |                                  +--> Candidate / Prime / Removed / Quarantine / Release
            |
            +--> Wallet receipt service (BBX-005 target)
                         |
                         v
Host fact adapters --> typed envelopes --> BBX recorder --> checkpoints / seal / derived views
                                                |
                                                +--> durable outbox / coverage gaps (BBX-007 target)

Oubliette static findings --> typed quarantine request --> Wallet custody transition
External Laboratory <----- traceable exported copy ----- Wallet
Returned external result -------------------------------> new Candidate only

Local reference comparator --> static local consistency report
Separate external witness --> optional future independent authentication
```

## Canonical ownership

- `blackbox_plugin` owns evidence framing, sequence, hash links, append authority, verification, checkpoints, seals, and derived views.
- Iteration Wallet owns custody state and protected operations.
- The connector translates typed host facts; it does not write segments directly or gain custody authority.
- Oubliette does not own file movement or a second evidence chain.
- PubCast and Pub Manager are future event producers, not evidence owners.

## Recorder P0

The current recorder validates storage identifiers, contains resolved paths, reloads the verified canonical tail under an interprocess lock, rebuilds operation state from records, writes unique derived-state temporaries, and creates checkpoints and seals with exclusive-create semantics.

The canonical record is a framed BBX1 line:

```text
BBX1|<urlsafe-base64 canonical JSON>|<sha256>
```

`active_state.json` is a derived cache. The verified segment tail is authoritative.

## Current compatibility boundary

`WalletBlackBoxCompat.write_event()` is a transitional host-fact path.

`WalletBlackBoxCompat.issue_human_intent_receipt()` is **not authoritative** and must not be used for protected operations. It remains only until BBX-005 replaces it with the Wallet-owned identity/Gatekeeper/ceremony/result/receipt/anchor protocol.

## Closed views

Current generic closed payload filtering is a known failed Candidate surface. BBX-006 replaces it with event-specific default-deny projectors and metadata-only behavior for unknown event types.

## Local reference comparator

`IntegritySentinel` is a compatibility name for a local read-only comparator. It records local file size/hash facts and compares later inert trees. It does not execute, repair, independently authenticate, or protect against an actor able to rewrite both target and manifest.

A future independent witness requires a separately controlled authority, signing key, external checkpoint service, or separate Wallet.

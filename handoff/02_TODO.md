# TODO — prioritized

## Closed in the 2026-07-27 continuation

1. The real suites ran: **322 Wallet tests** and **43 BlackBox tests** passed.
2. `/vault/open` and `/vault/lock` are covered by the complete regression suite,
   and every browser caller now supplies the required request body.
3. `vault_id` is wired into the Retire role-policy call site and has a
   non-owner denial regression test.
4. `static/app.html` was inspected for all Vault-open call sites, repaired, and
   passed JavaScript syntax plus the 27-check source verifier.

## P0 — remaining market-release security work

1. Replace the self-asserted local identity issuer with a production provider
   or a passkey-bound owner identity ceremony.
2. Bind first-passkey enrollment to a separately delivered setup secret or
   equivalent owner bootstrap.
3. Complete physical Windows Hello, phone-hybrid, and multi-vendor FIDO2 tests.
4. Deploy the Windows service identity/NTFS ACL custody boundary and signed
   installer/update lifecycle.
5. Implement and rehearse sealed-vault recovery, then complete independent
   penetration, accessibility, and field-recovery testing.

## P1 — the UI idea you raised
You pointed at the vault/typewriter illustration and asked about a hotspot-style interface —
click the vault wheel to request vault-open, click the cradle to open it, etc. I think it's a
good direction and worth building, but I did not start it this session for two reasons: it's a
substantial standalone frontend effort (the illustration is static art, not a component library —
someone has to decide what's a real clickable hotspot vs. decorative background, build the actual
state machine behind each hotspot, and wire it to the now-freshly-changed `/vault/open`/
`/vault/lock` request bodies), and this session's tokens were committed to the security fixes,
which were the more time-sensitive gap. Recommend scoping it as its own session: start from the
existing `iteration_wallet/static/app.html` (already has passkey-gate and vault-state UI, just
not in this illustrated style) rather than from a blank page.

## Reviewed and closed — no action needed
The rest of the divergence between the two source zips was reviewed file-by-file this session
and confirmed to be either pure forward-evolution (nothing lost) or cosmetic wording. Full detail
in `../evidence/LINEAGE_DIVERGENCE_INVENTORY.md`: `vault_v21.py`, `server.py` (beyond the vault
routes), `passkey_gate.py`, `private_alpha_runner.py` (beyond the 2 call sites), `cli.py` (beyond
the vault flows), `durable_io.py`, `intake_capsule.py`, `vault.py`, `runtime_continuity.py`,
`__init__.py`. Nothing here should need revisiting unless new information surfaces.

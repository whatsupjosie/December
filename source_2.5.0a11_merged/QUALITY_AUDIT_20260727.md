# Iteration Wallet 2.5.0a11 market-readiness quality audit

Date: 2026-07-27
Scope: active Wallet source, standalone BlackBox source, adapter, browser UI,
launchers, tests, release metadata, and built wheels.

## Outcome

The active tree was inventoried and structurally scanned in full: 131 Python
files and 191 text/configuration files. Release-critical authentication,
authorization, custody transactions, durable I/O, recovery, browser/API
contracts, packaging, and launch paths received targeted manual review.

No runtime pass/ellipsis stubs, unresolved work markers, duplicate definitions,
mutable default arguments, wildcard imports, parse failures, hidden control
characters, or dead static DOM references remain in the active release tree.
Ellipsis bodies that remain are methods on typed `Protocol` interfaces; they
declare contracts and are not executable placeholder implementations.

## Corrections made

1. Replaced two production `assert` invariants with explicit fail-closed errors.
   They now remain effective under `python -O`.
2. Required the BlackBox compatibility adapter to prove both acknowledged
   status and a durable receipt before returning event data.
3. Made base64url decoding reject noncanonical characters and made malformed
   Unicode hardware-gate tokens fail through `PasskeyGateError`.
4. Converted invalid WebAuthn credential algorithms into controlled gate
   failures instead of uncaught conversion errors.
5. Standardized active Wallet timestamps on timezone-aware UTC values. Older
   offset-free notification records are normalized deterministically on read.
6. Removed 18 verified unused imports/assignments.
7. Removed trailing whitespace, restored final newlines, and corrected stale
   transaction-availability documentation.
8. Added repeatable quality regression tests so these defects cannot silently
   return.

## Three-way evaluation of merely-okay code

| Area | Option 1 | Option 2 | Option 3 | Decision |
|---|---|---|---|---|
| Internal invariants | Keep `assert` | Explicit runtime guard | Redesign types to make state unrepresentable | Explicit guard now; type redesign is larger and riskier |
| Base64url input | Keep permissive decoder | Strict canonical decoder | Introduce dedicated encoded-value types throughout | Strict decoder gives the safest bounded change |
| Time values | Keep local naive time | Explicit UTC offsets | Inject a clock into every component | UTC now; clock injection is a future architectural change |
| Interface contracts | Ellipsis `Protocol` methods | Abstract base classes | Concrete no-op implementations | Keep `Protocol`; no-op code would fabricate functionality |
| Large transaction methods | Leave intact | Extract pure verification helpers | Redesign transaction state machines | Leave stable, heavily fault-tested paths intact for this alpha; redesign only as a versioned migration |

## Verification evidence

- Wallet suite: **330 passed**
- Standalone BlackBox suite: **43 passed**
- Source-bundle verifier: **27/27 passed**
- Focused quality/passkey regression suite: **30 passed**
- Python unused-symbol scan: **0 findings**
- Browser JavaScript syntax: **passed**
- Clean rebuilt-wheel import and `iw doctor`: **passed**
- Live loopback UI/capability/passkey HTTP smoke: **passed**

## Honest release boundary

The reviewed code is stable enough for the existing hardened-alpha boundary,
but this audit does not convert the product into a certified hostile-environment
release. The first-passkey bootstrap, provider-neutral local identity issuer,
physical multi-vendor authenticator validation, Windows service/ACL deployment,
signed installer/update lifecycle, sealed-vault recovery, independent
penetration testing, accessibility testing, and field recovery rehearsal remain
external release blockers. See `KNOWN_LIMITATIONS_2.5.0a11.md`.

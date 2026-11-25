# Product Wrap-Up Status — Iteration Wallet 2.5.0a5 / BlackBox 0.6.0a2

## Active alpha claim

Iteration Wallet is a local-first custody tool for AI-assisted project files. This alpha proves the backend custody spine: project/section creation, Raw Source and Candidate intake, Human Intent promotion to Prime, HMAC-authenticated LabCopy export and re-entry, static Oubliette inspection, Wallet-owned quarantine, BlackBox evidence recording, custody verification, and restart verification.

## Interface claim

The CLI is the official alpha operator surface. The browser UI/server exists and starts when runtime dependencies are installed, but browser interaction is not the primary demonstrated interface in this build.

## Fixed in 2.5.0a5 / 0.6.0a2

- `iw doctor` now checks runtime dependencies required by `iw serve` instead of only package ownership.
- `iw serve --root PATH` sets the Wallet runtime storage root for that server process.
- `tools/migrate_alpha_install.py` is included for legacy overlapping-wheel repairs.
- BlackBox Sentinel CLI accepts `--human-actor josie` by normalizing it to `human:josie` and reports controlled errors instead of raw tracebacks.
- Documentation states that offline installation requires a dependency wheelhouse; this bundle contains only project wheels.

## Known limitations

- Remove / restore / release protected actions deliberately fail closed and are not part of the alpha demo.
- Runtime Continuity is implemented and tested as a library, but not exposed as the primary user flow.
- Windows runtime behavior is not proven; POSIX behavior is tested.
- Browser UI automation is not proven.
- Local BlackBox/Sentinel verification is local consistency only, not independent external witnessing.

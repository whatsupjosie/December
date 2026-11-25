# BlackBox Changelog

## 0.6.0a2 — Neutral standalone recorder boundary

- Added the `bbx1-client/1` protocol and tested `LocalBlackBoxClient`.
- Added capability, status, and append-receipt verification CLI commands.
- Removed Wallet, PubCast, and Pub Manager adapters from the installed BlackBox package.
- Preserved host-specific donor code under `reference_source/`.
- Left canonical record validation, storage, views, migration, and verification in the standalone core.

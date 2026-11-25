# FILE MANIFEST — this package

```
IterationWallet_2.5.0a11_MERGED_HARDENED_20260725/
├── handoff/
│   ├── 00_START_HERE.md          ← read first
│   ├── 01_VERIFIED_STATE.md      ← what's fixed, verified, and not
│   ├── 02_TODO.md                ← prioritized next steps
│   ├── 03_FILE_MANIFEST.md       ← this file
│   └── 04_SECURITY_DEBUG_CONTINUATION_20260727.md ← latest authoritative handoff
├── evidence/
│   ├── LINEAGE_DIVERGENCE_INVENTORY.md   ← every differing file, individually reviewed, verdict + action
│   ├── manual_verify_approval_decision_fix.py           ← run it: python3 manual_verify_approval_decision_fix.py
│   ├── manual_verify_approval_decision_fix_OUTPUT.txt    ← 9/9 passed
│   ├── manual_verify_gatekeeper_approval_gate_fix.py     ← run it: python3 manual_verify_gatekeeper_approval_gate_fix.py
│   └── manual_verify_gatekeeper_approval_gate_fix_OUTPUT.txt   ← 2/2 passed
└── source_2.5.0a11_merged/       ← the merged, patched, installable source tree
    ├── iteration_wallet/          ← the package; notification_manager.py, server.py, and gatekeeper.py carry this work's fixes
    ├── iteration_wallet_blackbox/ ← local adapter package (this is what made the other lineage un-importable — present here)
    ├── blackbox_source/
    ├── dist/
    │   ├── iteration_wallet-2.5.0a11-py3-none-any.whl        ← freshly rebuilt, contains both fixes (verified)
    │   └── bbx1_iteration_wallet_plugin-0.6.0a4-py3-none-any.whl
    ├── tests/                     ← includes the 2026-07-27 security follow-up regressions
    ├── tools/                     ← 2 files updated for the vault fix
    ├── docs/                      ← carried over unmodified from the source tree
    ├── setup.py, requirements.txt, pytest.ini
    ├── app.py, START_ITERATION_WALLET.{bat,ps1}
    ├── CHANGELOG.md, README.md, INSTALLATION.md   ← carried over unmodified; do not yet reflect this session's fixes
    └── KNOWN_LIMITATIONS_2.5.0a11.md, SECURITY_BOUNDARY_2.5.0a11.md   ← carried over unmodified; the vault-open/lock gap
        these describe as a limitation is now fixed here — update these docs once the fix is
        live-verified (see 02_TODO.md P0)
```

## What's deliberately not in this package

- The two original uploaded zips themselves — you already have those; re-including them would
  roughly double the package size for no new information. Everything useful that was in them is
  either in `source_2.5.0a11_merged/` or documented in `evidence/LINEAGE_DIVERGENCE_INVENTORY.md`.
- `RVF_HANDOFF_TO_NEXT_AGENT_20260726.zip` and `731_night_i_handoff.zip` were duplicates of each
  other (confirmed by hash) — only the content, not the raw zips, is reflected here.
- `files__60_.zip` and `930am_currnt_prime_iw_bb.zip` are build `2.5.0a10` ("Continuous Agent UI +
  Passkey Gate") — confirmed the direct ancestor that `source_2.5.0a11_patched` was built from
  (per the RVF handoff's own account: a11 = a10 + the vault fix). Superseded by this package.
  One thing in `930am_currnt_prime_iw_bb.zip` that hasn't been evaluated: a sibling
  `pubcast_blackbox_adapter/` folder alongside the wallet source, not part of `iteration_wallet`
  itself. Not reviewed — flagging in case it's something you still want, since it wasn't present
  in either of the two `a11` lineages and would otherwise get lost.

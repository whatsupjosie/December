# iteration-wallet

Her words about these branches: "Main is for them all to be buddies and work together. Their own folders are for them, so they are separate individuals ready to go and do what we need without everyone else's baggage."

## What is here

At the top of this branch is Iteration Wallet 2.5.0a11, the frozen pre-beta build. Its handoff/ folder says the full suites were run on 2026-07-27: 322 Wallet tests, 43 BlackBox tests and 27/27 source checks passed. Those runs are the handoff's claim; they were not rerun here.

- `source_2.5.0a11_merged/`: the Wallet source, its pinned Black Box copy (blackbox_source/, iteration_wallet_blackbox/), tests, docs, the built wheels in dist/, and the Windows starters START_ITERATION_WALLET.bat and .ps1.
- `handoff/`: the six handoff notes that came with it (start here: 00_START_HERE.md).
- `evidence/`: the lineage inventory and the two manual verification scripts with their outputs.
- `pubcast-copy-2.1/`: the older 2.1 copy of the Wallet that lived inside PubCast (iteration_wallet/, docs/iteration_wallet/, one static test), kept at its PubCast paths under this folder so the two versions do not collide. It is older than 2.5.0a11.

## Where it came from

- 2.5.0a11: the zip `Frozen_Iteration_Wallet_Pre-Beta_Snapshot_v2.5.0a11_2026-07-28_12-45-49_PDT.zip` in the 6.0- repo (main, commit bb20a0c). Unpacked as it was; no file inside was changed. The other wallet zips and wheels in 6.0- are older and were not brought in.
- pubcast-copy-2.1: pre-dec branch `claude/integrate-strongest-parts-2026-11-24` at d727f09.

This branch starts fresh (no shared history with main). Nothing was deleted from 6.0-, pre-dec or Beyond-October.

## What it still needs from other branches to run on its own

Nothing found. Its Python files import nothing from any other December branch. Its Black Box is its own pinned copy (see source_2.5.0a11_merged/BLACKBOX_DEPENDENCY_PIN.json), not the blackbox branch.

## Still open, from her earlier notes

The Foresight Counter tray frame blocks passkeys. A two-permission fix was tested in Chrome and not applied.

## Working rule

Never `git merge` this branch into main-assembly or the other way round. Copy files by path. The map of where main-assembly expects the Wallet is in main-assembly at handoffs/DECEMBER_PLUG_POINTS_2026-11-25.md.

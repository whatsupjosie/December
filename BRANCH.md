# code-collector

Her words about these branches: "Main is for them all to be buddies and work together. Their own folders are for them, so they are separate individuals ready to go and do what we need without everyone else's baggage."

## What is here

Code Collector: the code_collector/ folder (an Electron app and browser extension) and its memory store modules/cc_memory_store.py. The broken link code_collector/node_modules points to a scratch path on another machine. It was kept exactly as it was, because she said "Not yet" to removing it.

## Where it came from

Every file here is copied exactly from pre-dec branch `claude/integrate-strongest-parts-2026-11-24` at commit d727f09 (its newest state at 04:26 UTC, Nov 25), with `claude/liars-dice-bar-2026-11-24` (736273e) merged on top in a local working copy. This branch starts fresh (it shares no history with main), so the history of each file is in main-assembly's history and in pre-dec. Nothing was deleted from pre-dec or Beyond-October.

## What it still needs from other branches to run on its own

Found by parsing the import lines of every Python file here (read by script, not run). It cannot run alone until these are beside it or replaced:

Nothing. Its Python files import nothing from any other branch.

## Working rule

Never `git merge` this branch into main-assembly or the other way round: the branches hold different sets of files on purpose. To bring a file across, copy it by path (for example `git checkout code-collector -- <path>`). The full map of where main-assembly expects this program is in main-assembly at handoffs/DECEMBER_PLUG_POINTS_2026-11-25.md.

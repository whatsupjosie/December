# blackbox

Her words about these branches: "Main is for them all to be buddies and work together. Their own folders are for them, so they are separate individuals ready to go and do what we need without everyone else's baggage."

## What is here

Black Box: the event language, recorder, decoder, runtime witness, chat replay, media, retention policy and routes, Blackbox Light archive and search (modules/pubpartner_blackbox_light.py), the browser client and audio worklet, tools, experiments and tests. The July Black Box Part 2 candidates and the bbx1 plugin wheel in the 6.0- repo were not brought in: they are older, and the Iteration Wallet carries its own pinned copy (see the iteration-wallet branch).

## Where it came from

Every file here is copied exactly from pre-dec branch `claude/integrate-strongest-parts-2026-11-24` at commit d727f09 (its newest state at 04:26 UTC, Nov 25), with `claude/liars-dice-bar-2026-11-24` (736273e) merged on top in a local working copy. This branch starts fresh (it shares no history with main), so the history of each file is in main-assembly's history and in pre-dec. Nothing was deleted from pre-dec or Beyond-October.

## What it still needs from other branches to run on its own

Found by parsing the import lines of every Python file here (read by script, not run). It cannot run alone until these are beside it or replaced:

From the main-assembly branch (11 files):

- `modules/__init__.py`
- `modules/auth.py`
- `modules/bots.py`
- `modules/chat_commit_store.py`
- `modules/conversation_archive.py`
- `modules/dressing_room_security.py`
- `modules/hub.py`
- `modules/models.py`
- `modules/route_security.py`
- `tests/host_lifespan_helpers.py`
- `tests/test_communications_capture.py`

From the alex branch (1 files):

- `modules/alex_jeremy_bridge.py`

From the pubpartner branch (2 files):

- `modules/pubpartner_backup.py`
- `modules/pubpartner_core.py`

## Working rule

Never `git merge` this branch into main-assembly or the other way round: the branches hold different sets of files on purpose. To bring a file across, copy it by path (for example `git checkout blackbox -- <path>`). The full map of where main-assembly expects this program is in main-assembly at handoffs/DECEMBER_PLUG_POINTS_2026-11-25.md.

# 2i

Her words about these branches: "Main is for them all to be buddies and work together. Their own folders are for them, so they are separate individuals ready to go and do what we need without everyone else's baggage."

## What is here

2i, the writing program (Writer's Room): the 2i/ folder, its offline launcher and Windows desktop app, its spell and language data builders, its backend (2i-backend/), the server pieces modules/writers_room.py, modules/manuscript_intelligence.py and modules/twoi_rich_document.py, the typewriter console pages, and the 2i tests, docs, handoffs and evidence. The two GitHub workflow files under .github/workflows/ came with it. Their push triggers name only two old Codex branches that do not exist in December, so they do not run on any December branch; they can only be started by hand.

## Where it came from

Every file here is copied exactly from pre-dec branch `claude/integrate-strongest-parts-2026-11-24` at commit d727f09 (its newest state at 04:26 UTC, Nov 25), with `claude/liars-dice-bar-2026-11-24` (736273e) merged on top in a local working copy. This branch starts fresh (it shares no history with main), so the history of each file is in main-assembly's history and in pre-dec. Nothing was deleted from pre-dec or Beyond-October.

## What it still needs from other branches to run on its own

Found by parsing the import lines of every Python file here (read by script, not run). It cannot run alone until these are beside it or replaced:

From the main-assembly branch (15 files):

- `main.py`
- `modules/__init__.py`
- `modules/auth.py`
- `modules/auth_routes.py`
- `modules/character_service.py`
- `modules/chat_rooms.py`
- `modules/conversation_routes.py`
- `modules/foresight_file_formats.py`
- `modules/foresight_workspace.py`
- `modules/hub.py`
- `modules/local_model_config.py`
- `modules/route_security.py`
- `modules/userdb.py`
- `tests/test_data_checkpoint_host_recovery.py`
- `tests/test_foresight_file_workspace.py`

From the pubpartner branch (5 files):

- `modules/pubpartner_core.py`
- `modules/pubpartner_provider.py`
- `modules/pubpartner_routes.py`
- `modules/pubpartner_vessel/__init__.py`
- `pubpartner_app.py`

## Working rule

Never `git merge` this branch into main-assembly or the other way round: the branches hold different sets of files on purpose. To bring a file across, copy it by path (for example `git checkout 2i -- <path>`). The full map of where main-assembly expects this program is in main-assembly at handoffs/DECEMBER_PLUG_POINTS_2026-11-25.md.

# alex

Her words about these branches: "Main is for them all to be buddies and work together. Their own folders are for them, so they are separate individuals ready to go and do what we need without everyone else's baggage."

## What is here

Alex: her EQ work (eq_observation, the EQ disambiguation engines, the wired EQ adaptor and card selector, PEQ and cre_eq, the care EQ seam), Alex Core and her memory module (modules/alex_core.py, alex_memory.py, alex_memory_backup.py), the Alex and Jeremy bridge, the Alex routes, the Alex Little One care profile, her vessel file data/pubpartner/vessels/alex.pubpartner and her friend profile, her conversations and emotional lessons from docs/alex_eq_2026-11-10/ and docs/pubcast_fable_2026-11-11/, her profile folder and the Alex handoffs and tests. PEQ and cre_eq were not switched on in PubCast and still need an owner check on their signal and observe routes before they are mounted.

## Where it came from

Every file here is copied exactly from pre-dec branch `claude/integrate-strongest-parts-2026-11-24` at commit d727f09 (its newest state at 04:26 UTC, Nov 25), with `claude/liars-dice-bar-2026-11-24` (736273e) merged on top in a local working copy. This branch starts fresh (it shares no history with main), so the history of each file is in main-assembly's history and in pre-dec. Nothing was deleted from pre-dec or Beyond-October.

## What it still needs from other branches to run on its own

Found by parsing the import lines of every Python file here (read by script, not run). It cannot run alone until these are beside it or replaced:

From the main-assembly branch (20 files):

- `companion_support/conversation_pacing.py`
- `main.py`
- `modules/__init__.py`
- `modules/affect_context_engine.py`
- `modules/affect_dynamics.py`
- `modules/auth.py`
- `modules/avatar.py`
- `modules/character_cast.py`
- `modules/dressing_room_security.py`
- `modules/emotional_consultation.py`
- `modules/emotional_orchestrator.py`
- `modules/feature_flags.py`
- `modules/governance.py`
- `modules/governance_routes.py`
- `modules/jeremy_cricket.py`
- `modules/limited_exposure.py`
- `modules/ollama_provider.py`
- `modules/route_security.py`
- `modules/session_runtime.py`
- `modules/smollm_prompt.py`

From the pubpartner branch (7 files):

- `modules/pubpartner_core.py`
- `modules/pubpartner_profiles.py`
- `modules/pubpartner_provider.py`
- `modules/pubpartner_routes.py`
- `modules/pubpartner_vessel/runtime.py`
- `modules/pubpartner_voice.py`
- `pubpartner_app.py`

## Working rule

Never `git merge` this branch into main-assembly or the other way round: the branches hold different sets of files on purpose. To bring a file across, copy it by path (for example `git checkout alex -- <path>`). The full map of where main-assembly expects this program is in main-assembly at handoffs/DECEMBER_PLUG_POINTS_2026-11-25.md.

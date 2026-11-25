# pubpartner

Her words about these branches: "Main is for them all to be buddies and work together. Their own folders are for them, so they are separate individuals ready to go and do what we need without everyone else's baggage."

## What is here

PubPartner, including its persistent memory architecture (the vessel in modules/pubpartner_vessel/, the cartridge and memory store in pubpartner/), the Base-Horizon companion mode, link and avatar preference layer (pubpartner/companion_mode.py, link.py, avatar_preference.py: library only, nothing calls it yet), its routes, core, backup, calibration, identity checkpoint, connector host, pages, launchers, example cartridge and tests. Alex's own vessel file and Alex's friend profile are in the alex branch, not here, because they are her memories.

## Where it came from

Every file here is copied exactly from pre-dec branch `claude/integrate-strongest-parts-2026-11-24` at commit d727f09 (its newest state at 04:26 UTC, Nov 25), with `claude/liars-dice-bar-2026-11-24` (736273e) merged on top in a local working copy. This branch starts fresh (it shares no history with main), so the history of each file is in main-assembly's history and in pre-dec. Nothing was deleted from pre-dec or Beyond-October.

## What it still needs from other branches to run on its own

Found by parsing the import lines of every Python file here (read by script, not run). It cannot run alone until these are beside it or replaced:

From the main-assembly branch (32 files):

- `companion_support/advisory.py`
- `modules/__init__.py`
- `modules/agency_observation.py`
- `modules/ai_providers.py`
- `modules/ai_runtime.py`
- `modules/ai_runtime_slots.py`
- `modules/auth.py`
- `modules/auth_routes.py`
- `modules/avatar_imports.py`
- `modules/byok_manager.py`
- `modules/chat_rooms.py`
- `modules/companion_advisory.py`
- `modules/dressing_room_security.py`
- `modules/governance.py`
- `modules/governance_routes.py`
- `modules/hub.py`
- `modules/jeremy_cricket.py`
- `modules/llm_framework.py`
- `modules/local_model_config.py`
- `modules/model_registry.py`
- `modules/ollama_provider.py`
- `modules/openai_compatible_provider.py`
- `modules/openai_responses_provider.py`
- `modules/opencode_zen.py`
- `modules/provider_capabilities.py`
- `modules/provider_neutralizer.py`
- `modules/pub_manager_authority.py`
- `modules/route_security.py`
- `modules/smollm_prompt.py`
- `modules/switchblade_router.py`
- `modules/turn_serialization.py`
- `modules/userdb.py`

From the blackbox branch (1 files):

- `modules/pubpartner_blackbox_light.py`

From the alex branch (5 files):

- `modules/alex_core.py`
- `modules/alex_jeremy_bridge.py`
- `modules/alex_routes.py`
- `modules/eq_observation/__init__.py`
- `modules/eq_observation/reliability.py`

From the 2i branch (2 files):

- `modules/manuscript_intelligence.py`
- `modules/writers_room.py`

## Working rule

Never `git merge` this branch into main-assembly or the other way round: the branches hold different sets of files on purpose. To bring a file across, copy it by path (for example `git checkout pubpartner -- <path>`). The full map of where main-assembly expects this program is in main-assembly at handoffs/DECEMBER_PLUG_POINTS_2026-11-25.md.

# Sir Purfluous

Her words: "Superfluous right now goes into parts assembly."

He was installed in main-assembly and his tests passed, then moved here on Nov 25 at her word. Both installs were reverted in main-assembly (the reverts of 4ef18bf6 and 53a4cc8a).

The two patches, in order:

1. `0001-salvage-ai-wiring-canon-cue-cards.patch`: his character material salvaged from the old scene-director file, the owner canon decisions of Nov 24, the AI Purfluous wired to his whole canon with paced interruptions, one cue-card deck for offline lines and online cues (with her TikTok watch line), and the EQ card catalog reader fix. From pre-dec `claude/purfluous-cue-cards-2026-11-24` (f762b3e), which holds purfluous-character-salvage, purfluous-ai-wiring and purfluous-canon.
2. `0002-more-cards-diagnostics-fixes.patch`: 160 more cards and the rest of Nov 24, plus three diagnostics (tools/purfluous_diagnostics.py) and their fixes. From pre-dec `claude/purfluous-more-cards-2026-11-24` (a959a35), its eleven Purfluous commits after c403fe6. Code Collector, also on that branch, is not in this patch.

Each patch is exactly what its install changed in main-assembly. Nothing was changed.

What was proven while he was installed (Nov 25): all three Purfluous test files together, 99 passed, driving him through modules/bots.py; his diagnostics soak of 20 simulated users for 50 turns each had 0 errors.

Heads-up: patch 1 also changes companion_support/eq_disambiguation_engine.py, which is Alex's EQ file.

To install later: on main-assembly, apply 0001 then 0002, run the Purfluous tests, write the handoff, then move this folder to Parts-Live-Archive.

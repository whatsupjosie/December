# On-set mini console

Moved back here from main-assembly on Nov 25 because it had not been proven to work.

Where it belongs, in her words: "the mini console goes in pub world. So the director can operate from inside there if they need to."

What it is now: a small console page (static/mini_console.html and mini_console.js, with its reference picture static/control_room_assets/mini_console_reference.png), recovered and wired to the current switcher. Right now it is reached only by an "On-set Mini Console" link on the director switcher's rail. It is not in Pub World yet.

Where it came from: pre-dec branch `codex/restore-mini-console` (59675d6), as merged on pre-dec's studio line in c805cca9 (Nov 22). The patch here is exactly what that merge changed in main-assembly (install merge ce44f0b1, since reverted). Nothing in it was changed.

What it still needs:
1. Wire it into Pub World, so the director can open and operate it from inside the world.
2. Prove it: use it in a real browser, from inside Pub World, against the running studio. It has no tests of its own. Serving the page and checking its files load is not enough.

To install once both are done: on main-assembly, apply this patch plus the Pub World wiring, use it in a browser, write the handoff, then move this folder to Parts-Live-Archive.

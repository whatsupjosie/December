# Director Dock restore and Control Room routing

Moved back here from main-assembly on Nov 25 because it had not been proven to work. Her words: "Move it back".

What it is: the Control Room's Director Dock brought back to how it worked in The Prime, plus fixes to how the Control Room finds its files and the order the studio starts up in. Page code only: static/control.html, control_stations.js, director_switcher.html, camera_pool_controller.js, production25d_app.js, editor_sync_station.js.

Where it came from: pre-dec branch `codex/restore-director-dock` (f66f285, which holds `codex/live-production` 17b29be), as merged on pre-dec's studio line in 2d0be28d (Nov 22). The patch here is exactly what that merge changed in main-assembly (install merge d97c6f13, since reverted by ae140bb). Nothing in it was changed.

What would prove it: open /control and /director-switcher in a real browser with the studio running and use the Director Dock and the switcher (the routes, the camera pool, the 2.5D production page). It has no tests of its own. Serving the pages and checking that their files load is not enough.

Why a patch and not the files: these six files belong to main-assembly. Copying changed versions in here would put two versions of the Control Room in December.

Heads-up for the rest of the studio line: later studio-line work edits two of these files again (director_switcher.html in 3 later commits, production25d_app.js in 4). Those later pieces were built with this change underneath them.

To install once proven: on main-assembly, apply this patch, use the pages in a browser, write the handoff, then move this folder to Parts-Live-Archive.

# Energy Sphere avatar and the Avatar Foundry upgrade

Dates: 2026-11-27/28 (Los Angeles). Repo `whatsupjosie/december`, branch `claude/primp-to-main-assembly-2026-11-27` (cut from `main-assembly`). Not merged; merging is the owner's call.

## Where the design comes from (read, verified)

- The owner's October 2025 design, in `parts-assembly:avatars-and-mocap/repos/recovery/2026-11-23/rediscovery/history_docs/Gemini_chat_avatar_creator_code_and_map_design_full_chat_10-11-25_454am.txt`, lines 1-30. It sets out four layers: a base glow, brightest at the centre; a woven texture of thread-like strands of light wrapping the sphere "like thread on a spool"; face features (eyes, mouth, eyebrows) "made of a denser, brighter application of the same woven thread style" that "do not change color with the mood"; and a spinning, scribbly "Mood Ring" border. The colour system is two-tone (core colour plus mood ring colour). Scale is "approximately one-third the height of an adult", floating at eye level. The avatar is a light source onto the surface below. Hands are floating, stylised, glowing gloved hands that "only appear when needed".
- Reference images the owner sent on 2026-11-28 (in this session's uploads, not committed): the prototype still `alpha_avatar_proto_type_still.png` (gold woven sphere with a lime mood ring); a turnaround and expression sheet (Front, 3/4, Back; Happy, Laughing, Surprised, Neutral, Sad with a tear, Mischief); colour and hair variation sheets; and face shade tests (a solid glowing ball). She also sent a green-and-brass "MIXER" console image. **Open question to her:** is it a style reference for the Foundry's controls, or did it arrive by accident?

## The owner's words, 2026-11-28 (quoted exactly)

On seeing through the sphere:
> "Yeah, I mean, remember, this is a sphere, so, just like they're turning around, they're facing away. But even when they're turned around, we can see through them a little bit. Although their features are still going to be much more distorted and flipped around."

Accessories and hands, still to build:
> "And they can be with or without eyelashes. Some of them could have a mustache, or a goatee, or a Van Dyke, or a full beard. Maybe a beauty mark. Pigtails, ponytail. You can play with different kinds of long hair, a little bow in the hair. Eye patch, hats. And they have hands too. They have like cartoon, like Mickey Mouse or Pac-Man, like white gloved hands basically. Probably four fingers. Or three fingers maybe, I don't know. But the hands are only there when they're actually doing something with them. So they have to be picking up a phone for their hands, and they don't have arms. So their hands just float out in space near their body, but they're their hands, you know?"

On the Foundry:
> "I want you to upgrade the Foundry ... Style, tactics, its methodology, the workflow, the fidelity, the options. I want you to give it the option of using HTML."

## What is built (done, tested)

- `static/js/energy_sphere.js`: a reusable renderer (one WebGL2 pass per canvas, no libraries). `PubCastEnergySphere.create(canvas, {core, ring, mood, energy, mode, background, zoom, lift, floor, yaw, interactive, idleLook})` returns `{set, destroy}`. Everything in the four layers above is drawn live:
  - **Movement:** floating; a glow cast on the floor; the face wraps the sphere when turned (drag, plus an idle look-around); blinking; a talking test.
  - **Moods:** calm (the prototype still), happy and laughing (closed, arched eyes), excited, surprised (round O), neutral (flat mouth, heavy lids), sad (with a tear), angry, and mischief (squinted >< eyes).
  - **Hologram modes:** energy (woven light); ghost (faint, flickering, more see-through); solid (an opaque, lit ball).
  - **The face from behind:** seen through the ball, mirrored and warped. It is faint in energy mode, clearer in ghost mode, and hidden in solid mode.
  - **Performance:** adaptive resolution for phones, and it draws only while on screen.

  It is generated from the tested standalone page by `gen_module.py`. That generator and the page are working files in the session, not in the repo; the module itself is the source of truth now.
- `modules/avatar.py`: new form `SPHERE` ("Energy Sphere", body type `sphere`, height 0.34). New `profile_view()` and `apply_profile_update()`, which validate every field and raise `AvatarProfileError` with a reason the page shows.
- `main.py` `/api/avatars/me`:
  - **Now saved and returned:** energy level, hologram mode, visibility, core colour and mood. Before this change these were silently dropped.
  - **The chosen form now saves:** the route accepts `preset_id`, and the old `preset` name as well.
  - **Refused with HTTP 422 and a reason:** an unknown form, a bad colour, energy outside 0-2, an unknown mode, non-boolean visibility, a bad mood or a name over 40 characters.
  - **Mood:** a mood the user saved wins over the live skin's mood.
  - **Old payloads:** `static/dressing.js` payloads (uppercase moods such as `ELEVATED`) still save, stored in lowercase.
- `static/avatar_foundry.html`:
  - **Stage:** a live stage above the forms when the Energy Sphere is chosen, with mood buttons (saved) and a "Test talking" button.
  - **Form card:** a live mini sphere on the Energy Sphere card.
  - **Colours:** Core Colour swatches. On the sphere, Glow Colour is the mood ring (noted on the page).
  - **Energy, Hologram Mode, Visible:** these now drive the sphere live and actually save.
  - **Saving:** Save shows "✓ Saved" only when the server saved, and otherwise shows the server's reason. Saving uses the sign-in token without the adapter's jump to the login page.
  - **Cards:** form cards are built once, with escaped names, and are keyboard-selectable. On phones they sit two per row.
  - **Side button:** the switch draft now carries the core colour and mood too.
  - **Form icons:** the other forms keep their simple preview and now show the server's own icons. The old icon list used the wrong IDs, so nearly every card showed 🎭.

## Tests (executed 2026-11-28)

- `tests/test_avatar_profile_api.py` (new): 15 passed (a full save/reload; nine kinds of refusal with nothing half-saved; the dressing-room payload; old `preset` name).
- `tests/primp_chromium/test_foundry_sphere.py` (new, real host + Chrome): 4 passed. The sphere draws, the card sphere draws, every choice saves and reloads, a refused save shows the reason, other forms keep the simple preview, and choices survive the trip to the boudoir.
- Whole `tests/primp_chromium` suite: 31 passed. `test_dressing_switch.py` was adjusted: the glow swatch is named explicitly now that a core swatch exists, and the visibility check no longer assumes the toggle starts "on", because tests share one host.
- Server regression: 196 passed and 1 skipped across routing, health, sign-in parity, cast, the public role, avatar imports, the Primp host and the restart tests. Node: 43/43.
- The full-suite run is recorded in the commit message.

## Not built yet (in this order)

1. **Face extras on the sphere**, using the same technique as the eyes and mouth: eyelashes (or none), mustache, goatee, Van Dyke, full beard, beauty mark, eye patch.
2. **Hair, bow and hats.** They stand past the ball's edge, so they need a second drawing layer: pigtails, ponytail, long hair styles, a little bow, hats.
3. **Hands:** white-gloved cartoon hands with three or four fingers (owner undecided), no arms, floating near the head, appearing only while doing something such as picking up a phone.
4. **The world:** drawing the sphere avatar in the walkable world. The world does not draw it yet; only the Foundry does.

## Decisions waiting on the owner

- The MIXER image: a style reference for the Foundry's controls, or an accident?
- Whether moods should also recolour the mood ring. Today the ring keeps the owner's chosen glow colour and moods change only the face. The standalone demo page recoloured the ring by mood using placeholder colours.
- The eyebrows come from the written design, but the prototype still has none. Keep them or drop them?
- Three or four fingers on the gloves.
- The mood names and labels are Claude's; rename any of them freely.

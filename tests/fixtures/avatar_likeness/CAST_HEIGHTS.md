# Cast heights for the avatar-likeness fixtures

Source: Josie, in the avatar-from-image session, 2026-11-27 (07:38 PT). Her words, verbatim:

> "you can measure the characters against pub blocks because Humphrey is just under 3 feet tall, the baby. Pete, the pink-haired woman, is canonically 5'7". And Repeat is 5'9". Repeat is the young man with the beard. That's his name."

The pub block is defined in `modules/voxel_set_contract.py`: `PUB_BLOCK_INCHES = 10`, `PUB_BLOCK_METERS = 0.254`.

| Character | Fixture file | Stated height | Inches | Metres | Pub blocks | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Humphrey (the baby detective) | `humphrey/Baby_Detective_Character_First_Sample.png` | "just under 3 feet" | < 36 | < 0.914 | < 3.6 | Upper bound only. The pipeline's working figure is 35 in (0.889 m, 3.5 blocks). That figure is my reading of "just under", not a number Josie gave. |
| Pete (pink-haired woman, biker jacket) | `fresh/fresh_woman_tpose_biker_jacket.png` | 5'7" | 67 | 1.7018 | 6.70 | As stated. |
| Repeat (bearded man, camera and bag) | `fresh/fresh_man_tpose_camera_bag.png` | 5'9" | 69 | 1.7526 | 6.90 | As stated. |

## Disagreement with the repository's existing heights (not changed here)

`modules/avatar_imports.py` (`DEFAULT_HEIGHTS`) and `data/avatars/canonical_heights.json` currently say:

- Pete: 68 in (stated today: 67 in, 5'7")
- RePete: 70 in (stated today: 69 in, 5'9"); the repo spells the name "RePete", today's message spells it "Repeat"
- Humphrey: not in the cast list

This branch does not edit either file. Both are shared integration files, and the spelling and the one-inch difference are Josie's call. The likeness pipeline takes the height as an input on every run (`height_in`), so each run is sized from what she states and not from the repository default.

# Character 3D model, unrigged v1 (Nov 19, 2026)

## Files
- character-unrigged-v1.glb: textured mesh, 253,010 triangles, one 2048x2048 color texture. Y up, meters, facing +Z, feet at Y=0, height 1.727 m (68 in). No skeleton, no animation.
- comparison-sheet-v1.png: her four drawings (top) and renders of the GLB from the same four directions (bottom), same scale and framing.
- three-quarter-views-v1.png and renders/: extra renders of the same GLB.
- reference/: her four drawings, pixel-identical to her uploads.

## How it was made
Built directly from her four drawings, not by an AI 3D generator. TRELLIS on Hugging Face was tried on Nov 19 and refused to run (free GPU quota used up, about 24 h to reset); its output also cannot be downloaded onto this machine, because Hugging Face is blocked from it.
1. Cut her outline out of each drawing.
2. Lined the back up with the front and the left side with the right side (mirror, small vertical stretch to match head-to-toe height, 2 px and 10 px sideways shifts).
3. Built the body slice by slice: each horizontal slice is a rounded shape whose width comes from the front outline and whose depth comes from the side outline, with the arms as separate rounds. Smoothed, then turned into a closed mesh.
4. Painted it by projecting each drawing onto the surfaces that face that drawing's direction, blended at the turns, and filled hidden spots (under arms, inner legs, soles) from the nearest painted spot.

## Verified
- The GLB loads back, measures 1.727 m tall, faces +Z, and its texture lands right side up (checked by rendering the exported file itself).
- The mesh is closed (watertight) as built.
- Front and back renders match the drawings closely; side renders match the outline.

## Not verified / guessed
- Height 68 in is the PubCast default adult height. That this character is Pete (Alex Bourgeois) is a guess from where similar sheets sit in Beyond-October; not confirmed.
- The drawings are cut off by their panel edges in places (arm outer edges in front and back, hair front, chest and heels in the side views). Those spots are filled in with a guessed curve.
- The drawings are not perfectly consistent with each other, so the blends between views show seams.

## Known gaps
- No real face shape: the face is painted on a rounded head. Seen from the side, the profile nose and lips are missing and the front face is stretched around the cheek.
- Hands and lower arms are too thin and merge with the hips, so the drawn hands smear onto the hips in the front and side views.
- Some background-colored specks around the boots.
- The mesh is heavy for a real-time avatar (253k triangles); it should be reduced before use in PubCast.
- Not rigged. Rigging to her PubCast 89-bone skeleton (Sheila/Manny, PubCast Avatar System 2.0) waits on her approval of this shape. Note for rigging: that skeleton's _L bones sit at -X while the body faces +Z, which is the character's right side in this file.

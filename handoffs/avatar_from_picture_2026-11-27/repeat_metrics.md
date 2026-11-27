# repeat: picture to avatar, measured

Built file repeat.glb (fingerprint 0ad9956b127b5fca); cut-out network used: False; pose detector used: False.

Height 69.1 in = 6.91 pub blocks; build adult; 16,010 vertices, 29,788 triangles, 25 bones.

## Old workflow (real Dressing Room bake)
The page said: ✓ Portrait baked — skin: auto, face detected: no. Host returned skin colour #9d9790, voxel count 3, face detected False. Studio: flat figure; nothing from the picture reaches Studio.

## New workflow, front view, against the picture (bind pose (the picture is a T-pose))
Silhouette overlap 0.932 (bands {'upper': 0.9272, 'middle': 0.9766, 'lower': 0.8732}); colour distance 3.7; ink outline loss 0.00.
Findings: none above the thresholds

## Deformation in motion (CPU skinning against the bind pose)
- Idle: 0.06% of triangles ever grow or shrink by more than 2.5x; worst single triangle 3.6x; by part {np.str_('arm_L'): 0.0011, np.str_('arm_R'): 0.0, np.str_('foot_L'): 0.0, np.str_('foot_R'): 0.0, np.str_('hand_L'): 0.0, np.str_('hand_R'): 0.0, np.str_('head'): 0.0, np.str_('leg_L'): 0.0, np.str_('leg_R'): 0.0, np.str_('torso'): 0.0011}
- Walk: 0.86% of triangles ever grow or shrink by more than 2.5x; worst single triangle 10.72x; by part {np.str_('arm_L'): 0.0022, np.str_('arm_R'): 0.0038, np.str_('foot_L'): 0.0, np.str_('foot_R'): 0.0, np.str_('hand_L'): 0.0, np.str_('hand_R'): 0.0, np.str_('head'): 0.0, np.str_('leg_L'): 0.026, np.str_('leg_R'): 0.0225, np.str_('torso'): 0.0032}

## How much of the picture is used at each view angle (front picture only)
-   0 deg: used well 99%, smeared 1%, hidden 0%; 0% of what is on screen is the generated back
-  30 deg: used well 79%, smeared 18%, hidden 3%; 0% of what is on screen is the generated back
-  60 deg: used well 55%, smeared 19%, hidden 26%; 15% of what is on screen is the generated back
-  90 deg: used well 29%, smeared 20%, hidden 50%; 46% of what is on screen is the generated back
- 120 deg: used well 12%, smeared 13%, hidden 75%; 80% of what is on screen is the generated back
- 180 deg: used well 0%, smeared 0%, hidden 100%; 100% of what is on screen is the generated back

## Turn stability
Turntable (rest pose): height drift 0.4%, lowest frame-to-frame overlap 0.808. the silhouette jumps between two frames (overlap 0.81)
Studio walk and turn: height drift 7.1%, lowest frame-to-frame overlap 0.279. the figure's height moves 7.1% across the run; the silhouette jumps between two frames (overlap 0.28)

## Warnings the builder gave the user
- No pose model is installed, so joints come from the build template. Check them in the editor.
- The arm joints were measured from the cut-out, not detected. Check the elbows and wrists in the editor.

## Not in the picture
- The back and the sides of the character are not in the picture. They are generated from the front's colours (back view setting) and a rounded body shape inferred from the outline.
- Depth is inferred. Parts are given rounded cross-sections sized from their own width; use the depth sliders where the character is flatter or deeper than that.
- Shoes are given a sole length from the build; the picture shows them head-on.

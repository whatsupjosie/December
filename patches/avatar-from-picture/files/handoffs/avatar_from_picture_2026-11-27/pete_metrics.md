# pete: picture to avatar, measured

Built file pete.glb (fingerprint 65a2ca3a47e54187); cut-out network used: False; pose detector used: False.

Height 67.0 in = 6.70 pub blocks; build adult; 14,858 vertices, 27,644 triangles, 25 bones.

## Old workflow (real Dressing Room bake)
The page said: ✓ Portrait baked — skin: auto, face detected: no. Host returned skin colour #a4a29f, voxel count 3, face detected False. Studio: flat figure; nothing from the picture reaches Studio.

## New workflow, front view, against the picture (bind pose (the picture is a T-pose))
Silhouette overlap 0.926 (bands {'upper': 0.9157, 'middle': 0.9862, 'lower': 0.8583}); colour distance 1.9; ink outline loss 0.01.
Findings: none above the thresholds

## Deformation in motion (CPU skinning against the bind pose)
- Idle: 0.04% of triangles ever grow or shrink by more than 2.5x; worst single triangle 3.1x; by part {np.str_('arm_L'): 0.0, np.str_('arm_R'): 0.0014, np.str_('foot_L'): 0.0, np.str_('foot_R'): 0.0, np.str_('hand_L'): 0.0, np.str_('hand_R'): 0.0, np.str_('head'): 0.0, np.str_('leg_L'): 0.0, np.str_('leg_R'): 0.0, np.str_('torso'): 0.0007}
- Walk: 0.11% of triangles ever grow or shrink by more than 2.5x; worst single triangle 5.0x; by part {np.str_('arm_L'): 0.0007, np.str_('arm_R'): 0.0072, np.str_('foot_L'): 0.0, np.str_('foot_R'): 0.0, np.str_('hand_L'): 0.0, np.str_('hand_R'): 0.0, np.str_('head'): 0.0, np.str_('leg_L'): 0.0, np.str_('leg_R'): 0.0, np.str_('torso'): 0.0016}

## How much of the picture is used at each view angle (front picture only)
-   0 deg: used well 99%, smeared 1%, hidden 0%; 0% of what is on screen is the generated back
-  30 deg: used well 78%, smeared 20%, hidden 3%; 0% of what is on screen is the generated back
-  60 deg: used well 56%, smeared 16%, hidden 28%; 15% of what is on screen is the generated back
-  90 deg: used well 31%, smeared 18%, hidden 50%; 46% of what is on screen is the generated back
- 120 deg: used well 13%, smeared 14%, hidden 73%; 80% of what is on screen is the generated back
- 180 deg: used well 0%, smeared 0%, hidden 100%; 100% of what is on screen is the generated back

## Turn stability
Turntable (rest pose): height drift 0.4%, lowest frame-to-frame overlap 0.813. the silhouette jumps between two frames (overlap 0.81)
Studio walk and turn: height drift 6.9%, lowest frame-to-frame overlap 0.452. the figure's height moves 6.9% across the run; the silhouette jumps between two frames (overlap 0.45)

## Warnings the builder gave the user
- No pose model is installed, so joints come from the build template. Check them in the editor.
- The arm joints were measured from the cut-out, not detected. Check the elbows and wrists in the editor.

## Not in the picture
- The back and the sides of the character are not in the picture. They are generated from the front's colours (back view setting) and a rounded body shape inferred from the outline.
- Depth is inferred. Parts are given rounded cross-sections sized from their own width; use the depth sliders where the character is flatter or deeper than that.
- Shoes are given a sole length from the build; the picture shows them head-on.

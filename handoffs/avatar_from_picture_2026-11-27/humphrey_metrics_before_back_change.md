# humphrey: picture to avatar, measured

Built file humphrey.glb (fingerprint eac4558f6aa39b21); cut-out network used: True; pose detector used: False.

Height 35.2 in = 3.52 pub blocks; build toddler; 35,470 vertices, 68,984 triangles, 25 bones.

## Old workflow (real Dressing Room bake)
The page said: ✓ Portrait baked — skin: auto, face detected: no. Host returned skin colour #6a543f, voxel count 3, face detected False. Studio: flat figure; nothing from the picture reaches Studio.

## New workflow, front view, against the picture (first frame of the Idle clip (the picture is not a T-pose, so its drawn pose is what to compare))
Silhouette overlap 0.922 (bands {'upper': 0.9735, 'middle': 0.9168, 'lower': 0.8849}); colour distance 1.9; ink outline loss 0.15.
Findings: none above the thresholds

## Deformation in motion (CPU skinning against the bind pose)
- Idle: 7.17% of triangles ever grow or shrink by more than 2.5x; worst single triangle 662.15x; by part {np.str_('arm_L'): 0.3636, np.str_('arm_R'): 0.3723, np.str_('foot_L'): 0.0, np.str_('foot_R'): 0.0, np.str_('hand_L'): 0.0902, np.str_('hand_R'): 0.3367, np.str_('head'): 0.0, np.str_('leg_L'): 0.0074, np.str_('leg_R'): 0.0, np.str_('torso'): 0.0356}
- Walk: 9.63% of triangles ever grow or shrink by more than 2.5x; worst single triangle 1248.96x; by part {np.str_('arm_L'): 0.42, np.str_('arm_R'): 0.4278, np.str_('foot_L'): 0.0, np.str_('foot_R'): 0.0, np.str_('hand_L'): 0.2131, np.str_('hand_R'): 0.4235, np.str_('head'): 0.0, np.str_('leg_L'): 0.044, np.str_('leg_R'): 0.0558, np.str_('torso'): 0.0539}

## How much of the picture is used at each view angle (front picture only)
-   0 deg: used well 90%, smeared 5%, hidden 5%; 4% of what is on screen is the generated back
-  30 deg: used well 74%, smeared 18%, hidden 7%; 8% of what is on screen is the generated back
-  60 deg: used well 56%, smeared 17%, hidden 27%; 21% of what is on screen is the generated back
-  90 deg: used well 32%, smeared 19%, hidden 49%; 47% of what is on screen is the generated back
- 120 deg: used well 11%, smeared 17%, hidden 72%; 74% of what is on screen is the generated back
- 180 deg: used well 3%, smeared 2%, hidden 95%; 96% of what is on screen is the generated back

## Turn stability
Turntable (rest pose): height drift 0.0%, lowest frame-to-frame overlap 0.883. 
Studio walk and turn: height drift 5.4%, lowest frame-to-frame overlap 0.811. the silhouette jumps between two frames (overlap 0.81)

## Against the Runway clip
head and upper body only (the clip is a close-up). The turn angle of each clip frame was judged by eye; the render is at that angle or its mirror, whichever overlaps better, and the pose is the picture's drawn pose.
- clip frame 1: turned about 0 deg (by eye), render at 0 deg, silhouette overlap 0.75, colour distance 4.7
    - silhouette overlap is 0.75 (below 0.8): the outline is a different shape
    - the upper third overlaps only 0.69
    - the middle third overlaps only 0.67
    - width per row differs by 0.147 of the height on average (head, shoulders or legs are sized differently)
- clip frame 56: turned about 40 deg (by eye), render at 320 deg, silhouette overlap 0.56, colour distance 2.9
    - silhouette overlap is 0.56 (below 0.8): the outline is a different shape
    - the upper third overlaps only 0.55
    - the middle third overlaps only 0.61
    - the lower third overlaps only 0.52
    - the figure is 27% wider or narrower for its height than the reference
    - width per row differs by 0.237 of the height on average (head, shoulders or legs are sized differently)
    - the dark outline along the edge is 53% weaker than in the reference
- clip frame 67: turned about 80 deg (by eye), render at 80 deg, silhouette overlap 0.70, colour distance 5.7
    - silhouette overlap is 0.70 (below 0.8): the outline is a different shape
    - the upper third overlaps only 0.64
    - the lower third overlaps only 0.68
    - the figure is 19% wider or narrower for its height than the reference
    - width per row differs by 0.135 of the height on average (head, shoulders or legs are sized differently)
    - the dark outline along the edge is 87% weaker than in the reference
- clip frame 89: turned about 140 deg (by eye), render at 220 deg, silhouette overlap 0.70, colour distance 5.3
    - silhouette overlap is 0.70 (below 0.8): the outline is a different shape
    - the middle third overlaps only 0.64
    - the figure is 13% wider or narrower for its height than the reference
    - width per row differs by 0.145 of the height on average (head, shoulders or legs are sized differently)
- clip frame 111: turned about 170 deg (by eye), render at 190 deg, silhouette overlap 0.78, colour distance 6.7
    - silhouette overlap is 0.78 (below 0.8): the outline is a different shape
    - the middle third overlaps only 0.65
    - width per row differs by 0.061 of the height on average (head, shoulders or legs are sized differently)

## Warnings the builder gave the user
- The picture is cropped at the feet. The legs will end where the picture ends and the shoes are closed off; set the floor line yourself if the shoes are visible.
- No pose model is installed, so joints come from the build template. Check them in the editor.
- The pose in the picture is far from a T-pose, so the arms were swung a long way into the rest pose. Check the shoulders and elbows in the editor.

## Not in the picture
- The back and the sides of the character are not in the picture. They are generated from the front's colours (back view setting) and a rounded body shape inferred from the outline.
- Depth is inferred. Parts are given rounded cross-sections sized from their own width; use the depth sliders where the character is flatter or deeper than that.
- Shoes are given a sole length from the build; the picture shows them head-on.

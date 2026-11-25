# Spatial Workspace Guide — 2.5.0a10

## Tray controls

Every desktop tray can be:

- dragged by its title bar;
- resized from its lower-right handle;
- snapped to the field grid and edges;
- docked left, docked right, or returned to free placement;
- collapsed and expanded;
- brought to the foreground;
- cycled through the material palette.

Arrow keys move a focused tray. Hold Shift for larger movement steps.

## Workspaces

The header workspace selector stores named layouts locally in the browser. Layout state includes tray position, size, material, collapsed state, docking state, z-order, geometry mode, and theme.

The File/Edit menus support saving, importing, exporting, resetting, compacting, and undoing tray layouts. The layout JSON contains no custody secrets.

## Responsive mode

Below the desktop breakpoint, the spatial field becomes a single-column document flow. Dragging and resizing are disabled, trays lose decorative clipping, and all controls remain reachable without horizontal spatial navigation.

## Shortcuts

- `Ctrl/Cmd + S`: save active tray workspace.
- `Ctrl/Cmd + Z`: undo the last tray movement.
- `Ctrl/Cmd + R`: refresh custody state.
- `Alt + 1…5`: jump among overview, workspace, LabCopy, promotion, and evidence.
- `Escape`: close menus and ceremonies.

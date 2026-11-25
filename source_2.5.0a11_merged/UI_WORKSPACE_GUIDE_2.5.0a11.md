# Spatial Workspace Guide — 2.5.0a11

## Tray controls

Every desktop tray can be dragged by its title bar, resized from its lower-right handle, snapped, docked, collapsed, brought forward, and assigned a material treatment. Arrow keys move a focused tray; Shift increases the movement step.

## Exact custody language

The interface uses literal terms only. `Retire`, `Restore`, `Archive`, `Quarantine`, `Export`, and `Revoke passkey` each describe one exact state or authority change. No ordinary interface action represents loss of protected content.

Generation rows expose **Retire** only for Raw Source, Candidate, and Archive objects. A retired object exposes **Restore**. Both actions show the exact project, section, object, resulting state, preservation statement, typed ceremony word, passkey approval, and final receipt. Current Prime shows an explanatory lock: promote a replacement before retirement.

## Passkey tray

A fresh installation reports enrollment as required. Enroll at least two independent authenticators. Revoking a credential requires a new exact-action passkey approval and leaves a preserved revocation record. The final active credential cannot be revoked.

## Workspaces

The workspace selector stores named visual layouts locally in the browser. Layout state contains tray geometry, material, collapse and docking state, z-order, geometry mode, and theme. Layout JSON contains no custody bytes or authority secrets.

## Responsive mode

Below the desktop breakpoint, the spatial field becomes a single-column document flow. Dragging and resizing are disabled, decorative clipping is reduced, and controls remain reachable without horizontal spatial navigation.

## Shortcuts

- `Ctrl/Cmd + S`: save active tray workspace.
- `Ctrl/Cmd + Z`: undo the last tray movement.
- `Ctrl/Cmd + R`: refresh custody state.
- `Alt + 1…5`: jump among overview, workspace, LabCopy, promotion, and evidence.
- `Escape`: close menus and ceremonies.

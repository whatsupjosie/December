// Primp ↔ PubCast avatar store (modules/avatar_imports.py).
// Primp opens any avatar in the store and sends a finished look back as a NEW
// avatar at the same canonical height and character. The original is never
// replaced, edited or deleted. The server re-measures every upload and refuses
// a height that does not match, so Primp does not resize anything itself.
import {LIMITS} from './core.mjs';

export const INCH_M = 0.0254;
export const MIN_HEIGHT_IN = 6, MAX_HEIGHT_IN = 240;   // same bounds as the store
const ID = /^[a-z0-9][a-z0-9_-]{0,63}$/;

export function validAvatarId(value) { return typeof value === 'string' && ID.test(value); }

// ?avatar=<id> on primp.html opens that PubCast avatar directly.
export function requestedAvatarId(search) {
  const id = new URLSearchParams(search || '').get('avatar');
  return validAvatarId(id) ? id : null;
}

async function failure(response, fallback) {
  if (response.status === 401) return new Error('Sign in to PubCast to open or send PubCast avatars. Your open work is still here.');
  const body = await response.json().catch(() => ({}));
  const detail = typeof body.detail === 'string' ? body.detail : '';
  return new Error(detail || `${fallback} (${response.status})`);
}

export async function listAvatars(fetcher = fetch) {
  const response = await fetcher('/api/avatars/imports');
  if (!response.ok) throw await failure(response, 'PubCast avatars could not be listed');
  const body = await response.json();
  if (!Array.isArray(body?.avatars)) throw new Error('The PubCast avatar list is invalid.');
  return body.avatars.filter(a => a && validAvatarId(a.id) && typeof a.name === 'string' && Number.isFinite(a.canonical_height_in));
}

export async function fetchAvatar(entry, fetcher = fetch) {
  if (!validAvatarId(entry?.id)) throw new Error('Invalid PubCast avatar.');
  if (Number(entry.bytes) > LIMITS.source) throw new Error(`“${entry.name}” is larger than Primp’s 30 MiB limit.`);
  const response = await fetcher(`/api/avatars/imports/${entry.id}/model.glb`);
  if (!response.ok) throw await failure(response, 'The PubCast avatar could not be opened');
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength > LIMITS.source) throw new Error(`“${entry.name}” is larger than Primp’s 30 MiB limit.`);
  return bytes;
}

// What Primp keeps about where an avatar came from. Stored in the .primp look
// and its local recovery, so a reopened look can still go back to PubCast.
export function originOf(entry) {
  return {id: entry.id, name: String(entry.name).slice(0, 80), character_id: String(entry.character_id || '').slice(0, 64), canonical_height_in: Number(entry.canonical_height_in)};
}
export function readOrigin(value) {
  const o = value?.origin;
  if (!o || typeof o !== 'object' || !validAvatarId(o.id) || typeof o.name !== 'string' || o.name.length > 80
      || typeof o.character_id !== 'string' || o.character_id.length > 64
      || !Number.isFinite(o.canonical_height_in) || o.canonical_height_in < MIN_HEIGHT_IN || o.canonical_height_in > MAX_HEIGHT_IN) return null;
  return {id: o.id, name: o.name, character_id: o.character_id, canonical_height_in: o.canonical_height_in};
}

// Height a non-PubCast avatar actually stands, to the nearest half inch.
export function standingHeightIn(heightM) { return Math.round(heightM / INCH_M * 2) / 2; }

export async function sendAvatar(glb, {name, heightIn, origin = null, sourceName = ''}, fetcher = fetch) {
  const clean = String(name || '').trim().slice(0, 80);
  if (!clean) throw new Error('Give the new avatar a name.');
  if (!Number.isFinite(heightIn) || heightIn < MIN_HEIGHT_IN || heightIn > MAX_HEIGHT_IN) throw new Error(`Canonical height must be between ${MIN_HEIGHT_IN} and ${MAX_HEIGHT_IN} inches.`);
  const query = new URLSearchParams({name: clean, height_in: String(heightIn), source_format: 'glb',
    // The made-up avatar belongs to the same character as the one it came from.
    character_id: origin ? (origin.character_id || origin.id) : '',
    source_name: origin ? `primp:${origin.id}` : `primp:${String(sourceName).slice(0, 180)}`});
  const response = await fetcher(`/api/avatars/imports?${query}`, {method: 'POST', headers: {'Content-Type': 'model/gltf-binary'}, body: glb});
  if (!response.ok) throw await failure(response, 'PubCast did not accept the avatar');
  const body = await response.json();
  if (!validAvatarId(body?.avatar?.id)) throw new Error('PubCast saved the avatar but returned an invalid record.');
  return body.avatar;
}

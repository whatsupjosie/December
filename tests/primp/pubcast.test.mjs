import test from 'node:test';
import assert from 'node:assert/strict';
import {listAvatars, fetchAvatar, sendAvatar, originOf, readOrigin, requestedAvatarId, standingHeightIn, validAvatarId} from '../../static/primp/pubcast.mjs';
import {LIMITS} from '../../static/primp/core.mjs';

const json = (status, body) => new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}});
const entry = {id: 'sheila-1a2b3c4d', name: 'Sheila', character_id: '', canonical_height_in: 74.5, bytes: 1000, url: '/api/avatars/imports/sheila-1a2b3c4d/model.glb'};

test('avatar ids follow the store rule and the deep link ignores anything else', () => {
  assert.equal(requestedAvatarId('?avatar=sheila-1a2b3c4d'), 'sheila-1a2b3c4d');
  for (const bad of ['?avatar=../etc', '?avatar=Sheila', '?avatar=', '', '?avatar=a/b', '?avatar=' + 'a'.repeat(65)]) assert.equal(requestedAvatarId(bad), null);
  assert.equal(validAvatarId('-lead'), false);
});

test('listing keeps only well-formed store records and reports server refusals', async () => {
  const listed = await listAvatars(async url => { assert.equal(url, '/api/avatars/imports'); return json(200, {ok: true, avatars: [entry, {id: '../x', name: 'bad', canonical_height_in: 68}, {id: 'ok-1', name: 3, canonical_height_in: 68}]}); });
  assert.deepEqual(listed.map(a => a.id), ['sheila-1a2b3c4d']);
  await assert.rejects(listAvatars(async () => json(200, {avatars: 'nope'})), /invalid/);
  await assert.rejects(listAvatars(async () => json(500, {detail: 'index unreadable'})), /index unreadable/);
  await assert.rejects(listAvatars(async () => json(401, {detail: 'x'})), /Sign in to PubCast/);
});

test('opening respects Primp’s 30 MiB source limit before and after download', async () => {
  const bytes = new Uint8Array([1, 2, 3]);
  const got = await fetchAvatar(entry, async url => { assert.equal(url, entry.url); return new Response(bytes); });
  assert.deepEqual(new Uint8Array(got), bytes);
  await assert.rejects(fetchAvatar({...entry, bytes: LIMITS.source + 1}, async () => assert.fail('must not download')), /30 MiB/);
  await assert.rejects(fetchAvatar({...entry, bytes: undefined}, async () => new Response(new Uint8Array(LIMITS.source + 1))), /30 MiB/);
  await assert.rejects(fetchAvatar({...entry, id: '../x'}, async () => assert.fail('must not request')), /Invalid/);
  await assert.rejects(fetchAvatar(entry, async () => json(404, {detail: 'avatar not found'})), /avatar not found/);
});

test('a look from a PubCast avatar goes back as a new avatar of the same character and height', async () => {
  const origin = originOf(entry), glb = new Uint8Array([9, 9]);
  let seen;
  const saved = await sendAvatar(glb, {name: '  Sheila (Primp)  ', heightIn: 74.5, origin}, async (url, init) => { seen = {url, init}; return json(201, {ok: true, avatar: {id: 'sheila-primp-0000aaaa', name: 'Sheila (Primp)'}}); });
  assert.equal(saved.id, 'sheila-primp-0000aaaa');
  const q = new URL(seen.url, 'http://host').searchParams;
  assert.equal(new URL(seen.url, 'http://host').pathname, '/api/avatars/imports');
  assert.equal(seen.init.method, 'POST'); assert.equal(seen.init.headers['Content-Type'], 'model/gltf-binary'); assert.equal(seen.init.body, glb);
  assert.equal(q.get('name'), 'Sheila (Primp)'); assert.equal(q.get('height_in'), '74.5');
  assert.equal(q.get('character_id'), 'sheila-1a2b3c4d', 'an avatar without a character id is its own character');
  assert.equal(q.get('source_name'), 'primp:sheila-1a2b3c4d');
  await sendAvatar(glb, {name: 'Pete', heightIn: 68, origin: {...origin, character_id: 'pete'}}, async url => { assert.equal(new URL(url, 'http://h').searchParams.get('character_id'), 'pete'); return json(201, {avatar: {id: 'pete-1'}}); });
});

test('sending refuses bad input before any request and passes the server’s reason through', async () => {
  const never = async () => assert.fail('must not request');
  await assert.rejects(sendAvatar(new Uint8Array(), {name: '   ', heightIn: 68}, never), /name/);
  for (const h of [NaN, 5.9, 240.5]) await assert.rejects(sendAvatar(new Uint8Array(), {name: 'A', heightIn: h}, never), /between 6 and 240/);
  await assert.rejects(sendAvatar(new Uint8Array(), {name: 'A', heightIn: 68}, async () => json(422, {detail: 'avatar measures 1.889 m tall but its canonical height is 68 in'})), /measures 1\.889 m/);
  await assert.rejects(sendAvatar(new Uint8Array(), {name: 'A', heightIn: 68}, async () => json(401, {})), /Sign in to PubCast/);
  await assert.rejects(sendAvatar(new Uint8Array(), {name: 'A', heightIn: 68}, async () => json(201, {avatar: {id: '../x'}})), /invalid record/);
  let q; await sendAvatar(new Uint8Array(), {name: 'A', heightIn: 68, sourceName: 'manny'}, async url => { q = new URL(url, 'http://h').searchParams; return json(201, {avatar: {id: 'a-1'}}); });
  assert.equal(q.get('character_id'), ''); assert.equal(q.get('source_name'), 'primp:manny');
});

test('the origin stored in a .primp look is read back strictly; anything malformed is dropped, not trusted', () => {
  const o = originOf(entry);
  assert.deepEqual(readOrigin({origin: o}), o);
  assert.equal(readOrigin({}), null);
  for (const bad of [{...o, id: '../x'}, {...o, canonical_height_in: 'tall'}, {...o, canonical_height_in: 2}, {...o, name: 'x'.repeat(81)}, {...o, character_id: 7}, 'string'])
    assert.equal(readOrigin({origin: bad}), null);
  assert.deepEqual(Object.keys(readOrigin({origin: {...o, extra: '<script>'}})).sort(), ['canonical_height_in', 'character_id', 'id', 'name']);
});

test('standing height rounds to the nearest half inch', () => {
  assert.equal(standingHeightIn(1.8891), 74.5);
  assert.equal(standingHeightIn(1.7272), 68);
});

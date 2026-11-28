"""Primp connected to the PubCast avatar store, end to end, in a real browser and host.

Open a stored avatar in Primp (picker and ?avatar= link), paint it, send it back,
and check that PubCast keeps the original untouched and adds a new avatar of the
same character and canonical height that the world's avatar manifest lists.
"""
import base64
import io
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from modules.avatar_imports import measure_glb  # noqa: E402

SHEILA = ROOT/'static/primp/avatars/sheila.glb'


def api(live_host, path, data=None, content_type=None):
    headers = {'Authorization': 'Bearer '+live_host['account']['access_token']}
    if content_type:
        headers['Content-Type'] = content_type
    request = urllib.request.Request(live_host['url']+path, data=data, headers=headers, method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(request) as response:
        body = response.read()
        return json.loads(body) if response.headers.get_content_type() == 'application/json' else body


def store_sheila(live_host, name, character_id):
    query = urllib.parse.urlencode({'name': name, 'height_in': '74.5', 'character_id': character_id, 'source_format': 'glb', 'source_name': 'sheila.glb'})
    return api(live_host, '/api/avatars/imports?'+query, SHEILA.read_bytes(), 'model/gltf-binary')['avatar']


def imports(live_host):
    return api(live_host, '/api/avatars/imports')['avatars']


def canvas_png(page):
    page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    return base64.b64decode(page.locator('#viewport canvas').evaluate('c=>c.toDataURL("image/png").split(",")[1]'))


def differs(a, b):
    return ImageChops.difference(Image.open(io.BytesIO(a)).convert('RGB'), Image.open(io.BytesIO(b)).convert('RGB')).getbbox() is not None


def paint(page):
    page.get_by_role('button', name='Ink', exact=True).click()
    box = page.locator('#viewport canvas').bounding_box()
    x, y = box['x']+box['width']/2, box['y']+box['height']/2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x+8, y, steps=5)
    page.mouse.up()
    expect(page.locator('#undo')).to_be_enabled()


def test_store_avatar_opens_paints_and_returns_as_a_new_avatar_of_the_same_character(mirror, live_host, tmp_path):
    page = mirror
    original = store_sheila(live_host, 'Store Sheila', 'sheila-store-test')
    before_ids = {a['id'] for a in imports(live_host)}

    # ?avatar=<id>, the link Import Avatar's library gives
    page.goto(live_host['url']+'/static/primp.html?avatar='+original['id'])
    expect(page.locator('#status')).to_contain_text('Avatar ready', timeout=30000)
    expect(page.locator('#avatar-name')).to_have_text('Store Sheila')
    expect(page.locator('#pubcast-avatar')).to_be_visible()
    expect(page.locator('#pubcast-avatar option', has_text='Store Sheila')).to_have_count(1)
    unpainted = canvas_png(page)
    paint(page)
    painted = canvas_png(page)
    assert differs(unpainted, painted)

    # Cancel sends nothing.
    page.locator('#send').click()
    expect(page.locator('#send-dialog')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('#status')).to_contain_text('cancelled')
    assert {a['id'] for a in imports(live_host)} == before_ids

    # Send keeps the stored canonical height (read-only) and the character.
    page.locator('#send').click()
    expect(page.locator('#send-height')).to_have_value('74.5')
    assert page.locator('#send-height').evaluate('e=>e.readOnly')
    expect(page.locator('#send-name')).to_have_value('Store Sheila (Primp)')
    page.locator('#send-name').fill('Sheila Evening Look')
    page.locator('#send-confirm').click()
    expect(page.locator('#status')).to_contain_text('Sent to PubCast as “Sheila Evening Look”', timeout=30000)

    after = imports(live_host)
    new = [a for a in after if a['id'] not in before_ids]
    assert len(new) == 1
    made_up = new[0]
    assert made_up['name'] == 'Sheila Evening Look'
    assert made_up['character_id'] == 'sheila-store-test'
    assert made_up['canonical_height_in'] == 74.5
    assert made_up['source_name'] == 'primp:'+original['id']
    assert made_up['measured']['skinned'] and made_up['measured']['joints'] == original['measured']['joints']

    # The original is still there, byte for byte.
    assert original['id'] in {a['id'] for a in after}
    assert api(live_host, original['url']) == SHEILA.read_bytes()
    sent = api(live_host, made_up['url'])
    assert sent != SHEILA.read_bytes()
    assert abs(measure_glb(sent)['height_m'] - measure_glb(SHEILA.read_bytes())['height_m']) < 1e-4
    (tmp_path/'sent.glb').write_bytes(sent)

    # The world's avatar manifest lists both; neither replaced the other. A real
    # install has the curated manifest in data/; this host's data folder is new.
    curated = live_host['data_dir']/'avatars'/'manifest.json'
    if not curated.exists():
        curated.write_bytes((ROOT/'data/avatars/manifest.json').read_bytes())
    manifest = api(live_host, '/data/avatars/manifest.json')
    pack = next(p for p in manifest['packs'] if p['pack_id'] == 'imported')
    listed = {a['id']: a for a in pack['assets']}
    assert original['id'] in listed and made_up['id'] in listed
    assert listed[made_up['id']]['character_id'] == 'sheila-store-test'

    # Reopening the sent avatar from the picker shows the paint, not the bare base.
    expect(page.locator('#pubcast-avatar option', has_text='Sheila Evening Look')).to_have_count(1)
    page.locator('#pubcast-avatar').select_option(made_up['id'])
    expect(page.locator('#avatar-name')).to_have_text('Sheila Evening Look', timeout=30000)
    expect(page.locator('#status')).to_contain_text('Avatar ready')
    reopened = canvas_png(page)
    page.locator('#pubcast-avatar').select_option(original['id'])
    expect(page.locator('#avatar-name')).to_have_text('Store Sheila', timeout=30000)
    expect(page.locator('#status')).to_contain_text('Avatar ready')
    assert differs(reopened, canvas_png(page)), 'the sent avatar must carry the painted surface'


def test_saved_look_remembers_its_pubcast_avatar(mirror, live_host, tmp_path):
    page = mirror
    original = store_sheila(live_host, 'Look Origin', '')
    page.goto(live_host['url']+'/static/primp.html?avatar='+original['id'])
    expect(page.locator('#status')).to_contain_text('Avatar ready', timeout=30000)
    paint(page)
    with page.expect_download() as caught:
        page.locator('#save').click()
    caught.value.save_as(tmp_path/'look.primp')
    saved = json.loads((tmp_path/'look.primp').read_text())
    assert saved['origin'] == {'id': original['id'], 'name': 'Look Origin', 'character_id': '', 'canonical_height_in': 74.5}

    page.goto(live_host['url']+'/static/primp.html')
    page.wait_for_function('document.querySelector("#viewport canvas") && !document.querySelector("#project-file").disabled')
    page.locator('#project-file').set_input_files(str(tmp_path/'look.primp'))
    expect(page.locator('#status')).to_contain_text('Editable look reopened')
    page.locator('#send').click()
    expect(page.locator('#send-height')).to_have_value('74.5')
    assert page.locator('#send-height').evaluate('e=>e.readOnly')
    page.locator('#send-confirm').click()
    expect(page.locator('#status')).to_contain_text('Sent to PubCast', timeout=30000)
    newest = imports(live_host)[-1]
    assert newest['character_id'] == original['id'] and newest['source_name'] == 'primp:'+original['id']


def test_prepared_base_sends_at_its_own_standing_height(mirror, live_host):
    page = mirror
    page.locator('[data-base=manny]').click()
    expect(page.locator('#status')).to_contain_text('Avatar ready')
    page.locator('#send').click()
    height = float(page.locator('#send-height').input_value())
    assert abs(height - 74.0) <= 0.5 and not page.locator('#send-height').evaluate('e=>e.readOnly')
    expect(page.locator('#send-note')).to_contain_text('Primp does not resize avatars')
    page.locator('#send-name').fill('Manny Base')
    page.locator('#send-confirm').click()
    expect(page.locator('#status')).to_contain_text('Sent to PubCast as “Manny Base”', timeout=30000)
    newest = imports(live_host)[-1]
    assert newest['name'] == 'Manny Base' and newest['character_id'] == '' and newest['source_name'] == 'primp:manny'


def test_wrong_height_is_refused_with_the_servers_reason_and_work_stays_open(mirror, live_host):
    page = mirror
    page.locator('[data-base=manny]').click()
    expect(page.locator('#status')).to_contain_text('Avatar ready')
    count = len(imports(live_host))
    page.locator('#send').click()
    page.locator('#send-height').fill('40')
    page.locator('#send-confirm').click()
    expect(page.locator('#status')).to_contain_text('canonical height is 40 in')
    assert page.locator('#status').get_attribute('data-error') == 'true'
    assert len(imports(live_host)) == count
    expect(page.locator('#send')).to_be_enabled()


def test_import_page_library_links_each_avatar_to_primp(page, context, live_host):
    store_sheila(live_host, '<b>Tag</b> Sheila', '')
    context.add_init_script('sessionStorage.setItem("pubcast_token",'+json.dumps(live_host['account']['access_token'])+');')
    page.goto(live_host['url']+'/avatar-import')
    link = page.locator('#library a.primp').last
    expect(link).to_have_text('Open in Primp')
    expect(page.locator('#library b')).to_have_count(0)   # names are text, not markup
    expect(page.locator('#library li', has_text='<b>Tag</b> Sheila')).to_have_count(1)
    link.click()
    expect(page.locator('#avatar-name')).to_have_text('<b>Tag</b> Sheila', timeout=30000)
    expect(page.locator('#status')).to_contain_text('Avatar ready')

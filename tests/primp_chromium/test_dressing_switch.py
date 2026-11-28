"""The side button between the boudoir (Primp) and the mirror and stage (Avatar Foundry).

Real host, real browser: work in progress on either side survives a round trip,
and the button never sits over a control on a desktop or a phone screen.
"""
import base64
import io

from PIL import Image, ImageChops
import pytest
from playwright.sync_api import expect

UNLOAD_WARNS = '(()=>{const e=new Event("beforeunload",{cancelable:true});window.dispatchEvent(e);return e.defaultPrevented})()'


@pytest.fixture
def offline_fonts(context):
    # The Foundry page asks Google Fonts for its type; this test host has no internet.
    context.route('**/fonts.googleapis.com/**', lambda route: route.fulfill(body='', content_type='text/css'))
    context.route('**/fonts.gstatic.com/**', lambda route: route.fulfill(body=b'', content_type='font/woff2'))


def canvas_png(page):
    page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    return base64.b64decode(page.locator('#viewport canvas').evaluate('c=>c.toDataURL("image/png").split(",")[1]'))


def same(a, b):
    return ImageChops.difference(Image.open(io.BytesIO(a)).convert('RGB'), Image.open(io.BytesIO(b)).convert('RGB')).getbbox() is None


def test_primp_look_survives_a_trip_to_the_mirror_and_stage(offline_fonts, mirror, live_host):
    page = mirror
    tab = page.get_by_role('button', name='Go to the mirror and stage (Avatar Foundry). Your look comes back with you.')
    expect(tab).to_be_visible()
    expect(tab).to_contain_text('Mirror and Stage')
    page.locator('[data-base=sheila]').click()
    expect(page.locator('#status')).to_contain_text('Avatar ready')
    blank = canvas_png(page)
    page.get_by_role('button', name='Ink', exact=True).click()
    box = page.locator('#viewport canvas').bounding_box()
    x, y = box['x']+box['width']/2, box['y']+box['height']/2
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x+8, y, steps=5); page.mouse.up()
    expect(page.locator('#undo')).to_be_enabled()
    painted = canvas_png(page)
    assert not same(blank, painted)
    assert page.evaluate(UNLOAD_WARNS), 'unsaved paint must still warn before the switch'
    page.wait_for_load_state('networkidle')   # the host's production-slate overlay checks sign-in on load

    tab.click()
    page.wait_for_url('**/static/avatar_foundry.html')
    back = page.get_by_role('button', name='Go to the boudoir (Primp makeup). Your Foundry choices come back with you.')
    expect(back).to_contain_text('Boudoir')
    page.wait_for_load_state('networkidle')
    back.click()
    page.wait_for_url('**/static/primp.html')
    expect(page.locator('#status')).to_contain_text('Back from the mirror and stage', timeout=30000)
    expect(page.locator('#avatar-name')).to_have_text('sheila')
    assert same(painted, canvas_png(page)), 'the painted look must come back exactly'
    assert page.evaluate(UNLOAD_WARNS), 'the look was unsaved before the trip and must still count as unsaved'
    assert page.evaluate('sessionStorage.getItem("primp:resume-after-switch")') is None


def test_foundry_choices_survive_a_trip_to_the_boudoir(offline_fonts, mirror, live_host):
    page = mirror
    page.goto(live_host['url']+'/static/avatar_foundry.html')
    page.wait_for_selector('.preset-card')
    page.locator('#displayName').fill('Evening Sheila')
    page.locator('#energy').fill('1.6')
    page.locator('#energy').dispatch_event('input')
    page.locator('#hMode').select_option('ghost')
    page.locator('.cswatch:not(.core)[data-c="#e05599"]').click()
    was_visible = 'on' in (page.locator('#visToggle').get_attribute('class') or '').split()   # the host is shared between tests
    page.locator('#visToggle').click()
    cards = page.locator('.preset-card')
    chosen = cards.nth(cards.count()-1)
    chosen_id = chosen.locator('.preset-badge').inner_text()
    chosen.click()
    page.wait_for_load_state('networkidle')

    page.get_by_role('button', name='Go to the boudoir (Primp makeup). Your Foundry choices come back with you.').click()
    page.wait_for_url('**/static/primp.html')
    page.wait_for_function('document.querySelector("#viewport canvas") && !document.querySelector("[data-base=sheila]").disabled')
    expect(page.locator('#welcome')).to_be_visible()          # no look was open, so nothing to bring back
    assert page.locator('#status').get_attribute('data-error') != 'true'
    page.wait_for_load_state('networkidle')
    page.get_by_role('button', name='Go to the mirror and stage (Avatar Foundry). Your look comes back with you.').click()
    page.wait_for_url('**/static/avatar_foundry.html')

    expect(page.locator('#displayName')).to_have_value('Evening Sheila')
    expect(page.locator('#energy')).to_have_value('1.6')
    expect(page.locator('#energyVal')).to_have_text('1.6')
    expect(page.locator('#hMode')).to_have_value('ghost')
    expect(page.locator('.cswatch.active:not(.core)')).to_have_attribute('data-c', '#e05599')
    if was_visible:
        expect(page.locator('#visToggle')).not_to_have_class('toggle on')
    else:
        expect(page.locator('#visToggle')).to_have_class('toggle on')
    expect(page.locator('.preset-card.active .preset-badge')).to_have_text(chosen_id)
    expect(page.locator('#prevName')).to_have_text('Evening Sheila')
    assert page.evaluate('sessionStorage.getItem("foundry:draft-after-switch")') is None


@pytest.mark.parametrize('size', [(1440, 900), (1280, 720), (390, 844)])
@pytest.mark.parametrize('where', ['primp', 'foundry'])
def test_the_side_button_never_covers_a_control(offline_fonts, mirror, live_host, size, where):
    page = mirror
    page.set_viewport_size({'width': size[0], 'height': size[1]})
    if where == 'foundry':
        page.goto(live_host['url']+'/static/avatar_foundry.html')
        page.wait_for_selector('.preset-card')
    else:
        page.locator('[data-base=sheila]').click()
        expect(page.locator('#status')).to_contain_text('Avatar ready')
    tab = page.locator('#dressing-switch')
    expect(tab).to_be_visible()
    overlaps = page.evaluate('''(tab)=>{
      const t=tab.getBoundingClientRect(), hits=[];
      for (const el of document.querySelectorAll('button,a,input,select,label,.preset-card,.cswatch,.toggle,#viewport canvas')) {
        if (el===tab||tab.contains(el)||el.closest('[hidden]')) continue;
        if (getComputedStyle(el).position==='fixed') continue;   // other floating buttons are checked by sight
        for (let y=0; y<=document.documentElement.scrollHeight; y+=innerHeight/2) {
          const r=el.getBoundingClientRect(), top=r.top+scrollY-y;
          if (r.width && r.height && r.right>t.left && r.left<t.right && top+r.height>t.top && top<t.bottom) { hits.push(el.id||el.className||el.tagName); break; }
        }
      }
      return hits;}''', tab.element_handle())
    assert overlaps == [], overlaps

"""The upgraded Avatar Foundry: the Energy Sphere drawn live, its options, and honest saving.

Real host, real browser (same live-host fixture as the Primp suite).
"""
import base64
import io
import json
import urllib.request

import pytest
from PIL import Image, ImageStat
from playwright.sync_api import expect


@pytest.fixture
def foundry(context, mirror, live_host):
    # The Foundry asks Google Fonts for its type; this test host has no internet.
    context.route('**/fonts.googleapis.com/**', lambda route: route.fulfill(body='', content_type='text/css'))
    context.route('**/fonts.gstatic.com/**', lambda route: route.fulfill(body=b'', content_type='font/woff2'))
    page = mirror
    page.goto(live_host['url']+'/static/avatar_foundry.html')
    page.wait_for_selector('.preset-card[data-preset="SPHERE"]')
    page.wait_for_load_state('networkidle')
    return page


def api_me(live_host):
    request = urllib.request.Request(live_host['url']+'/api/avatars/me', headers={'Authorization': 'Bearer '+live_host['account']['access_token']})
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def canvas_stats(page, selector):
    page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
    png = page.locator(selector).screenshot()
    image = Image.open(io.BytesIO(png)).convert('RGB')
    return ImageStat.Stat(image), image


def test_energy_sphere_is_drawn_live_and_every_choice_saves(foundry, live_host):
    page = foundry
    expect(page.locator('#stage')).to_be_hidden()
    page.locator('.preset-card[data-preset="SPHERE"]').click()
    expect(page.locator('#stage')).to_be_visible()
    expect(page.locator('.preset-card[data-preset="SPHERE"]')).to_have_class('preset-card active')

    stats, image = canvas_stats(page, '#stageCanvas')
    assert max(stats.extrema[0][1], stats.extrema[1][1]) > 150, 'the stage must actually draw the sphere'
    w, h = image.size
    centre = image.getpixel((w//2, int(h*0.45)))
    corner = image.getpixel((4, 4))
    assert sum(centre) > sum(corner) + 60, 'the sphere sits lit in the middle of a dark stage'
    card_stats, _ = canvas_stats(page, '#sphereCard')
    assert max(card_stats.extrema[0][1], card_stats.extrema[1][1]) > 120, 'the form card shows a live mini sphere'

    page.locator('#moodRow [data-mood="laughing"]').click()
    expect(page.locator('#moodRow [data-mood="laughing"]')).to_have_attribute('aria-pressed', 'true')
    page.locator('.cswatch.core[data-c="#ff3fa4"]').click()
    page.locator('.cswatch:not(.core)[data-c="#4ade80"]').click()
    page.locator('#energy').fill('1.6'); page.locator('#energy').dispatch_event('input')
    page.locator('#hMode').select_option('ghost')
    page.locator('#visToggle').click()
    page.locator('#displayName').fill('Josie Sphere')
    page.get_by_role('button', name='Save Avatar').click()
    expect(page.locator('#saveStatus')).to_have_text('✓ Saved')

    saved = api_me(live_host)
    assert {k: saved[k] for k in ('preset_id', 'core_color', 'glow_color', 'energy_level', 'hologram_mode', 'visible', 'mood', 'display_name')} == {
        'preset_id': 'SPHERE', 'core_color': '#FF3FA4', 'glow_color': '#4ADE80', 'energy_level': 1.6,
        'hologram_mode': 'ghost', 'visible': False, 'mood': 'laughing', 'display_name': 'Josie Sphere'}

    page.wait_for_load_state('networkidle')   # the host's production-slate overlay checks in on load
    page.reload(); page.wait_for_load_state('networkidle')
    expect(page.locator('#stage')).to_be_visible()
    expect(page.locator('#moodRow [data-mood="laughing"]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.cswatch.core.active')).to_have_attribute('data-c', '#ff3fa4')
    expect(page.locator('.cswatch.active:not(.core)')).to_have_attribute('data-c', '#4ade80')
    expect(page.locator('#energy')).to_have_value('1.6')
    expect(page.locator('#hMode')).to_have_value('ghost')
    expect(page.locator('#visToggle')).not_to_have_class('toggle on')
    expect(page.locator('#displayName')).to_have_value('Josie Sphere')


def test_a_refused_save_says_why_instead_of_saved(foundry):
    page = foundry
    page.route('**/api/avatars/me', lambda route: route.fulfill(status=422, content_type='application/json', body=json.dumps({'detail': 'energy level must be a number from 0 to 2'}))
               if route.request.method == 'POST' else route.continue_())
    page.locator('.preset-card[data-preset="SPHERE"]').click()
    page.get_by_role('button', name='Save Avatar').click()
    expect(page.locator('#saveStatus')).to_have_text('Not saved: energy level must be a number from 0 to 2')
    expect(page.locator('#saveStatus')).to_have_class('save-status err show')


def test_other_forms_keep_their_simple_preview(foundry):
    page = foundry
    page.locator('.preset-card[data-preset="MANNY"]').click()
    expect(page.locator('#stage')).to_be_hidden()
    expect(page.locator('#prevOrb')).to_be_visible()
    expect(page.locator('.sphere-only').first).to_be_hidden()


def test_sphere_choices_survive_the_trip_to_the_boudoir(foundry):
    page = foundry
    page.locator('.preset-card[data-preset="SPHERE"]').click()
    page.locator('#moodRow [data-mood="mischief"]').click()
    page.locator('.cswatch.core[data-c="#00e0ff"]').click()
    page.wait_for_load_state('networkidle')
    page.get_by_role('button', name='Go to the boudoir (Primp makeup). Your Foundry choices come back with you.').click()
    page.wait_for_url('**/static/primp.html')
    page.wait_for_load_state('networkidle')
    page.get_by_role('button', name='Go to the mirror and stage (Avatar Foundry). Your look comes back with you.').click()
    page.wait_for_url('**/static/avatar_foundry.html')
    expect(page.locator('#stage')).to_be_visible()
    expect(page.locator('#moodRow [data-mood="mischief"]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.cswatch.core.active')).to_have_attribute('data-c', '#00e0ff')

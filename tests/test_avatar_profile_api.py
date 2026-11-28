"""/api/avatars/me keeps everything the Avatar Foundry sets, and refuses bad values with a reason.

Before 2026-11-28 the route dropped energy level, hologram mode and visibility, and the
Foundry's chosen form never saved (it sent "preset", the route read only "preset_id").
"""
import pytest
from fastapi.testclient import TestClient

from modules.avatar import AvatarProfileError, AvatarState, apply_profile_update, list_presets, profile_view

FULL = {'preset_id': 'SPHERE', 'glow_color': '#e05599', 'core_color': '#ffc42e', 'display_name': 'Josie',
        'energy_level': 1.6, 'hologram_mode': 'ghost', 'visible': False, 'mood': 'mischief'}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import main
    monkeypatch.setattr(main, 'DATA_DIR', tmp_path)
    return TestClient(main.app)


def test_energy_sphere_is_a_listed_form():
    sphere = next(p for p in list_presets() if p.preset_id == 'SPHERE')
    assert sphere.name == 'Energy Sphere' and sphere.body_type == 'sphere'


def test_everything_the_foundry_saves_comes_back(client):
    r = client.post('/api/avatars/me', json=FULL)
    assert r.status_code == 200, r.text
    got = client.get('/api/avatars/me').json()
    assert {k: got[k] for k in FULL} == {**FULL, 'glow_color': '#E05599', 'core_color': '#FFC42E'}


def test_old_preset_field_name_still_saves_the_form(client):
    assert client.post('/api/avatars/me', json={'preset': 'sphere'}).status_code == 200
    assert client.get('/api/avatars/me').json()['preset_id'] == 'SPHERE'


@pytest.mark.parametrize('bad, reason', [
    ({'preset_id': 'NOPE'}, 'unknown avatar form'),
    ({'energy_level': 3}, 'energy level'),
    ({'energy_level': 'lots'}, 'energy level'),
    ({'hologram_mode': 'plasma'}, 'hologram mode'),
    ({'visible': 'yes'}, 'visible'),
    ({'core_color': 'red'}, 'core colour'),
    ({'glow_color': 'not-a-colour'}, 'glow colour'),
    ({'mood': 'Very Happy!'}, 'mood'),
    ({'display_name': 'x' * 41}, 'display name'),
])
def test_bad_values_are_refused_and_nothing_half_saves(client, bad, reason):
    client.post('/api/avatars/me', json=FULL)
    r = client.post('/api/avatars/me', json={**bad, 'display_name': bad.get('display_name', 'Changed')})
    assert r.status_code == 422 and reason in r.json()['detail']
    assert client.get('/api/avatars/me').json()['display_name'] == 'Josie'


def test_dressing_room_payload_still_saves(client):
    # static/dressing.js sends uppercase moods and fields this route ignores
    r = client.post('/api/avatars/me', json={'display_name': 'D', 'gender': 'neutral', 'mood': 'ELEVATED', 'primary_color': '#ff0000'})
    assert r.status_code == 200 and r.json()['mood'] == 'elevated'


def test_update_only_touches_fields_present():
    base = AvatarState(user_id='u', energy_level=0.4, hologram_mode='solid', metadata={'mood': 'sad', 'core_color': '#00E0FF'})
    out = apply_profile_update(base, {'display_name': 'New'})
    assert (out.energy_level, out.hologram_mode, out.metadata['mood'], out.metadata['core_color']) == (0.4, 'solid', 'sad', '#00E0FF')
    with pytest.raises(AvatarProfileError):
        apply_profile_update(base, {'visible': 1})
    assert profile_view(AvatarState(user_id='u'))['core_color'] == '#FFC42E'

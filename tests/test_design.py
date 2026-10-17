"""The redesign's presenter (design.py) and macros (templates/_ui.html, _base.html).

Golden values come from the approved mocks' own build code (scratchpad landing/hybrid4/build.py, pages/lists/
build.py, names/fit.py), run on the same inputs: the port must reproduce them exactly. The clock is frozen to
FIXTURE_NOW (2026-10-02 12:00 UTC, conftest.py); time-dependent tests pass `now` / `today` explicitly."""
import re
from datetime import date, datetime, timezone

import pytest

import app as A
import design as D
import photos
import site_pages

UTC = timezone.utc
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
TIME = re.compile(r'<time class="fight-time[^"]*" datetime="([^"]*)"[^>]*>([^<]*)</time>')


def ev(**kw):
    """A landing event as site_pages._group_events_for_landing builds it."""
    e = {'title': 'Daniel Dubois vs Fabio Wardley', 'fighter1': 'Daniel Dubois', 'fighter2': 'Fabio Wardley',
         'fighter1_image': '/persisted-fighters/daniel-dubois.jpg?v=1', 'fighter2_image': '/persisted-fighters/fabio-wardley.jpg?v=2',
         'date': '2026-10-17', 'time': '18:00', 'time_estimated': False, 'venue': 'London', 'location': 'London',
         'streaming': 'DAZN', 'fight_count': 5, 'sport': 'Boxing', 'undercard': [], 'weight_class': 'Title Heavyweight',
         'event_name': '', 'path': '/boxing-event/daniel-dubois-vs-fabio-wardley-2026-10-17', 'is_past': False,
         'result': None, 'result_pending': False}
    e.update(kw)
    return e


def ufc(**kw):
    e = ev(title='UFC 333: Volkanovski vs. Evloev', fighter1='Alexander Volkanovski', fighter2='Movsar Evloev',
           fighter1_image='/persisted-fighters/alexander-volkanovski.jpg', fighter2_image='/static/fighters/movsar-evloev.png',
           date='2026-10-24', time='18:00', venue='Etihad Arena', location='Etihad Arena', streaming='Paramount+',
           fight_count=13, sport='UFC', weight_class='', event_name='UFC 333: Volkanovski vs. Evloev',
           path='/event/ufc-333-volkanovski-vs.-evloev-2026-10-24',
           undercard=[{'fighter1': 'A One', 'fighter2': 'B Two', 'card_type': 'Main Card', 'date': '2026-10-24', 'time': '18:00'},
                      {'fighter1': 'C Three', 'fighter2': 'D Four', 'card_type': 'Prelims', 'date': '2026-10-24', 'time': '16:00'}])
    e.update(kw)
    return e


@pytest.fixture
def meta(monkeypatch):
    """photos.photo_meta() from a dict {path without query: meta}."""
    table = {}
    monkeypatch.setattr(photos, 'photo_meta', lambda p: table.get((p or '').split('?')[0]), raising=False)
    return table


def render(src, **ctx):
    with A.app.test_request_context('/'):
        return A.app.jinja_env.from_string(src).render(**ctx)


# --------------------------------------------------------------------------- names
@pytest.mark.parametrize('name, want', [
    ('Alexander Volkanovski', 'Volkanovski'), ('Julio Cesar Chavez Jr.', 'Chavez'), ('Isaac "Pitbull" Cruz', 'Cruz'),
    ('Alexy de la Cruz', 'de la Cruz'), ('Zhang Weili', 'Zhang'), ('Nico Ali Walsh', 'Walsh'),
    ('Charles Oliveira 2', 'Oliveira'), ('Christopher Guerrero-Martínez Jr.', 'Guerrero-Martínez'),
    ('Kai Kamaka III', 'Kamaka'), ('Joshua Van', 'Van'), ('TBA', 'TBA'), ('', 'TBA'), (None, 'TBA')])
def test_surname_keeps_particles_and_family_first_names(name, want):
    assert D.surname(name) == want


def test_given_name_and_family_part():
    assert D.name_split('Alexander Volkanovski') == ('Alexander', 'Volkanovski')
    assert D.name_split('Christopher Guerrero-Martínez Jr.') == ('Christopher', 'Guerrero-Martínez Jr.')
    assert D.name_split('Alexy de la Cruz') == ('Alexy', 'de la Cruz')
    assert D.name_split('Zhang Weili') == ('', 'Zhang Weili')
    assert D.name_split('Madonna') == ('', 'Madonna')
    assert D.name_split('TBA') == ('', 'TBA')
    assert D.given_name('Isaac "Pitbull" Cruz') == 'Isaac "Pitbull"'


def test_app_surname_is_still_formattings():
    import formatting
    assert A.surname is formatting.surname
    assert A.surname('Alexy de la Cruz') == 'Cruz'     # production's rule, unchanged


@pytest.mark.parametrize('text, em, broken', [
    ('YAN', 1.59, False), ('Volkanovski', 5.433, False), ('Guerrero-Martínez', 4.435, True),
    ('Asofa-Solomona', 4.459, True), ('Kondratavičius', 6.713, False), ('O’Doherty', 4.211, False),
    ('Álvarez', 3.335, False)])
def test_name_widths_match_fit_py(text, em, broken):
    w, b = D.line_em(text)
    assert round(w, 3) == em and b is broken


def test_unknown_letters_count_as_most_of_an_m():
    assert D.name_em('#') == pytest.approx(.839 * .8)


@pytest.mark.parametrize('a, b, stacked, one, card', [
    ('Yan', 'Gane', (2.09, False, False), 5.08, (0, 0, 1.954, 2)),
    ('Volkanovski', 'Evloev', (5.43, False, False), 9.7, (0, 1, 5.077, 2)),
    ('Guerrero-Martínez', 'Abdulloev', (4.43, True, False), 14.23, (0, 1, 4.142, 3)),
    ('Ko', 'TBA', (1.05, False, False), 3.17, (0, 0, .982, 2)),
    ('Asofa-Solomona', 'Gallen', (4.46, True, False), 11.72, (0, 0, 4.17, 3)),
    ('Dubois', 'Wardley', (3.71, False, False), 7.94, (0, 0, 3.469, 2))])
def test_pair_fitting_matches_the_mock(a, b, stacked, one, card):
    assert D.stacked_em(a, b) == stacked
    assert D.one_line_em(a, b) == one
    assert D.card_names(a, b, D.is_tba(b)) == card


@pytest.mark.parametrize('name, lsb, rsb', [
    ('Dubois', .05, .031), ('Wardley', .02, .0065), ('Volkanovski', .015, .0485), ('Evloev', .05, .0145),
    ('Ščerba', .0325, .019), ('Íñigo', .05, .0405)])
def test_side_bearings(name, lsb, rsb):
    assert (D.bearing(name, 0), D.bearing(name, 1)) == (lsb, rsb)


def test_pair_fit_gives_the_mocks_css_numbers():
    f = D.pair_fit(ev())
    assert (f['e1'], f['e2'], f['em_stack'], f['est'], f['nl'], f['sd'], f['sp']) == (2.643, 3.473, 3.71, 3.469, 2, 0, 0)
    assert f['n1'] == {'text': 'Dubois', 'tba': False, 'parts': None, 'style': '--lsb:0.05;--rsb:0.031'}
    g = D.pair_fit(ufc())
    assert (g['e1'], g['e2'], g['em_stack'], g['est'], g['sp']) == (5.08, 2.678, 5.43, 5.077, 1)
    h = D.pair_fit(ev(fighter1='Christopher Guerrero-Martínez Jr.', fighter2='TBA'))
    assert h['n1']['parts'] == ('Guerrero-', 'Martínez') and h['n2']['tba'] and h['tba2']


def test_list_and_box_widths():
    assert D.list_em(ev()) == 3.71
    assert D.box_em('Brendan Allen', 'Christian Leroy Duncan') == round(max(D.name_em('Allen'), D.name_em('Duncan')), 2)
    assert D.full_em('Alexander Volkanovski') == round(D.name_em('Alexander Volkanovski') * D.EMK, 2)


def test_title_order_follows_the_event_title():
    e = ufc(title='UFC 334: Gane vs. Hokit', fighter1='Jhonata Hokit', fighter2='Ciryl Gane',
            fighter1_image='/h.png', fighter2_image='/g.png')
    t = D.title_order(e)
    assert (t['fighter1'], t['fighter2'], t['fighter1_image'], t['fighter2_image']) == ('Ciryl Gane', 'Jhonata Hokit', '/g.png', '/h.png')
    assert e['fighter1'] == 'Jhonata Hokit', 'the input is not mutated'
    assert D.title_order(ev()) is not None and D.title_order(ev())['fighter1'] == 'Daniel Dubois'
    assert D.title_order(ev(fighter2='TBA'))['fighter2'] == 'TBA'


# --------------------------------------------------------------------------- photos
DUBOIS = {'w': 400, 'h': 400, 'face': True, 'ex': .4696, 'ey': .2665, 'em': .1068, 'box_h': .2859, 'crown': .045,
          'score': .93, 'b': 1.107, 'c': .929, 'backdrop': None, 'cut': False, 'x0': 0.0, 'x1': 1.0}


def test_poster_half_without_metadata_uses_the_fallback(meta):
    p = D.poster_half('/persisted-fighters/x.jpg?v=3')
    assert p == {'src': '/persisted-fighters/x.jpg?v=3', 'cls': 'nometa', 'copies': ['bf'],
                 'style': '--ar:1;--ex:0.5;--ey:0.33;--em:0.08;--sw:4000;--x0:0;--x1:1;--sh:0'}
    assert D.poster_half(None) is None and D.poster_half('') is None


def test_poster_half_with_metadata_gives_the_mocks_numbers(meta):
    meta['/persisted-fighters/daniel-dubois.jpg'] = DUBOIS
    p = D.poster_half('/persisted-fighters/daniel-dubois.jpg?v=1')
    assert p['style'] == '--ar:1;--ex:0.4696;--ey:0.2665;--em:0.1068;--sw:400;--x0:0;--x1:1;--sh:0;--b:1.107;--c:0.929;--cy:0.045'
    assert p['cls'] == '' and p['copies'] == ['bf']


def test_poster_half_kinds(meta):
    meta['/cut.png'] = dict(DUBOIS, w=400, h=300, cut=True)                 # Evloev: a UFC.com cut-out
    meta['/cur.jpg'] = dict(DUBOIS, x1=.665)                                 # Volkanovski: a bystander right of 66.5 %
    meta['/short.jpg'] = dict(DUBOIS, w=299, h=168, backdrop='lt')           # Puello: too short, light backdrop
    meta['/ko.jpg'] = dict(DUBOIS, backdrop='ko')
    meta['/bad.jpg'] = dict(DUBOIS, x0=.5, x1=.55, ex='nan', b='x')          # nonsense values
    cut = D.poster_half('/cut.png')
    assert cut['cls'] == 'cut' and cut['copies'] == [] and '--ar:1.3333;' in cut['style'] and '--sh:1' in cut['style']
    assert D.poster_half('/cur.jpg')['cls'] == 'cr'
    short = D.poster_half('/short.jpg')
    assert short['cls'] == 'lt sh' and short['copies'] == ['bf', 'bf bt', 'bf bb']
    assert D.poster_half('/ko.jpg')['cls'] == 'ko' and D.poster_half('/ko.jpg')['copies'] == []
    bad = D.poster_half('/bad.jpg')
    assert '--x0:0;--x1:1' in bad['style'] and '--ex:0.5;' in bad['style'] and '--b:' not in bad['style']


def test_photo_meta_errors_never_reach_a_page(monkeypatch):
    def boom(p):
        raise ValueError('corrupt metadata')
    monkeypatch.setattr(photos, 'photo_meta', boom, raising=False)
    assert D.photo_meta('/x.jpg') is None
    assert 'nometa' in D.poster_half('/x.jpg')['cls']
    monkeypatch.delattr(photos, 'photo_meta', raising=False)
    assert D.photo_meta('/x.jpg') is None


def test_poster_photos(meta):
    a, b, n = D.poster_photos(ev())
    assert a and b and n == 2
    assert D.poster_photos(ev(fighter2='TBA'))[2] == 1
    assert D.poster_photos(ev(fighter2_image='/persisted-fighters/daniel-dubois.jpg?v=9'))[2] == 1, 'one picture twice'
    assert D.poster_photos(ev(fighter1_image=None, fighter2_image=None))[2] == 0


def test_face_crops(meta):
    meta['/static/fighters/brendan-allen.png'] = {'w': 400, 'h': 300, 'face': True, 'ex': .4897, 'ey': .3735, 'em': .1804,
                                                  'box_h': .5281, 'cut': True, 'backdrop': None}
    meta['/persisted-fighters/floyd-schofield.jpg'] = {'w': 500, 'h': 468, 'face': True, 'ex': .4754, 'ey': .3403,
                                                       'em': .0729, 'box_h': .2007, 'backdrop': 'lt'}
    meta['/tiny.jpg'] = {'w': 400, 'h': 400, 'face': True, 'ex': .5, 'ey': .5, 'em': .01, 'box_h': .03}
    meta['/noface.jpg'] = {'w': 400, 'h': 400, 'face': False}
    assert D.face_crop('/static/fighters/brendan-allen.png')['style'] == '--px:0.486;--py:0.455;--z:1.1'   # the mock's
    sch = D.face_crop('/persisted-fighters/floyd-schofield.jpg')
    assert sch['style'] == '--px:0.474;--py:0.373;--z:2.74' and sch['tone'] == 'lt'
    assert D.face_crop('/tiny.jpg') is None, 'a 12 px face is not a usable crop: the grey disc'
    assert D.face_crop('/noface.jpg')['style'] == '--px:.5;--py:0.366;--z:1.3'
    assert D.face_crop('/unmeasured.jpg')['style'] == '--px:.5;--py:0.366;--z:1.3'
    assert D.face_crop(None) is None


# --------------------------------------------------------------------------- times
def test_utc_start_and_local_day():
    assert D.utc_start('2026-10-17', '18:00') == datetime(2026, 10, 17, 18, 0, tzinfo=UTC)
    assert D.utc_start('2026-10-17', '9:05') == datetime(2026, 10, 17, 9, 5, tzinfo=UTC)
    for bad in ('TBA', '', None, 'evening', 18):
        assert D.utc_start('2026-10-17', bad) is None
    assert D.utc_start('not-a-date', '18:00') is None
    e = ev(date='2026-10-16', time='23:00')
    assert D.local_day(e) == date(2026, 10, 16)
    assert D.local_day(e, 'Europe/Tallinn') == date(2026, 10, 17)
    assert D.local_day(ev(time='TBA'), 'Europe/Tallinn') == date(2026, 10, 17)
    assert D.local_day(ev(date=None, time=None)) is None


def test_night_hints_and_night_day():
    sat_2am = datetime(2026, 10, 17, 2, 0, tzinfo=UTC)
    assert D.night_hint(sat_2am) == 'Fri–Sat night'
    assert D.night_hint(datetime(2026, 10, 17, 5, 59, tzinfo=UTC)) == 'Fri–Sat night'
    assert D.night_hint(datetime(2026, 10, 17, 6, 0, tzinfo=UTC)) == ''
    assert D.night_hint(datetime(2026, 10, 19, 1, 0, tzinfo=UTC)) == 'Sun–Mon night'
    assert D.night_hint(None) == ''
    e = ev(date='2026-10-16', time='23:00')                 # 02:00 Saturday in Tallinn
    assert D.night_day(e, 'Europe/Tallinn') == date(2026, 10, 16)
    assert D.night_day(e) == date(2026, 10, 16)


@pytest.mark.parametrize('n, want', [(0, 'Today'), (1, 'Tomorrow'), (4, 'in 4 days'), (-1, 'Yesterday'), (-3, '3 days ago')])
def test_day_counts(n, want):
    today = date(2026, 10, 2)
    assert D.rel_day(date.fromordinal(today.toordinal() + n), today) == want


def test_countdown_only_in_the_last_day():
    s = datetime(2026, 10, 2, 21, 12, tzinfo=UTC)
    assert D.countdown(s, NOW) == 'in 9 h 12 min'
    assert D.countdown(datetime(2026, 10, 2, 12, 42, tzinfo=UTC), NOW) == 'in 42 min'
    assert D.countdown(NOW, NOW) == 'starting now'
    # a page left open: 'starting now' until 15 min after the start, then nothing (never next to "Yesterday")
    assert D.countdown(datetime(2026, 10, 2, 11, 46, tzinfo=UTC), NOW) == 'starting now'
    assert D.countdown(datetime(2026, 10, 2, 11, 45, tzinfo=UTC), NOW) == ''
    assert D.countdown(datetime(2026, 10, 1, 21, 0, tzinfo=UTC), NOW) == ''
    assert D.countdown(datetime(2026, 10, 3, 12, 0, tzinfo=UTC), NOW) == ''
    assert D.countdown(None, NOW) == ''


def test_zone_labels():
    at = datetime(2026, 10, 13, 21, 0, tzinfo=UTC)
    assert D.tz_label(None) == 'UTC'
    assert D.tz_label('Europe/Tallinn', at) == 'Tallinn (GMT+3)'
    assert D.tz_label('America/New_York', at) == 'New York (GMT−4)'
    assert D.tz_label('Asia/Kolkata', at) == 'Kolkata (GMT+5:30)'
    assert D.zone('Not/AZone') is UTC


def test_notes_under_a_time():
    e = ufc(date='2026-10-25', time='03:00', time_estimated=True,
            undercard=[{'card_type': 'Prelims', 'date': '2026-10-25', 'time': '00:00', 'fighter1': 'a', 'fighter2': 'b'},
                       {'card_type': 'Prelims', 'date': '2026-10-24', 'time': '23:00', 'fighter1': 'c', 'fighter2': 'd'}])
    assert D.prelim_start(e) == datetime(2026, 10, 24, 23, 0, tzinfo=UTC), 'the earliest prelim, across UTC midnight'
    assert D.time_notes(e) == [('est', 'Estimated'), ('night', 'Sat–Sun night'), ('prelims', datetime(2026, 10, 24, 23, 0, tzinfo=UTC))]
    assert D.time_notes(e, 'America/New_York')[1:] == [('prelims', datetime(2026, 10, 24, 23, 0, tzinfo=UTC))]
    assert D.time_notes(e, live=True) == [('since', datetime(2026, 10, 25, 3, 0, tzinfo=UTC))]
    assert D.time_notes(ev(time='TBA')) == []
    assert D.prelim_start(ev()) is None


def test_fight_state():
    e = ufc(date='2026-10-02', time='14:00', undercard=[{'card_type': 'Prelims', 'date': '2026-10-02', 'time': '12:00'}])
    assert D.fight_state(e, datetime(2026, 10, 2, 11, 0, tzinfo=UTC)) == ''
    assert D.fight_state(e, datetime(2026, 10, 2, 12, 30, tzinfo=UTC)) == 'prelims'
    assert D.fight_state(e, datetime(2026, 10, 2, 15, 0, tzinfo=UTC)) == 'live'
    assert D.fight_state(e, datetime(2026, 10, 2, 18, 0, tzinfo=UTC)) == 'done'
    assert D.fight_state(ev(is_past=True)) == 'done'
    assert D.fight_state(ev(time='TBA')) == ''


# --------------------------------------------------------------------------- text
@pytest.mark.parametrize('v, place, city', [
    ('Etihad Arena', 'Abu Dhabi', 'Abu Dhabi'), ('Meta APEX', 'Las Vegas', 'Las Vegas'),
    ('San Juan, Puerto Rico:', 'San Juan, Puerto Rico', 'San Juan'),
    ('Coliseo Roberto Clemente, San Juan, Puerto Rico', 'Coliseo Roberto Clemente, San Juan, Puerto Rico', 'San Juan'),
    ('Sydney, Australia.', 'Sydney, Australia', 'Sydney'), ('Chandler, Ariz.', 'Chandler, Ariz.', 'Chandler'),
    ('Crypto.com Arena in Los Angeles', 'Los Angeles', 'Los Angeles'), ('Meta Apex in Las Vegas', 'Las Vegas', 'Las Vegas'),
    ('TBA', '', ''), ('', '', '')])
def test_venue_to_city(v, place, city):
    e = {'venue': v, 'location': v}
    assert D.place(e) == place and D.city(e) == city


def test_place_line_for_fight_pages():
    assert D.place_line({'venue': 'Etihad Arena'}) == 'Etihad Arena · Abu Dhabi'
    assert D.place_line({'venue': 'Crypto.com Arena in Los Angeles'}) == 'Crypto.com Arena · Los Angeles'
    assert D.place_line({'venue': 'Coliseo Roberto Clemente, San Juan, Puerto Rico'}) == \
        'Coliseo Roberto Clemente · San Juan, Puerto Rico'
    assert D.place_line({'venue': 'London'}) == 'London'


@pytest.mark.parametrize('w, want', [('Title Heavyweight', 'Heavyweight title'), ('Junior Middleweight', 'Jr middleweight'),
                                     ('Title Junior Middleweight', 'Jr middleweight title'), ('', ''), (None, ''),
                                     ('Lightweight', 'Lightweight'), ('Title', 'Title fight')])
def test_weight_labels(w, want):
    assert D.weight_label(w) == want


def test_labels_and_sizes():
    assert D.kick_text(ufc()) == 'UFC 333' and D.event_label(ufc()) == 'UFC 333'
    assert D.kick_text(ufc(event_name='UFC Fight Night: Allen vs. Duncan')) == 'UFC Fight Night'
    assert D.kick_text(ev()) == 'Heavyweight title' and D.event_label(ev()) == 'Boxing'
    assert D.kick_text(ev(weight_class='')) == ''
    assert D.fights_n(5) == '5\u00a0fights' and D.fights_n(1) == '1\u00a0fight'
    assert D.card_size(ev(fight_count=2, undercard=[{}, {}, {}])) == 4
    assert D.event_key(ev()) == 'daniel-dubois-vs-fabio-wardley-2026-10-17'
    assert D.sport_class(ufc()) == 'ufc' and D.sport_class(ev()) == 'boxing'


# --------------------------------------------------------------------------- the schedule table
def _sched_events():
    return [
        ev(title='A', path='/boxing-event/a-2026-10-02', date='2026-10-02', time='20:00'),       # today
        ev(title='B', path='/boxing-event/b-2026-10-08', date='2026-10-08', time='23:00'),       # day 6 -> This week
        ev(title='C', path='/boxing-event/c-2026-10-09', date='2026-10-09', time='02:00'),       # 02:00 day 7: night of day 6
        ev(title='D', path='/boxing-event/d-2026-10-09', date='2026-10-09', time='19:00'),       # day 7 -> Next week
        ev(title='E', path='/boxing-event/e-2026-10-30', date='2026-10-30', time='TBA'),         # day 28 -> Later
        ev(title='F', path='/boxing-event/f-2026-09-30', date='2026-09-30', time='20:00'),       # past: left out
    ]


def test_schedule_groups_by_week_and_night():
    s = D.schedule(_sched_events(), today=date(2026, 10, 2), now=NOW)
    assert [g['id'] for g in s['groups']] == ['week', 'next', 'later'] and s['count'] == 5
    days = {g['id']: [(b['iso'], [r['e']['title'] for r in b['rows']]) for b in g['blocks']] for g in s['groups']}
    assert days['week'] == [('2026-10-02', ['A']), ('2026-10-08', ['B']), ('2026-10-09', ['C'])]
    assert days['next'] == [('2026-10-09', ['D'])]
    assert days['later'] == [('2026-10-30', ['E'])]
    first = s['groups'][0]['blocks'][0]
    assert (first['full'], first['dm'], first['short'], first['rel'], first['soon']) == \
        ('Friday', '2 October', 'Fri 2 Oct', 'Today', True)


def test_schedule_survives_odd_data():
    odd = [ev(title='nodate', path='/x/nodate', date=None, time=None), ev(title='bad', path='/x/bad', date='soon', time='TBA'),
           ev(title='ok', path='/x/ok', date='2026-10-03', time='nonsense')]
    s = D.schedule(odd, today=date(2026, 10, 2), now=NOW)
    assert s['count'] == 1 and s['groups'][0]['blocks'][0]['rows'][0]['e']['title'] == 'ok'


def test_schedule_keeps_empty_weeks_and_drops_empty_later():
    s = D.schedule([ev(title='X', path='/boxing-event/x', date='2026-10-12', time='18:00')], today=date(2026, 10, 2), now=NOW)
    assert [(g['id'], g['count']) for g in s['groups']] == [('week', 0), ('next', 1)]
    assert s['groups'][0]['when'] == 'this week'


def test_schedule_pointer_rows_and_beyond():
    evs = _sched_events()
    s = D.schedule(evs, today=date(2026, 10, 2), now=NOW, lead_keys={'b-2026-10-08': 'lead'}, beyond_keys={'e-2026-10-30'})
    rows = [r for g in s['groups'] for b in g['blocks'] for r in b.get('rows', [])]
    assert [r['kind'] for r in rows if r['e']['title'] == 'B'] == ['ptr'] and rows[1]['hid'] == 'lead'
    ahead = s['groups'][-1]
    assert ahead['id'] == 'ahead' and ahead['sub'] == 'headline events only' and ahead['count'] == 1
    d = D.schedule(evs, today=date(2026, 10, 2), now=NOW, lead_keys={'b-2026-10-08': 'lead'}, ptr='drop')
    assert '2026-10-08' not in [b['iso'] for g in d['groups'] for b in g['blocks']], 'a day of only hero fights is left out'


def test_clock_change_rows_between_and_inside_days():
    sat = ev(title='Sat', path='/x/sat', date='2026-10-24', time='18:00')       # 21:00 Tallinn, GMT+3
    sun = ev(title='Sun', path='/x/sun', date='2026-10-25', time='19:00')       # 21:00 Tallinn, GMT+2
    s = D.schedule([sat, sun], today=date(2026, 10, 20), tz='Europe/Tallinn', now=NOW)
    blocks = s['groups'][0]['blocks']
    assert [b['kind'] for b in blocks] == ['day', 'dst', 'day']
    c = blocks[1]
    assert (c['outside'], c['word'], c['by'], c['date_text'], c['hm'], c['gmt'], c['from'], c['to']) == \
        (True, 'back', 'an hour', 'Sun 25 Oct', '04:00', 'GMT+2', 180, 120)
    early = ev(title='Early', path='/x/early', date='2026-10-25', time='00:30')  # 03:30 Tallinn, before the change
    s2 = D.schedule([early, sun], today=date(2026, 10, 20), tz='Europe/Tallinn', now=NOW)
    rows = s2['groups'][0]['blocks'][0]['rows']
    assert [r['kind'] for r in rows] == ['ev', 'dst', 'ev'] and rows[1]['outside'] is False
    assert D.schedule([sat, sun], today=date(2026, 10, 20), now=NOW)['groups'][0]['blocks'][1]['kind'] == 'day', 'UTC never changes'


def test_clock_change_by_half_an_hour():
    a = ev(date='2026-04-04', time='10:00')
    b = ev(date='2026-04-05', time='10:00')
    c = D.clock_change(a, b, 'Australia/Lord_Howe')
    assert c['by'] == '30 minutes' and c['word'] == 'back'
    assert D.clock_change(a, ev(time='TBA')) is None


def test_row_view():
    v = D.row_view(ev(venue='Coliseo Roberto Clemente, San Juan, Puerto Rico', location='Coliseo Roberto Clemente, San Juan, Puerto Rico'), now=NOW)
    assert v['where'] == 'San Juan' and v['where_short'] == ''
    v = D.row_view(ev(weight_class='', location='Chandler, Ariz.'), now=NOW)
    assert 'nokick' in v['cls'] and v['where'] == 'Chandler, Ariz.' and v['where_short'] == 'Chandler'
    assert 'has-uc' in D.row_view(ufc(), now=NOW)['cls']


def test_undercard_groups():
    g = D.undercard_groups(ufc())
    assert [(x['name'], x['start'], len(x['bouts'])) for x in g] == [
        ('Main card', datetime(2026, 10, 24, 18, 0, tzinfo=UTC), 1), ('Prelims', datetime(2026, 10, 24, 16, 0, tzinfo=UTC), 1)]
    many = ev(undercard=[{'fighter1': f'A{i}', 'fighter2': f'B{i}'} for i in range(9)])
    g = D.undercard_groups(many)
    assert [(x['name'], len(x['bouts']), x['cont'], x['k0']) for x in g] == [('Undercard', 5, False, 0), ('Undercard, cont.', 4, True, 5)]
    res = D.undercard_groups(ev(undercard=[{'fighter1': 'a', 'fighter2': 'b', 'result': {'outcome': 'win'}}, {'fighter1': 'c', 'fighter2': 'd'}]), results=True)
    assert res[0]['note'] == '1 of 2 with a result'
    assert D.undercard_groups(ev()) == []


# --------------------------------------------------------------------------- results
@pytest.mark.parametrize('outcome, method, rd, tm, want', [
    ('win', 'KO (head kick)', '2', '0:22', ('KO', 'R2 0:22', 'Knockout (head kick)')),
    ('win', 'Decision (unanimous)', '3', None, ('UD', '3 rds', 'Unanimous decision')),
    ('win', 'Submission (rear-naked choke)', '5', '2:46', ('SUB', 'R5 2:46', 'Rear-naked choke')),
    ('win', 'TKO (punches)', '7', '1:31', ('TKO', 'R7 1:31', 'Technical knockout (punches)')),
    ('win', 'UD', '12', None, ('UD', '12 rds', 'Unanimous decision')),
    ('win', 'SD', '12', None, ('SD', '12 rds', 'Split decision')),
    ('win', 'KO', '3', '1:00', ('KO', 'R3 1:00', 'Knockout')),
    ('win', 'Decision (split)', '3', None, ('SD', '3 rds', 'Split decision')),
    ('draw', 'Decision (majority)', '12', None, ('DRAW', '12 rds', 'Majority draw')),
    ('draw', 'Draw (majority)', '10', None, ('DRAW', '10 rds', 'Majority draw')),
    ('nc', 'No contest (accidental clash of heads)', '2', '1:12', ('NC', 'R2 1:12', 'No contest (accidental clash of heads)')),
    ('win', 'KO (slam)', '1', '0:40', ('KO', 'R1 0:40', 'Knockout (slam)')),
    # beyond the mock's sample: methods seen in the Wikipedia records
    ('win', 'PTS', '8', None, ('PTS', '8 rds', 'Points decision')),
    ('win', 'Disqualification (low blows)', '4', '2:00', ('DQ', 'R4 2:00', 'Disqualification (low blows)')),
    ('win', 'RTD', '6', None, ('RTD', '6 rds', 'Retirement')),
    ('win', 'Decision (technical)', '3', None, ('TD', '3 rds', 'Technical decision')),
    ('win', 'Overturned', None, None, ('', '', 'Overturned'))])
def test_method_codes(outcome, method, rd, tm, want):
    assert D.method_parts({'outcome': outcome, 'method': method, 'round': rd, 'time': tm}) == want


def test_method_parts_without_a_result():
    assert D.method_parts(None) is None and D.method_parts({}) is None


def test_results_winner_first_and_text():
    r = {'outcome': 'win', 'winner': 'Fabio Wardley', 'method': 'KO', 'round': '3', 'time': '1:00'}
    sides = D.result_sides(ev(result=r))
    assert [(s['name'], s['won'], s['lost'], s['second']) for s in sides] == [
        ('Fabio Wardley', True, False, True), ('Daniel Dubois', False, True, False)]
    assert D.result_text(ev(result=r)) == 'Fabio Wardley won, Knockout, R3 1:00.'
    draw = {'outcome': 'draw', 'method': 'Decision (majority)', 'round': '12'}
    assert [s['name'] for s in D.result_sides(ev(result=draw))] == ['Daniel Dubois', 'Fabio Wardley']
    assert D.result_text(ev(result=draw)) == 'Majority draw, 12 rds.'
    assert D.result_text(ev()) == ''


def test_bout_results():
    win = {'fighter1': 'A', 'fighter2': 'B', 'result': {'outcome': 'win', 'winner': 'B', 'method': 'UD', 'round': '3'}}
    assert D.bout_result(win) == {'kind': 'win', 'first': 'B', 'second': 'A', 'code': 'UD', 'detail': '3 rds', 'words': 'Unanimous decision'}
    assert D.bout_result({'fighter1': 'A', 'fighter2': 'B', 'result': {'outcome': 'nc', 'method': 'No contest'}})['kind'] == 'nc'
    assert D.bout_result({'fighter1': 'A', 'fighter2': 'TBA'})['kind'] == 'none'


def test_results_packing():
    assert [D.pack(k) for k in range(0, 13)] == [[], [1], [2], [3], [4], [2, 3], [3, 3], [3, 4], [4, 4], [3, 3, 3],
                                                  [3, 3, 4], [3, 4, 4], [4, 4, 4]]
    assert [s for _, s in D.results_rows(list('abcde'))] == [6, 6, 4, 4, 4]
    assert [s for _, s in D.results_rows(list('a'))] == [12]


def test_results_split():
    items = [ev(title='old', date='2026-09-20', result=None, result_pending=False),
             ev(title='due', date='2026-10-01', result=None, result_pending=True),
             ev(title='won', date='2026-09-28', result={'outcome': 'win', 'winner': 'Daniel Dubois', 'method': 'UD'}),
             ev(title='newer', date='2026-09-30', result={'outcome': 'win', 'winner': 'Daniel Dubois', 'method': 'UD'})]
    dec, pen, none = D.results_split(items)
    assert [x['title'] for x in dec] == ['newer', 'won'] and [x['title'] for x in pen] == ['due'] and [x['title'] for x in none] == ['old']


# --------------------------------------------------------------------------- the hero
def test_hero_fights_follow_big_fight_rules(monkeypatch):
    a = ev(title='a', date='2026-10-10', path='/x/a')
    b = ufc(title='b', date='2026-10-05', path='/x/b')
    done = ev(title='done', date='2026-10-02', time='06:00', path='/x/done')       # started 6 h before NOW: finished
    c = ev(title='c', date='2026-10-20', path='/x/c')
    monkeypatch.setattr(site_pages, '_big_fights', lambda events, today: [x for x in events])
    got = D.hero_fights([a, b, done, c], now=NOW)
    assert [x['title'] for x in got] == ['b', 'a']
    assert [x['title'] for x in D.hero_fights([a, b, c], now=NOW, sport='Boxing')] == ['a', 'c']
    monkeypatch.setattr(site_pages, '_big_fights', lambda events, today: 1 / 0)
    assert D.hero_fights([a], now=NOW) == [], 'a failing rule leaves the page without a hero, never broken'


def test_hero_fights_on_the_fixture(client):
    with A.app.test_request_context('/'):
        up = A.upcoming_only(A.fetch_fights())
        evs = A._group_events_for_landing(up, 'UFC')[0] + A._group_events_for_landing(up, 'Boxing')[0]
        big = site_pages._big_fights(evs, date(2026, 10, 2))
        got = D.hero_fights(evs)
    assert len(got) <= 2 and all(x in big for x in got)
    assert got == sorted(got, key=lambda x: D.start_of(x))


def test_hero_view(meta):
    v = D.hero_view(ev(), 'c1', now=NOW)
    assert v['cls'] == 'rc lead hero card c1 boxing n2 l-ph r-ph'
    assert v['style'] == '--e1:2.643;--e2:3.473;--em-stack:3.71;--est:3.469;--nl:2'
    assert (v['day_text'], v['rel'], v['what_first'], v['what_rest']) == ('Sat 17 Oct', 'in 15 days', 'Boxing', ['Heavyweight title', 'London'])
    u = D.hero_view(ufc(), 'c2', now=NOW)
    assert 'sp' in u['cls'].split() and u['what_first'] == 'UFC 333' and u['what_rest'] == ['Abu Dhabi']
    assert u['notes'] == [('prelims', datetime(2026, 10, 24, 16, 0, tzinfo=UTC))]
    s = D.hero_view(ev(), 'solo', now=NOW)
    assert s['cls'].startswith('rc lead hero solo boxing n2') and s['what_first'] == 'Heavyweight title'
    assert s['what_rest'] == ['London', '5\u00a0fights']
    n0 = D.hero_view(ev(fighter1_image=None, fighter2_image=None), 'c1', now=NOW)
    assert 'n0' in n0['cls'].split() and 'sd' in n0['cls'].split(), 'no photos: the names stack and carry the card'
    live = D.hero_view(ev(date='2026-10-02', time='11:00'), 'c1', now=NOW)
    assert live['state'] == 'live' and 'is-live' in live['cls'] and live['notes'][0][0] == 'since'


# --------------------------------------------------------------------------- macros
UI = "{% import '_ui.html' as ui %}"


def test_time_contract(client):
    h = render(UI + "{{ ui.time_el(e, 'big') }}|{{ ui.time_el(t, 'long') }}|{{ ui.time_el(x, 'big') }}|{{ ui.date_el(e) }}",
               e=ev(), t=ev(time_estimated=True), x=ev(time='TBA'))
    a, b, c, d = h.split('|')
    assert a == ('<time class="fight-time big" datetime="2026-10-17T18:00Z" data-utc-time="18:00" data-date="2026-10-17" '
                 'data-estimated="false" data-format="big">18:00 UTC</time>')
    assert 'data-estimated="true"' in b and '>~18:00 UTC</time>' in b
    assert c == '<time class="fight-time big no-time tba" datetime="2026-10-17" data-date="2026-10-17" data-format="big">Time TBA</time>'
    assert d.startswith('<time class="fdate" datetime="2026-10-17T18:00Z"') and d.endswith('data-format="date">Sat 17 Oct</time>')
    for dt, text in TIME.findall(h):
        assert re.fullmatch(r'\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}Z)?', dt) and (text.endswith(' UTC') or text.endswith('TBA'))


def test_watch_links(client):
    h = render(UI + "{{ ui.watch(e, 'home_list') }}|{{ ui.watch(o, 'home_list') }}|{{ ui.watch(n, 'home_list') }}",
               e=ev(), o=ev(streaming='ProBoxTV'), n=ev(streaming=''))
    a, b, c = h.split('|')
    assert a.startswith('<a class="watch" href="/go/dazn?event=daniel-dubois-vs-fabio-wardley-2026-10-17&amp;sport=boxing&amp;p=home_list"')
    assert 'rel="sponsored nofollow noopener"' in a and '<b>DAZN</b>' in a
    assert b.startswith('<span class="watch nolink">') and '<b>ProBoxTV</b>' in b and '<a' not in b
    assert c == '', 'nothing shown when no broadcaster is announced (owner, 2026-10-14)'


def test_faces_and_result_markup(client, meta):
    h = render(UI + "{{ ui.face('A', none) }}|{{ ui.face('TBA', '/x.jpg') }}|{% for s in ds.result_sides(e) %}{{ ui.res_face(s) }}|{% endfor %}",
               e=ev(result={'outcome': 'win', 'winner': 'Daniel Dubois', 'method': 'UD', 'round': '12'}))
    parts = h.split('|')
    assert parts[0] == '<span class="face none" aria-hidden="true"></span>'
    assert parts[1] == '<span class="face tba" aria-hidden="true"></span>'
    assert parts[2].startswith('<span class="won-ring"><img class="av won"')
    assert parts[3].startswith('<span class="face rf lostf" aria-hidden="true"><img class="av b lost"')
    h2 = render(UI + "{% for s in ds.result_sides(e) %}{{ ui.res_face(s) }}|{% endfor %}",
                e=ev(result={'outcome': 'win', 'winner': 'Fabio Wardley', 'method': 'UD', 'round': '12'}))
    assert h2.startswith('<span class="won-ring b"><img class="av b won"')
    assert '<img class="av lost"' in h2


def test_poster_cards(client, meta):
    meta['/persisted-fighters/daniel-dubois.jpg'] = DUBOIS
    for n in (0, 1, 2):
        h = render(UI + "{{ ui.big_band(bigs, 'UFC & boxing schedule') }}", bigs=[ev(), ufc()][:n])
        assert h.count('<h1') == 1 and '>UFC &amp; boxing schedule</h1>' in h
        assert not re.search(r'<a [^>]*>(?:(?!</a>).)*<a ', h, re.S), 'no link inside a link'
        assert h.count('<article class="rc lead hero') == n
    assert 'big-section none' in render(UI + "{{ ui.big_band([], 'x') }}")
    h = render(UI + "{{ ui.big_band(bigs, 'x') }}", bigs=[ev(), ufc()])
    assert 'class="rc lead hero card c1 boxing n2 l-ph r-ph" id="lead"' in h and 'id="lead2"' in h
    assert 'href="/go/dazn?event=daniel-dubois-vs-fabio-wardley-2026-10-17&amp;sport=boxing&amp;p=home_lead"' in h
    assert '<a class="btn sec rc-link lead-link fc" href="/boxing-event/daniel-dubois-vs-fabio-wardley-2026-10-17">' in h
    assert 'style="--ar:1;--ex:0.4696;' in h and 'fetchpriority="high"' in h
    assert '<span class="n1" style="--lsb:0.05;--rsb:0.031">Dubois</span><span class="vs">vs</span>' in h
    assert '<span class="nt prelims">Prelims <time class="fight-time short" datetime="2026-10-24T16:00Z"' in h
    solo = render(UI + "{{ ui.big_band(bigs, 'x') }}", bigs=[ev(streaming='')])
    assert 'hero solo' in solo and 'Broadcast not announced' not in solo and '<a class="btn pri rc-link lead-link fc"' in solo


def test_schedule_macro(client, meta):
    evs = _sched_events() + [ufc(date='2026-10-04', path='/event/ufc-333-2026-10-04')]
    sch = D.schedule(evs, today=date(2026, 10, 2), now=NOW, lead_keys={'a-2026-10-02': 'lead'})
    h = render(UI + "{{ ui.schedule(sch) }}", sch=sch)
    assert h.count('<article class="ev') == 6 and h.count('class="ev ptr') == 1
    assert '<a href="/event/ufc-333-2026-10-04" class="ev-main">' in h
    assert '<a class="ptr-go" href="#lead">Featured above' in h
    assert '<details class="ucd" id="ucd-sched-' in h and 'data-closed-label="13\u00a0fights"' in h
    assert '<h3 class="grp-h"><span class="gn">This week</span></h3>' in h
    assert 'Times in <b class="tz-display">UTC</b>' in h
    assert not re.search(r'<a [^>]*>(?:(?!</a>).)*<a ', h, re.S)
    for dt, text in TIME.findall(h):
        assert text.endswith(' UTC') or text.endswith('TBA')
    assert '<span class="nt night">Thu–Fri night</span>' in h, 'C: Friday 9 October, 02:00 UTC'


def test_results_macro(client, meta):
    won = ev(date='2026-09-28', result={'outcome': 'win', 'winner': 'Fabio Wardley', 'method': 'KO (punches)', 'round': '3', 'time': '1:00'},
             undercard=[{'fighter1': 'A B', 'fighter2': 'C D', 'result': {'outcome': 'win', 'winner': 'C D', 'method': 'UD', 'round': '8'}}])
    pend = ev(title='p', date='2026-10-01', path='/boxing-event/p', result=None, result_pending=True)
    old = ev(title='o', date='2026-09-10', path='/boxing-event/o', result=None)
    h = render(UI + "{{ ui.results_block(items) }}", items=[won, pend, old])
    assert '<article class="bx boxing w12 has-uc"' in h and '<b class="code">KO</b><span class="dt">R3 1:00</span>' in h
    assert '<span class="bw">C D</span> <i>def.</i> <span class="bls">A B</span>' in h
    assert '<h3 class="pend-h">Result pending</h3>' in h and h.count('<li class="pl-row') == 2
    assert '1 more card with no result on record' in h
    home = render(UI + "{{ ui.results_block(items, limit=4, undercards=false, fold=false) }}", items=[won, pend, old])
    assert 'has-uc' not in home and 'no result on record' not in home


def test_base_template_frame(client):
    page = render("{% extends '_base.html' %}{% set nav_active = 'UFC' %}{% block head %}<title>T</title>{% endblock %}"
                  "{% block main %}<h1>Hello</h1>{% endblock %}")
    assert page.count('<h1') == 1 and '<title>T</title>' in page
    assert '<a class="nav-pill" href="/ufc" aria-current="page">UFC</a>' in page
    assert 'id="timezone-display">UTC</b>' in page and 'href="/#search"' in page
    assert '<link rel="stylesheet" href="/static/css/site.css">' in page and '/static/js/site.js' in page
    assert 'window.FS_GA_ID' in page and 'id="fs-consent"' in page and "localStorage.setItem('fs-consent'" in page
    assert 'Fighter photos: UFC, Wikimedia Commons and others.' in page and 'Credits on each fight page.' in page
    assert '<g id="wm-g">' in page and page.count('<use href="#wm-g"/>') == 2
    assert 'styles.css' not in page, 'the redesign never loads Tailwind'
    search = render("{% extends '_base.html' %}{% set search_here = true %}{% block main %}{% endblock %}")
    for hook in ('id="searchToggle"', 'id="searchBar"', 'id="searchInput"', 'id="searchResults"'):
        assert hook in search


def test_design_names_do_not_shadow_other_modules():
    """app.<name> forwards to the owning module; a name owned twice would silently switch modules."""
    seen = {}
    for mod, names in A._OWNED.items():
        for n in names:
            assert n not in seen, f'{n} is owned by both {seen[n]} and {mod}'
            seen[n] = mod


def test_site_css_and_fonts_are_complete():
    import os
    root = os.path.dirname(A.__file__)
    css = open(os.path.join(root, 'static', 'css', 'site.css')).read()
    for f in re.findall(r'url\(\.\./fonts/([^)]+)\)', css):
        assert os.path.exists(os.path.join(root, 'static', 'fonts', f)), f
    # the owner's final change stays last; photos stay black and white; the winner ring stays green
    assert css.rstrip().endswith('@media (max-width: 1023.98px) { .duo-top { padding: 0; } }')
    assert 'filter: grayscale(1) brightness(var(--b, .95)) contrast(var(--c, 1.05))' in css
    assert '--win: #22C55E;' in css and '0 0 0 4px var(--win)' in css
    # a file too short for its half always covers the half's width (no framed box on the wide fight poster, QA
    # 2026-10-14); checked in a browser by checks/browser_checks.py
    assert '.ph.sh { --F: 36px; --Wi: max(min(var(--sw) * 1.25px, max(var(--Wc), var(--Wf))), var(--HW) / (var(--x1) - var(--x0))); }' in css
    js = open(os.path.join(root, 'static', 'js', 'site.js')).read()
    # the countdown says 'starting now' only until 15 min after the start, as design.countdown()
    assert "if (mins <= 0) return mins > -15 ? 'starting now' : '';" in js and D.STARTING_NOW_MIN == 15
    assert "tap('seen')" in js and 'need = 5000' in js and 'visibilitychange' in js and "'/api/t'" in js


def test_every_odd_case_renders(client, meta):
    """The brief's robustness list: TBA opponent, no venue, no broadcaster, time TBA, estimated time, long names,
    no photos, an unknown broadcaster: every macro renders, no 'None' reaches the page, no nested links."""
    odd = [ev(fighter2='TBA', fighter2_image=None, title='Maureen Shea vs TBA', path='/boxing-event/shea'),
           ev(venue='', location='', streaming=None, path='/boxing-event/novenue'),
           ev(time='TBA', path='/boxing-event/tba'),
           ev(time_estimated=True, path='/boxing-event/est', date='2026-10-16', time='23:00'),
           ev(fighter1='Christopher Guerrero-Martínez Jr.', fighter2='Muhammadqodir Abdulloev', fighter1_image=None,
              fighter2_image=None, path='/boxing-event/long', weight_class='Title Super Bantamweight',
              location='Coliseo Roberto Clemente, San Juan, Puerto Rico'),
           ev(streaming='ProBoxTV', path='/boxing-event/probox', result={'outcome': 'nc', 'method': 'No contest'})]
    src = (UI + "{% for e in odd %}{{ ui.hero(e, 'c1', hid='h' ~ loop.index) }}{{ ui.hero(e, 'solo', hid='s' ~ loop.index) }}"
           "{{ ui.box(e, 6, uid='b' ~ loop.index) }}{{ ui.pend_row(e) }}{{ ui.ptr_row(e, 'h1') }}{% endfor %}{{ ui.schedule(sch) }}")
    h = render(src, odd=odd, sch=D.schedule(odd, today=date(2026, 10, 2), now=NOW))
    assert 'None' not in h and 'nan' not in h
    assert not re.search(r'<a [^>]*>(?:(?!</a>).)*<a ', h, re.S)
    assert '<span class="n2 tba">TBA</span>' in h and '<b class="sn tba">TBA</b>' in h
    assert '<span class="bc">On <b>ProBoxTV</b></span>' in h and 'Start time not announced' in h
    assert '<span class="ln">Guerrero-</span><span class="ln">Martínez</span>' in h
    assert '<b class="code">NC</b>' in h


def test_worth_indexing_rule_b():
    """Owner 2026-10-17: never a TBA fighter; otherwise a tale of the tape, a preview, or 4+ other bouts."""
    m = {'fighter1': 'A', 'fighter2': 'B'}
    assert not D.worth_indexing({'fighter1': 'A', 'fighter2': 'TBA'}, 12, True, True)
    assert not D.worth_indexing({'fighter1': 'TBD', 'fighter2': 'B'}, 12, True, True)
    assert D.worth_indexing(m, 0, True, False) and D.worth_indexing(m, 0, False, True)
    assert D.worth_indexing(m, 4, False, False) and not D.worth_indexing(m, 3, False, False)
    assert not D.worth_indexing(m, 0, False, False)

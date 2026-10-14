"""The fight pages (/event/<slug>, /boxing-event/<slug>) in the approved redesign (2026-10-14):
site_pages.fight_view() and templates/_fight.html. The SEO head and the JSON-LD are the old templates' own
(tests/test_seo_titles.py, test_pages.py); these pin what the page shows. Clock: the fixtures' day, 2026-10-02."""
import json
import re

import time_machine

import app as A
import design as D
import photos
import site_pages as SP

UFC_URL = '/event/ufc-332-silva-vs.-wang-2026-10-04'
TIME = re.compile(r'<time class="fight-time[^"]*" datetime="([^"]*)"[^>]*>([^<]*)</time>')


def _fight(**kw):
    f = {'sport': 'Boxing', 'fighter1': 'Daniel Dubois', 'fighter2': 'Fabio Wardley', 'date': '2026-10-17',
         'time': '18:00', 'venue': 'London', 'location': 'London', 'streaming': 'DAZN', 'weight_class': 'Title Heavyweight',
         'is_main_event': True, 'time_estimated': False, 'fighter1_image': None, 'fighter2_image': None,
         'is_past': False, 'result': None, 'result_pending': False, 'fighter1_tape': None, 'fighter2_tape': None}
    f.update(kw)
    return f


def _view(main, others=(), sport='Boxing', event_name='', label=''):
    event = {'event_name': event_name, 'canonical_url': 'https://fightschedule.live/x', 'preview': None}
    with A.app.test_request_context('/'):
        return SP.fight_view(sport, main, [(label, [main] + list(others))], event, 'x-slug')


def _render(fv):
    with A.app.test_request_context('/'):
        return A.app.jinja_env.from_string("{% from '_fight.html' import fight_page %}{{ fight_page(fv) }}").render(fv=fv)


def test_fight_page_is_on_the_redesign_frame(client):
    h = client.get(UFC_URL).get_data(as_text=True)
    assert '<link rel="stylesheet" href="/static/css/site.css">' in h and '/static/css/site-fight.css' in h
    assert 'styles.css' not in h and 'list.js' not in h and 'fonts.googleapis.com' not in h
    assert len(re.findall(r'<h1[\s>]', h)) == 1
    assert '<a class="nav-pill" href="/ufc" aria-current="true">UFC</a>' in h, 'the section the page belongs to'


def test_times_are_utc_for_crawlers_and_the_prelims_keep_their_day(client):
    h = client.get(UFC_URL).get_data(as_text=True)
    ts = TIME.findall(h)
    assert ts
    for d, t in ts:
        assert re.fullmatch(r'\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}Z)?', d), d
        assert t.endswith(' UTC') or t.endswith('TBA'), t
    # the prelims start the evening before the main card (UTC): their own day, not the main card's
    sub = re.search(r'<span class="gn">Prelims</span><span class="tm"><time [^>]*datetime="([^"]+)"', h)
    assert sub and sub.group(1) == '2026-10-03T20:00Z'
    note = h.split('<p class="ld-note" data-night')[1].split('</p>')[0]
    assert '<span class="nt lead">Main card</span>' in note and 'datetime="2026-10-03T20:00Z"' in note


def test_watch_calendar_and_crumbs(client):
    h = client.get(UFC_URL).get_data(as_text=True)
    slug = UFC_URL.rsplit('/', 1)[-1]
    assert f'href="/go/paramount-plus?event={slug}&amp;sport=ufc&amp;p=event"' in h
    assert f'href="/go/ufc-fight-pass?event={slug}&amp;sport=ufc&amp;p=event"' in h
    assert 'We may earn a commission if you subscribe. <a href="/privacy#affiliate">Details</a>' in h
    # the old template's Google Calendar link, character for character
    start = '20261004T000000Z'
    assert ('https://calendar.google.com/calendar/render?action=TEMPLATE&amp;text=UFC%20332%3A%20Silva%20vs.%20Wang'
            f'&amp;dates={start}/{start}&amp;details=Full%20card%20and%20times%3A%20https%3A//fightschedule.live{UFC_URL}'
            '&amp;location=Delta%20Center') in h
    crumbs = h.split('<nav class="crumbs" aria-label="Breadcrumb">')[1].split('</nav>')[0]
    assert '<a href="/">Schedule</a>' in crumbs and '<a href="/ufc">UFC schedule</a>' in crumbs
    assert '<span aria-current="page">UFC 332</span>' in crumbs
    ld = [json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)]
    bc = next(x for x in ld if x['@type'] == 'BreadcrumbList')
    assert [i['name'] for i in bc['itemListElement']] == ['Home', 'UFC Schedule', 'UFC 332: Silva vs. Wang']


def test_main_event_is_one_pointer_on_its_card(client):
    h = client.get(UFC_URL).get_data(as_text=True)
    assert h.count('class="bout ptr') == 1 and 'Main event · above' in h
    assert '<a class="ptr-go" href="#fight-h">' in h and 'id="fight-h"' in h


def test_pair_follows_the_event_title_with_each_tape_on_its_side():
    t_malott = {'record': '14-2-1', 'nationality': 'Canada'}
    t_buckley = {'record': '21-8', 'nationality': 'United States'}
    main = _fight(sport='UFC', fighter1='Mike Malott', fighter2='Joaquin Buckley', fighter1_tape=t_malott,
                  fighter2_tape=t_buckley, event_name='UFC Fight Night: Buckley vs. Malott', streaming=None, weight_class=None)
    other = _fight(sport='UFC', fighter1='Nate Landwehr', fighter2='Mandel Nallo', streaming=None, weight_class=None)
    fv = _view(main, [other], sport='UFC', event_name='UFC Fight Night: Buckley vs. Malott', label='Main card')
    assert (fv['e']['fighter1'], fv['e']['fighter2']) == ('Joaquin Buckley', 'Mike Malott')
    assert fv['tape']['names'] == ('Joaquin Buckley', 'Mike Malott')
    assert fv['tape']['rows'][0] == ('21-8', 'Record', '14-2-1')
    h = _render(fv)
    h1 = re.sub(r'\s+', ' ', re.sub('<[^>]+>', ' ', re.search(r'<h1[^>]*>(.*?)</h1>', h, re.S).group(1))).strip()
    assert h1 == 'UFC Fight Night Buckley vs Malott'
    assert '<span aria-hidden="true">Buckley <i>vs</i> Malott</span>' in h, 'the pointer row in the same order'


def test_past_fight_shows_the_result_and_dims_the_loser():
    r = {'outcome': 'win', 'winner': 'Brendan Allen', 'loser': 'Christian Leroy Duncan', 'method': 'Submission (rear-naked choke)',
         'round': '5', 'time': '2:46'}
    main = _fight(sport='UFC', fighter1='Brendan Allen', fighter2='Christian Leroy Duncan', date='2026-09-30', time='00:00',
                  is_past=True, result=r, fighter1_image='/static/a.png', fighter2_image='/static/b.png', streaming=None)
    fv = _view(main, sport='UFC', event_name='UFC Fight Night: Allen vs. Duncan', label='Main card')
    assert fv['result'] == {'code': 'SUB', 'who': 'Allen', 'words': 'Rear-naked choke', 'detail': 'Round 5, 2:46',
                            'sr': 'Brendan Allen won, Rear-naked choke, Round 5, 2:46.'}
    assert 'lost' in fv['p2']['cls'].split() and 'lost' not in fv['p1']['cls'].split()
    h = _render(fv)
    assert '<b class="code">SUB</b>' in h and '<b>Allen</b> won' in h
    assert '<span class="n1 won"' in h and '<span class="n2 lost"' in h
    assert 'Add to calendar' not in h and 'Where to watch' not in h
    assert fv['crumb'] == 'Allen vs Duncan' and fv['section'] == ('Results', '/results', 'Results')


def test_missing_result_says_pending_inside_the_grace_window_only():
    recent = _view(_fight(date='2026-10-01', is_past=True))
    assert recent['pending_label'] == 'Result pending'
    assert '<b class="code pend">Result pending</b>' in _render(recent)
    old = _view(_fight(date='2026-09-12', is_past=True), [_fight(fighter1='A B', fighter2='C D', date='2026-09-12', is_past=True)])
    h = _render(old)
    assert '<b class="code pend">No result on record</b>' in h and 'No results on record.' in h


def test_decided_bouts_are_box_scores_in_card_order():
    r = {'outcome': 'win', 'winner': 'Loopy Godínez', 'loser': 'Ketlen Souza', 'method': 'Decision (unanimous)', 'round': '3'}
    main = _fight(date='2026-09-30', is_past=True)
    bout = _fight(fighter1='Ketlen Souza', fighter2='Loopy Godínez', date='2026-09-30', is_past=True, result=r,
                  fighter2_image='/static/l.png', weight_class='Flyweight', is_main_event=False)
    h = _render(_view(main, [bout]))
    box = h.split('<li class="bout bx')[1].split('</li>')[0]
    assert box.index('Souza') < box.index('Godínez'), 'fighter1 first, as the approved fight page'
    # changed 2026-10-14 (owner): undercard bouts carry no faces; the winner is marked by the W tag
    assert '<span class="wtag" aria-hidden="true">W</span>' in box
    assert 'class="face' not in box and 'won-ring' not in box and '<img' not in box, 'no faces on undercard bouts'
    assert '<b class="code">UD</b>' in box and '<a ' not in box, 'a bout is not a link'
    assert '<h2 id="fight-card">Results</h2>' in h


def test_one_fight_card_and_broadcasters():
    solo = _render(_view(_fight(streaming=None)))
    assert 'id="fight-card"' not in solo and 'Only the main event has been announced so far.' in solo
    assert 'Broadcast not announced' not in solo and 'id="fight-watch"' not in solo, 'no Where to watch when none is announced'
    plain = _render(_view(_fight(streaming='LIVE on ProBoxTV')))
    assert '<p class="bc">On <b>ProBoxTV</b></p>' in plain and '/go/' not in plain
    dazn = _render(_view(_fight()))
    assert 'href="/go/dazn?event=x-slug&amp;sport=boxing&amp;p=event"' in dazn and 'Watch on DAZN' in dazn


def test_live_card_says_so():
    # the fixtures' clock is 2026-10-02 12:00 UTC: a boxing card that started at 11:00 is under way
    h = _render(_view(_fight(date='2026-10-02', time='11:00')))
    assert 'Under way' in h and 'Watch live on DAZN' in h and '<span class="live">' in h
    assert 'since <time class="fight-time short" datetime="2026-10-02T11:00Z"' in h


def test_time_states_at_every_boundary():
    """Before, at, during and just after the live window, after midnight UTC and with a result: the page never says
    "starting now" next to "Yesterday" or keeps the upcoming layout once the card is over (QA 2026-10-14)."""
    card = dict(date='2026-10-17', time='18:00')           # boxing: live for design.LIVE_HOURS['Boxing'] = 5 h
    r = {'outcome': 'win', 'winner': 'Daniel Dubois', 'loser': 'Fabio Wardley', 'method': 'KO', 'round': '4', 'time': '1:10'}
    cases = [
        ('2026-10-16T19:00:00Z', {}, 'up', 'in 23 h 0 min'),
        ('2026-10-17T17:59:30Z', {}, 'up', 'starting now'),
        ('2026-10-17T18:10:00Z', {}, 'live', None),
        ('2026-10-17T22:59:00Z', {}, 'live', None),
        ('2026-10-17T23:00:00Z', {}, 'pending', None),       # the live window is over; the day is not (UTC)
        ('2026-10-17T23:59:00Z', {}, 'pending', None),
        ('2026-10-18T09:00:00Z', {'is_past': True}, 'pending', None),
        ('2026-10-17T23:30:00Z', {'result': r}, 'result', None),
    ]
    for at, kw, want, cd in cases:
        with time_machine.travel(at, tick=False):
            fv = _view(_fight(**card, **kw))
            h = _render(fv)
        where = f'{at} {kw}'
        assert 'starting now' not in h or want == 'up', where
        if want == 'up':
            assert not fv['past'] and fv['countdown'] == cd and 'Watch on DAZN' in h, where
            assert f'data-countdown="2026-10-17T18:00Z">{cd}</span>' in h, where
        elif want == 'live':
            assert fv['state'] == 'live' and 'Under way' in h and 'Watch live on DAZN' in h, where
            assert 'data-countdown' not in h, where
        else:
            assert fv['past'] and fv['state'] == 'done' and 'data-countdown' not in h, where
            assert 'Watch on' not in h and 'Add to calendar' not in h and 'class="wrap fp boxing past' in h, where
            if want == 'pending':
                assert '<b class="code pend">Result pending</b>' in h, where
            else:
                assert '<b class="code">KO</b>' in h and '<b>Dubois</b> won' in h, where
    # a UFC card: 3.5 h from the main card's start; its prelims the evening before (UTC)
    with time_machine.travel('2026-10-18T09:00:00Z', tick=False):
        fv = _view(_fight(sport='UFC', fighter1='Brendan Allen', fighter2='Christian Leroy Duncan', date='2026-10-18',
                          time='02:00', streaming=None), sport='UFC', event_name='UFC Fight Night', label='Main card')
        h = _render(fv)
    assert fv['past'] and 'starting now' not in h and 'Result pending' in h and 'Where to watch' not in h


def test_h1_keeps_its_words_and_the_column_shows_the_design_label():
    fv = _view(_fight(weight_class='Title Junior Welterweight'))
    assert fv['h1_kick'] == 'Junior Welterweight title' and fv['kick'] == 'Jr welterweight title'
    assert SP._h1_label('Boxing', {'weight_class': 'Title'}) == 'Title fight'
    assert SP._h1_label('Boxing', {'weight_class': ''}) == 'Boxing'


def test_stray_parenthesis_in_a_birthplace_is_dropped():
    fv = _view(_fight(fighter1_tape={'nationality': 'Russia)'}, fighter2_tape={'nationality': 'Wales (UK)'}))
    assert ('Russia', 'From', 'Wales (UK)') in fv['tape']['rows']


def test_face_crop_always_covers_its_disc(monkeypatch):
    # a close-up whose chin sits near the file's bottom edge: shown off-centre, never with a grey band in the disc
    monkeypatch.setattr(photos, 'photo_meta', lambda p: {'w': 400, 'h': 400, 'face': True, 'ex': .48, 'ey': .61,
                                                          'em': .25, 'box_h': .65, 'crown': .14})
    st = dict(kv.split(':') for kv in D.face_crop('/x.png')['style'].split(';'))
    z, px, py = float(st['--z']), float(st['--px']), float(st['--py'])
    assert .5 / z - 1e-3 <= px <= 1 - .5 / z + 1e-3 and .5 / z - 1e-3 <= py <= 1 - .5 / z + 1e-3


def test_close_up_portrait_is_sized_by_its_face(monkeypatch):
    meta = {'/p.jpg': {'w': 500, 'h': 667, 'face': True, 'ex': .58, 'ey': .41, 'em': .171, 'box_h': .53, 'b': .88, 'c': 1.4},
            '/s.jpg': {'w': 400, 'h': 400, 'face': True, 'ex': .47, 'ey': .27, 'em': .107, 'box_h': .29}}
    monkeypatch.setattr(photos, 'photo_meta', lambda p: meta.get(p.split('?')[0]))
    fv = _view(_fight(fighter1_image='/p.jpg', fighter2_image='/s.jpg'))
    assert 'fs' in fv['p1']['cls'].split() and '--c:1.15' in fv['p1']['style'] and fv['p1']['copies'] == []
    assert 'fs' not in fv['p2']['cls'].split()


def test_unknown_fight_urls_get_the_site_404_page(client):
    for url in ('/boxing-event/nobody-vs-no-one-2026-10-10', '/boxing-event/x', '/event/ufc-329-nobody-vs.-none-2026-07-11'):
        r = client.get(url)
        body = r.get_data(as_text=True)
        assert r.status_code == 404 and '<meta name="robots" content="noindex">' in body and 'Not on the card' in body, url


def test_draw_in_the_main_event():
    r = {'outcome': 'draw', 'winner': None, 'method': 'Decision (majority)', 'round': '5', 'time': None}
    fv = _view(_fight(date='2026-09-30', is_past=True, result=r))
    assert fv['ws'] == 0 and fv['result']['code'] == 'DRAW' and fv['result']['who'] == ''
    h = _render(fv)
    assert 'Majority draw' in h and '5 rounds' in h and ' won' not in h and 'class="n1 ' not in h

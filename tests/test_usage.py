"""Cookie-free usage counts: page views, tap beacons, bot/script filtering, aggregation."""
import json
import os

import app as A
import usage

BROWSER = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile Safari/604.1',
           'Accept-Language': 'en-US,en;q=0.9'}


def _records():
    if not os.path.exists(usage.USAGE_FILE):
        return []
    return [json.loads(l) for l in open(usage.USAGE_FILE, encoding='utf-8')]


def test_page_views_are_counted_without_cookies(client):
    client.get('/', headers=BROWSER)
    client.get('/results', headers=BROWSER)
    client.get('/ufc', headers=BROWSER)
    r = client.get('/', headers=BROWSER)
    assert 'Set-Cookie' not in r.headers
    views = [x for x in _records() if x['kind'] == 'view']
    assert [v['page'] for v in views] == ['homepage', 'results', 'ufc page', 'homepage']
    assert all(set(v) == {'ts', 'kind', 'page', 'name', 'detail', 'bot', 'lang', 'ref'} for v in views), 'nothing identifying is stored'


def test_non_page_requests_are_not_views(client):
    for p in ('/health', '/robots.txt', '/sitemap.xml', '/llms.txt', '/static/js/list.js', '/api/debug/state?token=t&part=health'):
        client.get(p, headers=BROWSER)
    assert not [x for x in _records() if x['kind'] == 'view']


def test_bot_and_languageless_views_are_marked(client):
    client.get('/', headers={'User-Agent': 'Googlebot/2.1', 'Accept-Language': 'en'})
    client.get('/', headers={'User-Agent': BROWSER['User-Agent']})
    views = [x for x in _records() if x['kind'] == 'view']
    assert views[0]['bot'] is True and views[1]['bot'] is False and views[1]['lang'] is False


def test_tap_beacon_records_valid_taps_only(client):
    h = dict(BROWSER, Referer='http://localhost/ufc', Origin='http://localhost')
    for body in ({'name': 'card', 'detail': 'UFC', 'page': '/ufc'},
                 {'name': 'filter', 'detail': 'Boxing', 'page': '/'},
                 {'name': 'undercard_open', 'page': '/'},
                 {'name': 'watch', 'detail': 'dazn', 'page': '/boxing-event/x-vs-y-2026-10-03'},
                 {'name': 'evil', 'page': '/'},                         # unknown name
                 {'name': 'card', 'detail': '<script>', 'page': '/'},   # bad detail
                 {'name': 'card', 'detail': 'x' * 200, 'page': '/'}):   # too long
        r = client.post('/api/t', json=body, headers=h)
        assert r.status_code == 204
    taps = [x for x in _records() if x['kind'] == 'tap']
    assert [(t['page'], t['name'], t['detail']) for t in taps] == [
        ('ufc page', 'card', 'UFC'), ('homepage', 'filter', 'Boxing'), ('homepage', 'undercard_open', None),
        ('boxing fight page', 'watch', 'dazn')]
    assert all(t['ref'] for t in taps)


def test_tap_from_outside_the_site_is_marked(client):
    client.post('/api/t', json={'name': 'card', 'page': '/'}, headers=BROWSER)                       # no referer/origin
    client.post('/api/t', json={'name': 'card', 'page': '/'}, headers=dict(BROWSER, Origin='https://evil.example'))
    client.post('/api/t', json={'name': 'card', 'page': '/'}, headers=dict(BROWSER, Referer='http://localhost/'))
    taps = [x for x in _records() if x['kind'] == 'tap']
    assert [t['ref'] for t in taps] == [False, False, True]


def test_oversized_body_is_dropped(client):
    r = client.post('/api/t', data='x' * 2000, headers=dict(BROWSER, Referer='http://localhost/'), content_type='application/json')
    assert r.status_code == 204 and not _records()


def test_stats_count_real_visitors_and_show_what_was_dropped(client):
    h = dict(BROWSER, Referer='http://localhost/')
    for _ in range(4):
        client.get('/', headers=BROWSER)
    client.get('/', headers={'User-Agent': 'curl/8.0'})
    client.post('/api/t', json={'name': 'card', 'detail': 'UFC', 'page': '/'}, headers=h)
    client.post('/api/t', json={'name': 'watch', 'detail': 'dazn', 'page': '/'}, headers=h)
    client.post('/api/t', json={'name': 'watch', 'detail': 'dazn', 'page': '/'}, headers=BROWSER)   # no referer: script
    s = usage.stats(days=1)
    assert s['views_by_page'] == {'homepage': 4}
    assert s['dropped']['bot'] == 1 and s['dropped']['not_from_site'] == 1
    assert s['taps_by_name'] == {'card': 1, 'watch': 1}
    assert s['per_page']['homepage']['tap_rate_pct'] == {'card': 25.0, 'watch': 25.0}
    d = client.get('/api/debug/state?token=t&part=usage').get_json()
    assert d['views_by_page'] == {'homepage': 4}


def test_page_type_mapping():
    assert usage.page_type('https://fightschedule.live/') == 'homepage'
    assert usage.page_type('/event/ufc-332-x-2026-10-04?a=1') == 'ufc fight page'
    assert usage.page_type('/boxing-event/a-vs-b-2026-10-03') == 'boxing fight page'
    assert usage.page_type('/boxing') == 'boxing page'
    assert usage.page_type('/results#x') == 'results'
    assert usage.page_type('/go/dazn') == 'other'


def test_privacy_page_describes_usage_counts(client):
    assert 'id="usage"' in client.get('/privacy').get_data(as_text=True)


def test_seen_beacon_is_its_own_count(client):
    h = dict(BROWSER, Referer='http://localhost/')
    for _ in range(3):
        client.get('/', headers=BROWSER)                                     # server views
    client.post('/api/t', json={'name': 'seen', 'page': '/'}, headers=h)    # one person looked
    client.post('/api/t', json={'name': 'card', 'detail': 'UFC', 'page': '/'}, headers=h)
    client.get('/', headers={'User-Agent': 'curl/8.0'})                      # bot: raw only
    recs = _records()
    assert [r['kind'] for r in recs if r['kind'] != 'view'] == ['seen', 'tap']
    seen = next(r for r in recs if r['kind'] == 'seen')
    assert seen['name'] is None and seen['detail'] is None
    s = usage.stats(days=1)
    assert s['seen_total'] == 1 and s['seen_by_page'] == {'homepage': 1}
    assert s['views_by_page'] == {'homepage': 3}
    assert sum(s['raw_views_by_day'].values()) == 4
    assert s['taps_by_name'] == {'card': 1}, 'seen is not a tap'


def test_seen_needs_a_real_page_load_from_the_site(client):
    client.post('/api/t', json={'name': 'seen', 'page': '/'}, headers=BROWSER)        # no referer
    client.post('/api/t', json={'name': 'seen', 'page': '/'}, headers={'User-Agent': 'python-requests/2.31',
                                                                        'Referer': 'http://localhost/'})
    assert usage.stats(days=1)['seen_total'] == 0


def test_page_script_reports_seen_after_five_visible_seconds():
    js = open('static/js/list.js').read()
    assert "tap('seen')" in js and 'need = 5000' in js and 'visibilitychange' in js

"""Rendered pages: every bout shown once, crawler-visible UTC times, no link
inside a link, structured data present."""
import collections
import os
import re

import app as A

EV_LINK = re.compile(r'<a href="(/(?:event|boxing-event)/[^"]+)" class="ev-main"')
TIME = re.compile(r'<time class="fight-time[^"]*" datetime="([^"]*)"[^>]*>([^<]*)</time>')


def _events(fights):
    with A.app.test_request_context('/'):
        return A._group_events_for_landing(fights, 'UFC')[0] + A._group_events_for_landing(fights, 'Boxing')[0]


def test_every_upcoming_bout_shown_exactly_once(client, seeded_cache):
    up = A.upcoming_only(A.fetch_fights())
    shown = collections.Counter()
    for e in _events(up):
        shown[(e['fighter1'], e['fighter2'], e['date'])] += 1
        for b in e['undercard']:
            shown[(b['fighter1'], b['fighter2'], b['date'])] += 1
    want = collections.Counter((f['fighter1'], f['fighter2'], f['date']) for f in up)
    assert shown == want


def test_homepage_lists_each_event_once(client):
    h = client.get('/').get_data(as_text=True)
    hrefs = EV_LINK.findall(h)
    assert hrefs and len(hrefs) == len(set(hrefs))


def test_results_page_shows_every_past_bout_once(client):
    past = A.recent_results(A.fetch_fights())
    shown = collections.Counter()
    for e in _events(past):
        shown[(e['fighter1'], e['fighter2'], e['date'])] += 1
        for b in e['undercard']:
            shown[(b['fighter1'], b['fighter2'], b['date'])] += 1
    want = collections.Counter((f['fighter1'], f['fighter2'], f['date']) for f in past)
    assert shown == want
    h = client.get('/results').get_data(as_text=True)
    assert all(f'href="{e["path"]}"' in h for e in _events(past))


def test_pages_render_without_nested_links(client):
    paths = ['/', '/results', '/ufc', '/boxing', '/privacy', '/llms.txt', '/sitemap.xml', '/health']
    h = client.get('/').get_data(as_text=True)
    paths += EV_LINK.findall(h)[:4]
    for p in paths:
        r = client.get(p)
        assert r.status_code in (200, 503), p
        body = r.get_data(as_text=True)
        assert not re.search(r'<a [^>]*>(?:(?!</a>).)*<a ', body, re.S), f'nested link on {p}'
        assert '{{' not in body, f'unrendered template on {p}'


def test_crawlers_see_utc_times_and_valid_datetimes(client):
    for p in ('/', '/ufc', '/boxing', '/results'):
        ts = TIME.findall(client.get(p).get_data(as_text=True))
        assert ts, p
        for d, t in ts:
            assert re.fullmatch(r'\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}Z)?', d), (p, d)
            assert t.strip().endswith(' UTC') or t.strip().endswith('TBA'), (p, t)


def test_ufc_event_page_leads_with_main_event_and_full_card(client, seeded_cache):
    h = client.get('/').get_data(as_text=True)
    href = next(x for x in EV_LINK.findall(h) if 'ufc-332' in x)
    assert href.endswith('2026-10-04')
    r = client.get(href)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    hero = body.split('class="hero')[1][:3000]
    assert 'datetime="2026-10-04T00:00Z"' in hero
    assert body.count('class="bout') == 13
    assert body.count('/go/paramount-plus') >= 1 and 'espn-plus' not in body


def test_old_event_url_redirects_to_main_card_date(client):
    r = client.get('/event/ufc-332-silva-vs.-wang-2026-10-03')
    assert r.status_code == 301 and r.headers['Location'].endswith('2026-10-04')


def test_structured_data_is_valid_json(client):
    h = client.get('/').get_data(as_text=True)
    import json
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)
    assert blocks
    for b in blocks:
        json.loads(b)


def test_watch_clicks_are_logged_and_counted(client):
    h = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/129.0 Safari/537.36',
         'Accept-Language': 'en-US,en;q=0.9', 'Referer': 'https://fightschedule.live/'}
    r = client.get('/go/dazn?event=x&sport=boxing&p=home_list', headers=h)
    assert r.status_code == 302 and 'dazn.com' in r.headers['Location']
    client.get('/go/dazn?event=x&sport=boxing&p=event', headers={'User-Agent': 'Googlebot/2.1'})
    client.get('/go/dazn?event=x&sport=boxing&p=event', headers={'User-Agent': h['User-Agent'], 'Accept-Language': 'en-US'})  # no referer
    rc = A.click_stats(days=30)['real_clicks']
    assert rc['total'] == 1 and rc['by_placement'] == {'home_list': 1} and rc['by_page'] == {'homepage': 1}


def test_robots_disallows_private_paths(client):
    rb = client.get('/robots.txt').get_data(as_text=True)
    for p in ('/admin/', '/go/', '/api/', '/health'):
        assert f'Disallow: {p}' in rb


def test_sport_label_is_coloured_text_without_dot(client):
    h = client.get('/').get_data(as_text=True)
    assert 'class="dot"' not in h
    css = open(os.path.join(os.path.dirname(A.__file__), 'static', 'css', 'list.css')).read()
    assert '.ev.ufc .tag { color: var(--ufc); }' in css and '.ev.boxing .tag { color: var(--box); }' in css

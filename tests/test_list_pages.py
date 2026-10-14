"""The redesigned list pages (approved 2026-10-14): the homepage, /ufc, /boxing, /results, /privacy and the 404 page.
They keep their addresses, SEO heads and usage hooks; the parts every page shares (poster cards, the schedule table,
results) are tested in test_design.py. The clock is frozen to FIXTURE_NOW (2026-10-02 12:00 UTC, conftest.py)."""
import re

import pytest

import app as A
import design
import fight_store
import pipeline
import site_pages

PTR = re.compile(r'<a class="ptr-go" href="#(lead2?)">')


def _get(client, path):
    r = client.get(path)
    return r.status_code, r.get_data(as_text=True)


def test_home_frame_hero_and_one_table(client):
    s, h = _get(client, '/')
    assert s == 200 and len(re.findall(r'<h1[\s>]', h)) == 1
    assert '<h1 class="duo-h1">UFC &amp; boxing schedule</h1>' in h
    assert h.count('class="tt sched"') == 1, 'one schedule table'
    assert 'id="search-data"' in h and 'id="searchBar"' in h and '/static/js/list.js' not in h
    assert 'aria-current="page">Schedule</a>' in h
    # each poster fight's table slot is a pointer line to its card
    heroes = re.findall(r'<article class="rc lead hero[^"]*" id="(lead2?)"', h)
    assert heroes and sorted(PTR.findall(h)) == sorted(heroes)
    assert 'p=home_big' in h and 'p=home_list' in h, 'Watch placements keep their usage names'
    assert 'class="chipf' not in h, 'the nav is the only sport control'


def test_home_latest_results_cover_the_last_ten_days(client, monkeypatch):
    s, h = _get(client, '/')
    sec = h.split('id="results"', 1)[1].split('</section>', 1)[0] if 'id="results"' in h else ''
    dates = re.findall(r'<time class="fdate bx-d" datetime="(\d{4}-\d{2}-\d{2})', sec)
    assert all(d >= '2026-09-22' for d in dates)
    assert len(re.findall(r'<article class="bx ', sec)) <= 4
    # nothing decided and nothing pending: no empty section
    monkeypatch.setattr(fight_store, 'recent_results', lambda fights: [])
    assert 'Latest results' not in _get(client, '/')[1]


def test_home_without_any_fights_still_renders(client, monkeypatch):
    monkeypatch.setattr(pipeline, 'fetch_fights', lambda: [])
    s, h = _get(client, '/')
    assert s == 200 and len(re.findall(r'<h1[\s>]', h)) == 1
    assert 'No upcoming fights listed right now' in h and 'class="big-section none"' in h


@pytest.mark.parametrize('path, sport', [('/ufc', 'UFC'), ('/boxing', 'Boxing')])
def test_sport_pages(client, path, sport):
    s, h = _get(client, path)
    assert s == 200 and len(re.findall(r'<h1[\s>]', h)) == 1
    assert f'aria-current="page">{sport}</a>' in h
    assert 'id="results"' in h and 'data-tab=' not in h, '/ufc#results lands on the results section; no tabs'
    assert f'p={sport.lower()}_list' in h
    rows = re.findall(r'<article class="ev (ufc|boxing)', h)
    assert rows and set(rows) == {sport.lower()}
    if sport == 'Boxing':
        assert '<p class="ld-what"><b>Boxing</b>' not in h, 'the page names the sport; the cards do not repeat it'


def test_empty_sport_page_points_to_the_other_sport(client, monkeypatch):
    real = pipeline.fetch_fights
    monkeypatch.setattr(pipeline, 'fetch_fights', lambda: [f for f in real() if f['sport'] == 'UFC' or f['date'] < '2026-10-02'])
    s, h = _get(client, '/boxing')
    assert s == 200 and len(re.findall(r'<h1[\s>]', h)) == 1
    assert 'No fights listed right now' in h and 'href="/calendar/boxing.ics"' in h
    assert 'Meanwhile in the UFC' in h and h.count('class="rc lead hero') == 1
    assert 'id="results"' in h
    monkeypatch.setattr(pipeline, 'fetch_fights', lambda: [])
    s, h = _get(client, '/boxing')
    assert s == 200 and 'No fights listed right now' in h and 'class="rc lead hero' not in h
    assert 'No boxing results in the last 30 days yet.' in h


def test_results_page(client, monkeypatch):
    s, h = _get(client, '/results')
    assert s == 200 and '<h1 class="vh" id="results-t">Results</h1>' in h
    assert 'aria-current="page">Results</a>' in h
    # the fixture has no results on record: every past card folds into one line
    assert re.search(r'class="nr-t">\d+ cards with no result on record', h)
    real = pipeline.fetch_fights

    def with_a_result():
        fs = [dict(f) for f in real()]
        f = next(f for f in fs if f['sport'] == 'Boxing' and f.get('is_main_event') and f['date'] < '2026-10-02')
        f['result'] = {'outcome': 'win', 'winner': f['fighter2'], 'method': 'Decision (unanimous)', 'round': '12', 'time': None}
        f['fighter1_image'], f['fighter2_image'] = '/static/fighters/a.png', '/static/fighters/b.png'
        return fs
    monkeypatch.setattr(pipeline, 'fetch_fights', with_a_result)
    h = _get(client, '/results')[1]
    assert h.count('<article class="bx ') == 1
    assert '<span class="won-ring b"><img class="av b won"' in h and '<img class="av lost"' in h, 'production\'s result markup'
    assert re.search(r'class="nr-t">\d+ more cards with no result on record', h)
    monkeypatch.setattr(pipeline, 'fetch_fights', lambda: [])
    s, h = _get(client, '/results')
    assert s == 200 and 'No results in the last 30 days yet.' in h


def test_privacy_keeps_its_anchors(client):
    s, h = _get(client, '/privacy')
    assert s == 200
    for i in ('cookies', 'usage', 'affiliate'):
        assert f'id="{i}"' in h
    assert 'window.fsShowConsent' in h and 'id="fs-consent"' in h


def test_missing_page_gets_the_sites_404(client):
    s, h = _get(client, '/event/ufc-999-nobody-2026-01-01')
    assert s == 404
    assert 'Not on the card' in h and '<meta name="robots" content="noindex">' in h
    assert len(re.findall(r'<h1[\s>]', h)) == 1 and '/event/ufc-999-nobody-2026-01-01' in h
    s, h = _get(client, '/no-such-page/<script>')
    assert s == 404 and '<script>' not in h.split('nf-path">', 1)[1].split('</span>', 1)[0]
    # files, the API and admin keep the plain 404
    for p in ('/static/no-such-file.png', '/persisted-fighters/nobody.jpg', '/api/nothing'):
        s, h = _get(client, p)
        assert s == 404 and 'Not on the card' not in h, p


def test_404_page_never_fails(client, monkeypatch):
    def boom():
        raise RuntimeError('cache unreadable')
    monkeypatch.setattr(pipeline, 'fetch_fights', boom)
    s, h = _get(client, '/nope')
    assert s == 404 and 'Not on the card' in h and 'class="rc lead hero' not in h
    monkeypatch.setattr(design, 'schedule', lambda *a, **k: 1 / 0)
    assert client.get('/nope').status_code == 404


def test_list_pages_keep_their_seo_heads(client):
    s, h = _get(client, '/')
    assert '<link rel="canonical" href="https://fightschedule.live/">' in h and '"@type": "FAQPage"' in h
    s, h = _get(client, '/ufc')
    assert '<link rel="canonical" href="https://fightschedule.live/ufc">' in h and '"@type": "BreadcrumbList"' in h
    s, h = _get(client, '/results')
    assert '<link rel="canonical" href="https://fightschedule.live/results">' in h
    for p in ('/', '/ufc', '/boxing', '/results', '/privacy'):
        h = _get(client, p)[1]
        assert h.count('<title>') == 1 and h.count('name="description"') == 1, p
        assert '/static/css/styles.css' not in h and 'fonts.googleapis.com' not in h, p

"""Finished fights keep their pages after leaving the 30-day lists, and the
sitemap's dates are honest. The clock is frozen at 2026-10-02 (conftest), so
the results window starts 2026-09-02."""
import re

import app as A

OLD_UFC = [
    {'sport': 'UFC', 'event_name': 'UFC 330: Alpha vs. Beta', 'fighter1': 'Al Alpha', 'fighter2': 'Bo Beta',
     'date': '2026-08-16', 'time': '03:00', 'card_type': 'Main Card', 'venue': 'Some Arena', 'weight_class': 'Lightweight'},
    {'sport': 'UFC', 'event_name': 'UFC 330: Alpha vs. Beta', 'fighter1': 'Cy Gamma', 'fighter2': 'Di Delta',
     'date': '2026-08-16', 'time': '01:00', 'card_type': 'Prelims', 'venue': 'Some Arena', 'weight_class': 'Flyweight'},
]
OLD_BOX = [{'sport': 'Boxing', 'fighter1': 'Ed Epsilon', 'fighter2': 'Fy Zeta', 'date': '2026-08-20',
            'time': '21:00', 'is_main_event': True, 'venue': 'Hall', 'location': 'London', 'weight_class': 'Heavyweight'}]
UFC_URL = '/event/ufc-330-alpha-vs.-beta-2026-08-16'
BOX_URL = '/boxing-event/ed-epsilon-vs-fy-zeta-2026-08-20'


def _seed_archive():
    A._runs.write_json_atomic(A.RESULTS_ARCHIVE_FILE, OLD_UFC + OLD_BOX)


def test_old_fight_pages_stay_online(client):
    _seed_archive()
    r = client.get(UFC_URL)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Alpha' in body and 'Gamma' in body
    hero = body.split('class="hero')[1][:2500]
    assert 'Alpha' in hero, 'the headline bout leads the old card too'
    assert client.get(BOX_URL).status_code == 200


def test_old_fights_stay_off_the_lists(client):
    _seed_archive()
    for path in ('/', '/results', '/ufc', '/boxing'):
        assert 'Epsilon' not in client.get(path).get_data(as_text=True), path


def test_unknown_old_url_is_still_404(client):
    _seed_archive()
    assert client.get('/event/ufc-329-nobody-vs.-none-2026-07-11').status_code == 404


def test_sitemap_keeps_old_pages_and_honest_dates(client):
    _seed_archive()
    xml = client.get('/sitemap.xml').get_data(as_text=True)
    assert 'https://fightschedule.live' + UFC_URL + '</loc>' in xml
    assert 'https://fightschedule.live' + BOX_URL + '</loc>' in xml
    lastmod = dict(re.findall(r'<loc>https://fightschedule.live(/[a-z]*)</loc>\s*<lastmod>([^<]+)</lastmod>', xml))
    assert lastmod['/privacy'] == A.PRIVACY_UPDATED.isoformat()
    assert lastmod['/results'] < '2026-10-02', 'Results: the newest result, not "today"'


def test_archived_pages_are_not_reported_removed(data_dir, seeded_cache):
    _seed_archive()
    A.sync_page_versions(seeded_cache, reason='test')
    urls = set(A._load_versions())
    assert 'https://fightschedule.live' + UFC_URL in urls
    assert 'https://fightschedule.live' + BOX_URL in urls


def test_privacy_page_shows_real_update_date(client):
    d = A.PRIVACY_UPDATED
    assert f'Last updated: {d.day} {d:%B %Y}' in client.get('/privacy').get_data(as_text=True)

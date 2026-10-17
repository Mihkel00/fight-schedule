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
# a full card (4 other bouts) keeps a page worth indexing without a tale of the tape or a preview
# (design.worth_indexing, rule B, owner 2026-10-17)
OLD_UFC += [{'sport': 'UFC', 'event_name': 'UFC 330: Alpha vs. Beta', 'fighter1': f'P{i} Prelim', 'fighter2': f'Q{i} Quiet',
             'date': '2026-08-16', 'time': '01:00', 'card_type': 'Prelims', 'venue': 'Some Arena'} for i in range(3)]
OLD_BOX = [{'sport': 'Boxing', 'fighter1': 'Ed Epsilon', 'fighter2': 'Fy Zeta', 'date': '2026-08-20',
            'time': '21:00', 'is_main_event': True, 'venue': 'Hall', 'location': 'London', 'weight_class': 'Heavyweight'}]
OLD_BOX += [{'sport': 'Boxing', 'fighter1': f'U{i} Under', 'fighter2': f'V{i} Card', 'date': '2026-08-20', 'time': '19:00',
             'is_main_event': False, 'venue': 'Hall', 'location': 'London'} for i in range(4)]
# a thin old card: one bout, no profiles, no preview. Online, but noindex and out of the sitemap.
THIN_BOX = [{'sport': 'Boxing', 'fighter1': 'Th Thin', 'fighter2': 'Un Unknown', 'date': '2026-08-21',
             'time': '21:00', 'is_main_event': True, 'venue': 'Gym', 'location': 'Leeds'}]
UFC_URL = '/event/ufc-330-alpha-vs.-beta-2026-08-16'
BOX_URL = '/boxing-event/ed-epsilon-vs-fy-zeta-2026-08-20'
THIN_URL = '/boxing-event/th-thin-vs-un-unknown-2026-08-21'


def _seed_archive():
    A._runs.write_json_atomic(A.RESULTS_ARCHIVE_FILE, OLD_UFC + OLD_BOX + THIN_BOX)


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
    assert THIN_URL not in xml, 'a thin page (one bout, no tape, no preview) stays out of the sitemap'
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


def test_thin_fight_page_is_online_but_noindex(client):
    """Rule B (owner 2026-10-17): a fight page with no tale of the tape, no preview and under 4 other bouts, or a
    TBA fighter, stays online for visitors but tells search engines noindex and leaves the sitemap."""
    _seed_archive()
    r = client.get(THIN_URL)
    assert r.status_code == 200
    h = r.get_data(as_text=True)
    assert '<meta name="robots" content="noindex, follow">' in h and 'Thin' in h
    full = client.get(BOX_URL).get_data(as_text=True)
    assert '<meta name="robots" content="index, follow' in full

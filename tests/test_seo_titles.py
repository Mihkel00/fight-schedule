"""Search titles, descriptions and the H1 of fight pages."""
import re
from html import unescape

import app as A


def test_place_is_not_repeated():
    assert A._place_text('London', 'London') == 'London'
    assert A._place_text('Las Vegas', 'Las Vegas, Nevada') == 'Las Vegas, Nevada'
    assert A._place_text('TBA', 'Spain') == 'Spain'
    assert A._place_text(None, None) == ''


def test_boxing_kind():
    assert A._boxing_kind('Title Heavyweight') == 'heavyweight title fight'
    assert A._boxing_kind('Super Middleweight') == 'super middleweight bout'
    assert A._boxing_kind(None) == 'bout'


def test_upcoming_and_past_titles():
    t, d = A.fight_page_seo('UFC', 'UFC 333: Volkanovski vs. Evloev', '2026-10-24', 'Etihad Arena', 'Etihad Arena', False)
    assert t == 'UFC 333: Volkanovski vs. Evloev: Start Time, Date & Fight Card'
    assert 'Saturday 24 October 2026 at Etihad Arena' in d and '2026-10-24' not in d
    t, d = A.fight_page_seo('Boxing', 'Daniel Dubois vs Fabio Wardley', '2026-10-17', 'London', 'London', True,
                            kind='heavyweight title fight')
    assert t == 'Daniel Dubois vs Fabio Wardley: Result & Full Card'
    assert 'London, London' not in d and 'AI' not in d


def test_long_names_stay_within_limits():
    t, d = A.fight_page_seo('Boxing', 'Kyonosuke Kameda vs Sebastian Hernandez Reyes', '2026-09-23',
                            'Some Very Long Arena Name, Osaka, Japan', 'Osaka, Japan', False, kind='super bantamweight title fight',
                            streaming='DAZN')
    assert len(t) <= A.TITLE_MAX and len(d) <= 200


def _pages(client):
    sm = client.get('/sitemap.xml').get_data(as_text=True)
    return [u.replace('https://fightschedule.live', '') or '/' for u in re.findall(r'<loc>([^<]+)</loc>', sm)]


def test_every_page_has_one_h1_and_unique_title(client):
    titles = {}
    for p in _pages(client):
        h = client.get(p).get_data(as_text=True)
        assert len(re.findall(r'<h1[\s>]', h)) == 1, p
        t = unescape(re.search(r'<title>(.*?)</title>', h, re.S).group(1).strip())
        assert t not in titles, (p, titles.get(t))
        titles[t] = p
        if '/event/' in p or '/boxing-event/' in p:      # list pages use a shorter share title on purpose
            og = unescape(re.search(r'og:title" content="([^"]*)"', h).group(1))
            assert og == t, p


def test_fight_page_h1_names_the_matchup(client):
    h = client.get('/event/ufc-332-silva-vs.-wang-2026-10-04').get_data(as_text=True)
    h1 = re.sub(r'\s+', ' ', re.sub('<[^>]+>', ' ', re.search(r'<h1[^>]*>(.*?)</h1>', h, re.S).group(1))).strip()
    assert h1.startswith('UFC 332') and ' vs ' in h1

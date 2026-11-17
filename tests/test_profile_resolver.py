"""Wikipedia title resolution must survive punctuation differences between sources and
Wikipedia (owner, 2026-10-31: "Christian Mbilli" vs the article "Christian M'billi"),
and a resolver change must retry the names an older resolver gave up on."""
from datetime import datetime, timedelta

import profile_store
from scrapers import fighter_profiles as fp


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _fake_api(search_titles, direct_title=None):
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append(params)
        if params.get('list') == 'search':
            return _Resp({'query': {'search': [{'title': t} for t in search_titles]}})
        if 'titles' in params:
            page = {'title': direct_title} if direct_title else {'missing': ''}
            return _Resp({'query': {'pages': {'1': page}}})
        raise AssertionError(params)
    return get, calls


def test_apostrophe_in_article_title_still_matches(monkeypatch):
    get, _ = _fake_api(['Canelo Álvarez', "Christian M'billi"])
    monkeypatch.setattr(fp.requests, 'get', get)
    assert fp.resolve_title('Christian Mbilli', 'Boxing') == "Christian M'billi"


def test_name_used_as_title_follows_redirect_when_search_misses(monkeypatch):
    get, calls = _fake_api(['Canelo Álvarez'], direct_title="Christian M'billi")
    monkeypatch.setattr(fp.requests, 'get', get)
    assert fp.resolve_title('Christian Mbilli', 'Boxing') == "Christian M'billi"
    assert calls[1]['titles'] == 'Christian Mbilli' and calls[1]['redirects'] == 1


def test_redirect_to_someone_else_is_rejected(monkeypatch):
    get, _ = _fake_api([], direct_title='Boxing in Cameroon')
    monkeypatch.setattr(fp.requests, 'get', get)
    assert fp.resolve_title('Christian Mbilli', 'Boxing') is None


def test_other_professions_and_strangers_still_rejected(monkeypatch):
    get, _ = _fake_api(['Ryan Garcia (politician)', 'Ryan García Sánchez'])
    monkeypatch.setattr(fp.requests, 'get', get)
    assert fp.resolve_title('Ryan Garcia', 'Boxing') is None


def test_same_person_ignores_punctuation():
    assert fp._same_person("Christian M'billi", 'Christian Mbilli')
    assert fp._same_person("Sean O'Malley", 'Sean OMalley')
    assert not fp._same_person('Christian Mbilli', 'Christian Billi')


def test_old_resolver_misses_are_retried_but_current_ones_wait():
    fights = [{'fighter1': 'Christian Mbilli', 'fighter2': 'Kevin Lele', 'date': '2026-11-20', 'sport': 'Boxing'}]
    fresh = (datetime.now() - timedelta(hours=1)).isoformat()
    profiles = {
        'christian mbilli': {'title': None, 'profile': None, 'fetched_at': fresh},
        'kevin lele': {'title': None, 'profile': None, 'fetched_at': fresh,
                       'resolver': profile_store.RESOLVER_VERSION},
    }
    names = [n for n, _ in profile_store._profile_work_list(fights, profiles)]
    assert names == ['Christian Mbilli']


def test_letters_without_a_separate_accent_still_match(monkeypatch):
    # "ł" does not decompose into "l" + accent; it must not be deleted (2026-11-17, Michał Cieślak)
    get, _ = _fake_api(['Michał Cieślak (boxer)'])
    monkeypatch.setattr(fp.requests, 'get', get)
    assert fp.resolve_title('Michal Cieslak', 'Boxing') == 'Michał Cieślak (boxer)'
    for a, b in [('Søren', 'Soren'), ('Đorđe', 'Dorde'), ('Strauß', 'Strauss'), ('Kılıç', 'Kilic')]:
        assert fp._loose(a) == fp._loose(b), (a, b)


def test_stored_keys_do_not_change():
    # profile and photo keys are built from _norm; changing them would orphan saved data
    assert fp._norm('Michał Cieślak') == 'micha cieslak'


def test_refusal_is_not_no_article(monkeypatch):
    monkeypatch.setattr(fp.requests, 'get', lambda *a, **k: _Resp(None, status_code=429))
    import pytest
    with pytest.raises(fp.WikiUnavailable):
        fp.resolve_title('Tyrone McKenna', 'Boxing')
    with pytest.raises(fp.WikiUnavailable):
        fp.fetch_profile('Tyrone McKenna', 'Boxing')


def test_profile_job_keeps_data_and_stops_when_refused(monkeypatch):
    fights = [{'fighter1': 'Tyrone McKenna', 'fighter2': 'Josh Blenkiron', 'date': '2026-12-19', 'sport': 'Boxing'}]
    saved = {}
    old = {'josh blenkiron': {'name': 'Josh Blenkiron', 'title': 'Josh Blenkiron', 'profile': {'record': '1-0'},
                              'fetched_at': '2026-01-01T00:00:00'}}
    calls = []

    def refuse(name, sport):
        calls.append(name)
        raise fp.WikiUnavailable('HTTP 429')
    monkeypatch.setattr(profile_store, 'load_profiles', lambda: dict(old))
    monkeypatch.setattr(profile_store, 'save_profiles', lambda d: saved.update(d))
    monkeypatch.setattr(profile_store._wiki, 'resolve_title', refuse)
    monkeypatch.setattr(profile_store._wiki, 'fetch_profile', refuse)
    monkeypatch.setattr(profile_store.time, 'sleep', lambda s: None)
    monkeypatch.setattr(profile_store._images, 'autofill_new_fighters', lambda: None)
    monkeypatch.setattr(profile_store.seo, 'sync_page_versions', lambda *a, **k: None)
    profile_store._profile_job_state['running'] = False
    profile_store._real_refresh_profiles(fights)
    assert len(calls) == 1                                   # stopped at the first refusal
    assert 'tyrone mckenna' not in saved                     # no "no article" stored for him
    assert saved['josh blenkiron']['profile'] == {'record': '1-0'}   # existing data untouched


# Responses as Wikipedia gave them on 2026-11-17 (search titles, redirect targets), plus
# whether each page has a fight-record table.
_RECORD = ('<table class="wikitable"><tr><th>Res.</th><th>Record</th><th>Opponent</th><th>Method</th><th>Date</th></tr>'
           '<tr><td>Win</td><td>1-0</td><td>X</td><td>KO</td><td>1 March 2025</td></tr></table>')
_PAGES = {'Sharabutdin Magomedov': _RECORD, 'Brian Norman Jr.': _RECORD, 'Jazza Dickens': _RECORD,
          'The Mighty Celt': '<p>The Mighty Celt is a 2005 film.</p>', 'Brian Norman Smith': _RECORD}
_REDIRECTS = {'Shara Magomedov': 'Sharabutdin Magomedov', 'Tyrone McKenna': 'The Mighty Celt'}


def _wiki_fake(search):
    def get(url, params=None, headers=None, timeout=None):
        if params.get('list') == 'search':
            return _Resp({'query': {'search': [{'title': t} for t in search]}})
        if params.get('action') == 'parse':
            html = _PAGES.get(params['page'])
            if html is None:
                return _Resp({'error': {'code': 'missingtitle'}})
            return _Resp({'parse': {'title': params['page'], 'text': {'*': html}}})
        t = _REDIRECTS.get(params['titles']) or (params['titles'] if params['titles'] in _PAGES else None)
        return _Resp({'query': {'pages': {'1': {'title': t} if t else {'missing': ''}}}})
    return get


def test_redirect_to_a_fighter_page_is_accepted(monkeypatch):
    monkeypatch.setattr(fp.requests, 'get', _wiki_fake(['2026 in UFC']))
    assert fp.resolve_title('Shara Magomedov', 'UFC') == 'Sharabutdin Magomedov'


def test_redirect_to_a_film_is_rejected(monkeypatch):
    monkeypatch.setattr(fp.requests, 'get', _wiki_fake(['Belfast']))
    assert fp.resolve_title('Tyrone McKenna', 'Boxing') is None


def test_jr_suffix_on_the_article_is_accepted(monkeypatch):
    monkeypatch.setattr(fp.requests, 'get', _wiki_fake(['Brian Norman Jr.', 'Brian Norman Smith']))
    assert fp.resolve_title('Brian Norman', 'Boxing') == 'Brian Norman Jr.'


def test_nickname_inside_the_name(monkeypatch):
    monkeypatch.setattr(fp.requests, 'get', _wiki_fake(['Jazza Dickens', 'Dickens (surname)']))
    assert fp.resolve_title('James “Jazza” Dickens', 'Boxing') == 'Jazza Dickens'


def test_same_surname_without_a_fight_record_is_rejected(monkeypatch):
    _PAGES_NO = {**_PAGES, 'Brian Norman Jr.': '<p>American politician.</p>'}
    monkeypatch.setattr(fp, 'fetch_profile', lambda t, s=None: fp.parse_profile(_PAGES_NO[t], t, s) if t in _PAGES_NO else None)
    monkeypatch.setattr(fp.requests, 'get', _wiki_fake(['Brian Norman Jr.']))
    assert fp.resolve_title('Brian Norman', 'Boxing') is None


_GOALS = ('<table class="wikitable"><tr><th>No.</th><th>Date</th><th>Venue</th><th>Opponent</th><th>Score</th>'
          '<th>Result</th><th>Competition</th></tr><tr><td>1</td><td>11 June 2022</td><td>X</td><td>Suriname</td>'
          '<td>1–0</td><td>3–0</td><td>Nations League</td></tr></table>')


def test_another_sports_results_table_is_not_a_fight_record(monkeypatch):
    # 2026-11-17: "Eric Sanchez" (boxer) was matched to "Érick Sánchez", a footballer
    _PAGES['Érick Sánchez'] = _GOALS
    _REDIRECTS['Eric Sanchez'] = 'Érick Sánchez'
    try:
        monkeypatch.setattr(fp.requests, 'get', _wiki_fake(['Érick Sánchez']))
        assert fp.resolve_title('Eric Sanchez', 'Boxing') is None
    finally:
        _PAGES.pop('Érick Sánchez'); _REDIRECTS.pop('Eric Sanchez')


def test_renamed_titles_from_the_faulty_resolver_are_checked_again():
    fresh = datetime.now().isoformat()
    fights = [{'fighter1': 'Eric Sanchez', 'fighter2': 'Shara Magomedov', 'date': '2026-12-11', 'sport': 'Boxing'},
              {'fighter1': 'Brian Ortega', 'fighter2': 'Joel Camilleri', 'date': '2026-12-11', 'sport': 'UFC'}]
    profiles = {
        'eric sanchez': {'title': 'Érick Sánchez', 'fetched_at': fresh, 'resolver': 3},          # renamed, v3: recheck
        'shara magomedov': {'title': 'Sharabutdin Magomedov', 'fetched_at': fresh,
                            'resolver': profile_store.RESOLVER_VERSION},                       # renamed, current: keep
        'brian ortega': {'title': 'Brian Ortega', 'fetched_at': fresh, 'resolver': 3},          # exact title: keep
        'joel camilleri': {'title': None, 'fetched_at': fresh, 'resolver': 3},                  # v3 miss: keep
    }
    assert [n for n, _ in profile_store._profile_work_list(fights, profiles)] == ['Eric Sanchez']

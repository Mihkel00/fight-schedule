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

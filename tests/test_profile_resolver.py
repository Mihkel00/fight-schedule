"""Wikipedia title resolution must survive punctuation differences between sources and
Wikipedia (owner, 2026-10-31: "Christian Mbilli" vs the article "Christian M'billi"),
and a resolver change must retry the names an older resolver gave up on."""
from datetime import datetime, timedelta

import profile_store
from scrapers import fighter_profiles as fp


class _Resp:
    def __init__(self, payload):
        self._payload = payload

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

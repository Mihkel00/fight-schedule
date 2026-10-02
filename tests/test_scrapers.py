"""Parsers against saved source pages. A page the parser cannot read must come
back as layout_unknown / http_error, never as "no fights"."""
import json

from conftest import FakeResponse, read_fixture
from scrapers import boxing_scraper as B, ufc_scraper as U


# ---------------------------------------------------------------- boxing

def test_boxing_real_rsd_page_parses():
    r = B.parse(read_fixture('boxing_rsd_2026-10-02.html'))
    assert r['outcome'] == 'parsed' and r['layout'] == 'rsd-event'
    assert r['layouts']['rsd-event'] == 26
    assert len(r['fights']) == 138
    mains = [f for f in r['fights'] if f['is_main_event']]
    assert len(mains) == 23   # 26 containers on the page, 23 distinct cards (2026-09-30 double listing)
    assert all(f['sport'] == 'Boxing' and f['date'] >= '2026-10-02' for f in r['fights'])


def test_boxing_double_listing_is_deduplicated():
    """2026-09-30: boxingschedule.co listed a weekend's cards in two blocks."""
    r = B.parse(read_fixture('boxing_rsd_2026-10-02.html'))
    keys = [(tuple(sorted([f['fighter1'], f['fighter2']])), f['date']) for f in r['fights']]
    assert len(keys) == len(set(keys))
    assert sum(1 for f in r['fights'] if f['fighter1'] == 'Ben Whittaker') == 1


def test_boxing_rscard_layout_parses():
    r = B.parse(read_fixture('boxing_rscard_synthetic.html'))
    assert r['outcome'] == 'parsed' and r['layout'] == 'rs-card'
    assert [f['fighter1'] for f in r['fights']] == ['Dalton Smith', 'Pat McCormack', 'Junaid Bostan', 'Example One']
    main = r['fights'][0]
    assert main['is_main_event'] and main['weight_class'] == 'Title Super Lightweight' and main['rounds'] == '12'
    assert main['date'] == '2026-10-24' and main['time'] == '18:00'   # 2 pm ET -> 18:00 UTC
    assert main['streaming'] == 'DAZN'
    assert r['fights'][3]['time_estimated'] is True                   # Tokyo card, no time: venue estimate


def test_boxing_legacy_layout_parses_9pm_et():
    r = B.parse(read_fixture('boxing_legacy_synthetic.html'))
    assert r['outcome'] == 'parsed' and r['layout'] == 'legacy'
    smith = r['fights'][0]
    assert smith['fighter1'] == 'Dalton Smith' and smith['is_main_event']
    assert smith['time'] == '01:00'          # 9 pm ET = 01:00 UTC next day (the legacy date stays local)
    assert smith['weight_class'] == 'Title Super Lightweight'


def test_boxing_unknown_redesign_is_layout_unknown():
    r = B.parse(read_fixture('boxing_redesign_unknown.html'))
    assert r['outcome'] == 'layout_unknown' and not any(r['layouts'].values()) and r['fights'] == []


def test_boxing_empty_body_is_layout_unknown():
    assert B.parse(b'')['outcome'] == 'layout_unknown'


def test_boxing_http_error_is_not_empty_list(monkeypatch, data_dir):
    monkeypatch.setattr(B.requests, 'get', lambda *a, **k: FakeResponse(403, b'<html>Access denied</html>'))
    r = B.scrape_boxing()
    assert r['outcome'] == 'http_error' and r['fights'] == []
    assert r['snapshots'], 'the failed response must still be saved'


def test_boxing_events_wrapper_returns_list(monkeypatch, data_dir):
    monkeypatch.setattr(B.requests, 'get', lambda *a, **k: FakeResponse(200, read_fixture('boxing_rsd_2026-10-02.html')))
    assert len(B.scrape_boxing_events()) == 138


# ---------------------------------------------------------------- ufc / espn

def _espn(status_by_month):
    page = read_fixture('espn_scoreboard_202610_2026-10-02.json')

    def get(url, params=None, headers=None, timeout=None):
        m = (params or {}).get('dates')
        st = status_by_month.get(m, 200)
        if st != 200:
            return FakeResponse(st, b'Access Denied')
        return FakeResponse(200, page if m == '202610' else b'{"events": []}')
    return get


def test_espn_real_scoreboard_page(monkeypatch, data_dir):
    monkeypatch.setattr(U.requests, 'get', _espn({}))
    r = U.scrape_ufc(['202610'])
    assert r['outcome'] == 'parsed' and r['layout'] == 'espn-scoreboard'
    ufc332 = [f for f in r['fights'] if f['event_name'].startswith('UFC 332')]
    assert len(ufc332) == 14
    # 2026-10-01 incident: ESPN lists the opener first and labels every bout the same
    assert ufc332[0]['fighter1'] == 'Court McGee'
    assert {f['card_type'] for f in ufc332} == {'Main Card'}
    assert not any('Contender Series' in f['event_name'] for f in r['fights'])


def test_espn_partial_months(monkeypatch, data_dir):
    monkeypatch.setattr(U.requests, 'get', _espn({'202611': 403, '202612': 403, '202701': 403}))
    r = U.scrape_ufc(['202610', '202611', '202612', '202701', '202702', '202703'])
    assert r['outcome'] == 'partial'
    assert r['diagnostics']['months_failed'] == ['202611', '202612', '202701']
    assert len(r['fights']) > 20, 'what was read is still returned'


def test_espn_all_blocked_is_http_error(monkeypatch, data_dir):
    monkeypatch.setattr(U.requests, 'get', _espn({'202610': 403, '202611': 403}))
    r = U.scrape_ufc(['202610', '202611'])
    assert r['outcome'] == 'http_error' and r['fights'] == []


def test_espn_unknown_shape_is_layout_unknown(monkeypatch, data_dir):
    monkeypatch.setattr(U.requests, 'get', lambda *a, **k: FakeResponse(200, b'{"message": "new api"}'))
    assert U.scrape_ufc(['202610'])['outcome'] == 'layout_unknown'


def test_espn_bout_without_time_keeps_event_date(monkeypatch, data_dir):
    page = json.loads(read_fixture('espn_scoreboard_202610_2026-10-02.json'))
    for ev in page['events']:
        for c in ev['competitions']:
            c.pop('date', None)
    monkeypatch.setattr(U.requests, 'get', lambda *a, **k: FakeResponse(200, json.dumps(page).encode()))
    event_date = next(e for e in page['events'] if e['name'].startswith('UFC 332'))['date'][:10]
    r = U.scrape_ufc(['202610'])
    ufc332 = [f for f in r['fights'] if f['event_name'].startswith('UFC 332')]
    assert ufc332 and all(f['time'] is None and f['date'] == event_date for f in ufc332)

"""normalize_ufc_cards: the main event and card segments must come from the
data, never from the order a source happened to use."""
import copy
import json

import app as A
import invariants
from conftest import FakeResponse, read_fixture
from scrapers import ufc_scraper as U


def _scraped_ufc(monkeypatch):
    page = read_fixture('espn_scoreboard_202610_2026-10-02.json')
    monkeypatch.setattr(U.requests, 'get', lambda *a, **k: FakeResponse(200, page))
    return U.scrape_ufc(['202610'])['fights']


def test_main_event_from_title_not_list_position(monkeypatch, data_dir):
    """2026-10-01: UFC 332 showed McGee vs Nolan (the opener) as its main event."""
    fights = A.normalize_ufc_cards(_scraped_ufc(monkeypatch))
    ufc332 = [f for f in fights if f['event_name'].startswith('UFC 332')]
    head = ufc332[0]
    assert (head['fighter1'], head['fighter2']) == ('Natalia Silva', 'Wang Cong')
    assert head['date'] == '2026-10-04' and head['time'] == '00:00' and head['card_type'] == 'Main Card'
    assert head['bout_order'] == 0


def test_segments_from_start_times_when_labels_are_useless(monkeypatch, data_dir):
    fights = A.normalize_ufc_cards(_scraped_ufc(monkeypatch))
    ufc332 = [f for f in fights if f['event_name'].startswith('UFC 332')]
    main = [f for f in ufc332 if f['card_type'] == 'Main Card']
    pre = [f for f in ufc332 if f['card_type'] == 'Prelims']
    assert len(main) == 5 and len(pre) == 9
    assert all(f['time'] == '00:00' for f in main)
    assert max(f['time'] for f in pre) < '24:00' and all(f['date'] == '2026-10-03' for f in pre)


def test_every_titled_event_leads_with_its_named_bout(monkeypatch, data_dir):
    fights = A.normalize_ufc_cards(_scraped_ufc(monkeypatch))
    assert all(c['ok'] for c in invariants.model_checks(fights) if c['name'] in ('one_main_event_per_ufc_event', 'ufc_main_event_matches_title', 'prelims_before_main_card')), invariants.failures(fights)


def test_normalize_is_idempotent(monkeypatch, data_dir):
    once = A.normalize_ufc_cards(_scraped_ufc(monkeypatch))
    twice = A.normalize_ufc_cards(copy.deepcopy(once))
    assert [(f['fighter1'], f['card_type'], f['bout_order']) for f in once] == [(f['fighter1'], f['card_type'], f['bout_order']) for f in twice]


def test_normalize_keeps_every_bout_and_boxing_untouched(fights):
    before = sorted((f['fighter1'], f['fighter2'], f['date']) for f in fights)
    boxing_before = [f for f in fights if f['sport'] == 'Boxing']
    out = A.normalize_ufc_cards(copy.deepcopy(fights))
    assert sorted((f['fighter1'], f['fighter2'], f['date']) for f in out) == before
    assert [f for f in out if f['sport'] == 'Boxing'] == boxing_before


def test_single_start_time_card_keeps_source_order_but_still_finds_title_bout():
    card = [
        {'sport': 'UFC', 'event_name': 'UFC 999: Doe vs. Roe', 'fighter1': 'Al Opener', 'fighter2': 'Bo First', 'date': '2026-12-01', 'time': '20:00', 'card_type': 'Main Card'},
        {'sport': 'UFC', 'event_name': 'UFC 999: Doe vs. Roe', 'fighter1': 'Jane Doe', 'fighter2': 'Rick Roe', 'date': '2026-12-01', 'time': '20:00', 'card_type': 'Main Card'},
    ]
    out = A.normalize_ufc_cards(card)
    assert out[0]['fighter1'] == 'Jane Doe' and out[0]['bout_order'] == 0
    assert {f['card_type'] for f in out} == {'Main Card'}, 'one start time: nothing is relabelled a prelim'


def test_load_cache_dedups_and_normalizes(data_dir, fights):
    """A cache written before these rules existed may hold repeats and ESPN order."""
    import datetime
    doubled = fights + [dict(f) for f in fights if f['sport'] == 'Boxing'][:40]
    A._runs.write_json_atomic(A.CACHE_FILE, {'timestamp': datetime.datetime.now().isoformat(), 'fights': doubled})
    out = A.load_cache()
    assert len(out) == len(fights)
    assert all('bout_order' in f for f in out if f['sport'] == 'UFC')

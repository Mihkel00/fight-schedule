"""The scrape/merge/carry-forward pipeline, run records and /health."""
import datetime
import glob
import json
import os

import app as A
import runs


def _ok(fights, sport):
    return {'fights': [dict(f) for f in fights if f['sport'] == sport and f['date'] >= '2026-10-01'], 'outcome': 'parsed', 'layout': 'test'}


def test_both_sources_down_carries_cache_forward_and_fails_health(seeded_cache, monkeypatch):
    monkeypatch.setattr(A, 'scrape_ufc_events', lambda: {'fights': [], 'outcome': 'http_error', 'diagnostics': {'error': 'HTTP 403'}})
    monkeypatch.setattr(A, 'scrape_boxing_events', lambda: {'fights': [], 'outcome': 'layout_unknown', 'layouts': {'rsd-event': 0, 'rs-card': 0, 'legacy': 0}})
    out = A._scrape_all_sources()
    assert sum(1 for f in out if f['sport'] == 'UFC') > 20 and sum(1 for f in out if f['sport'] == 'Boxing') > 20
    assert runs.last_run('UFC')['status'] == 'failed' and 'fetched' in runs.last_run('UFC')['note']
    assert runs.last_run('Boxing')['status'] == 'failed' and 'layout' in runs.last_run('Boxing')['note']
    r = A.app.test_client().get('/health')
    assert r.status_code == 503 and all(not s['healthy'] for s in r.get_json()['sources'])


def test_good_scrape_writes_ok_runs_and_health_200(seeded_cache, monkeypatch):
    monkeypatch.setattr(A, 'scrape_ufc_events', lambda: _ok(seeded_cache, 'UFC'))
    monkeypatch.setattr(A, 'scrape_boxing_events', lambda: _ok(seeded_cache, 'Boxing'))
    A._scrape_all_sources()
    assert runs.last_run('UFC')['status'] == 'ok' and runs.last_run('Boxing')['status'] == 'ok'
    r = A.app.test_client().get('/health')
    assert r.status_code == 200 and r.get_json()['healthy']
    assert r.get_json()['sources'][0]['next_scrape_due']


def test_partial_espn_is_used_but_flagged(seeded_cache, monkeypatch):
    ufc = _ok(seeded_cache, 'UFC')
    ufc.update(outcome='partial', months={'202610': {'fights': 30}, '202611': {'fights': 0, 'error': 'HTTP 403'}})
    monkeypatch.setattr(A, 'scrape_ufc_events', lambda: ufc)
    monkeypatch.setattr(A, 'scrape_boxing_events', lambda: _ok(seeded_cache, 'Boxing'))
    out = A._scrape_all_sources()
    rec = runs.last_run('UFC')
    assert rec['status'] == 'partial'
    assert any(c['name'] == 'all_months' and not c['ok'] for c in rec['checks'])
    assert sum(1 for f in out if f['sport'] == 'UFC') >= 20


def test_below_floor_is_failed_and_carried_forward(seeded_cache, monkeypatch):
    monkeypatch.setattr(A, 'scrape_ufc_events', lambda: {'fights': _ok(seeded_cache, 'UFC')['fights'][:3], 'outcome': 'parsed'})
    monkeypatch.setattr(A, 'scrape_boxing_events', lambda: _ok(seeded_cache, 'Boxing'))
    out = A._scrape_all_sources()
    assert runs.last_run('UFC')['status'] == 'failed' and 'floor' in runs.last_run('UFC')['note']
    assert sum(1 for f in out if f['sport'] == 'UFC') > 20


def test_plain_list_from_a_test_stub_is_accepted(seeded_cache, monkeypatch):
    monkeypatch.setattr(A, 'scrape_ufc_events', lambda: _ok(seeded_cache, 'UFC')['fights'])
    monkeypatch.setattr(A, 'scrape_boxing_events', lambda: _ok(seeded_cache, 'Boxing')['fights'])
    A._scrape_all_sources()
    assert runs.last_run('UFC')['status'] == 'ok'


def test_merged_output_has_no_duplicates_even_if_sources_repeat(seeded_cache, monkeypatch):
    """2026-09-30: boxingschedule.co listed cards twice."""
    box = _ok(seeded_cache, 'Boxing'); box['fights'] = box['fights'] * 2
    monkeypatch.setattr(A, 'scrape_ufc_events', lambda: _ok(seeded_cache, 'UFC'))
    monkeypatch.setattr(A, 'scrape_boxing_events', lambda: box)
    out = A._scrape_all_sources()
    keys = [A._fight_key(f) for f in out]
    assert len(keys) == len(set(keys))


def test_completed_fights_are_kept_for_results(seeded_cache, monkeypatch):
    """2026-09: fights finishing on the day were lost; sources drop a card as soon
    as it ends. A card that vanished from the source must stay as a result."""
    gone = [f for f in seeded_cache if f['sport'] == 'Boxing' and f['date'] == '2026-10-02']
    assert gone
    box = _ok(seeded_cache, 'Boxing'); box['fights'] = [f for f in box['fights'] if f['date'] != '2026-10-02']
    monkeypatch.setattr(A, 'scrape_ufc_events', lambda: _ok(seeded_cache, 'UFC'))
    monkeypatch.setattr(A, 'scrape_boxing_events', lambda: box)
    class Today(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 2)
    monkeypatch.setattr(A, 'date', Today)
    out = A._scrape_all_sources()
    assert any(f['fighter1'] == gone[0]['fighter1'] and f['date'] == '2026-10-02' for f in out)


def test_health_stale_after_30h(data_dir):
    old = (datetime.datetime.utcnow() - datetime.timedelta(hours=40)).strftime('%Y-%m-%dT%H:%M:%SZ')
    runs.write_run('UFC', 'ok', 'parsed', fetched_at=old)
    runs.write_run('Boxing', 'ok', 'parsed')
    r = A.app.test_client().get('/health')
    assert r.status_code == 503
    assert any('ago' in p for p in r.get_json()['sources'][0]['problems'])


def test_snapshot_round_trip_and_path_guard(data_dir):
    side = runs.save_snapshot('Boxing', 'schedule', 'https://x', 200, b'<html>page</html>')
    assert runs.read_snapshot(side['file']) == b'<html>page</html>'
    import pytest
    with pytest.raises(ValueError):
        runs.read_snapshot('../fights_cache.json')


def test_write_json_atomic_never_leaves_a_half_file(data_dir):
    p = os.path.join(data_dir, 'x.json')
    runs.write_json_atomic(p, {'a': 1})
    class Bad: pass
    import pytest
    with pytest.raises(TypeError):
        runs.write_json_atomic(p, {'a': Bad()})
    assert json.load(open(p)) == {'a': 1}
    assert not glob.glob(os.path.join(data_dir, '.x.json.*'))


def test_backfill_writes_a_manual_run(seeded_cache):
    c = A.app.test_client()
    new = [{'fighter1': 'Past One', 'fighter2': 'Past Two', 'date': '2026-09-20', 'time': '20:00', 'venue': 'X', 'location': 'X', 'sport': 'Boxing', 'is_main_event': True}]
    r = c.post('/api/debug/state?token=t&part=backfill', json=new)
    assert r.status_code == 200 and r.get_json()['added']
    assert runs.last_run('Boxing')['status'] == 'manual'


def test_debug_check_part_runs_invariants(client):
    d = client.get('/api/debug/state?token=t&part=check').get_json()
    assert 'checks' in d and any(c['name'] == 'no_duplicate_bouts' for c in d['checks'])

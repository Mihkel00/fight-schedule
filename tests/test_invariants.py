"""The named checks: pass on good data, fail on each kind of corruption."""
import copy

import app as A
import invariants as I


def _normalized(fights):
    return A.normalize_ufc_cards(copy.deepcopy(fights))


KNOWN = {'rows_valid'}   # the live cache holds one junk row ('TBA vs Opponent TBA'); rows are filtered in step 3


def test_fixture_passes_every_check(fights):
    fails = I.failures(_normalized(fights))
    assert {c['name'] for c in fails} <= KNOWN, fails
    rows = next(c for c in fails if c['name'] == 'rows_valid')
    assert rows['detail'].startswith('1 row problems'), rows


def test_duplicate_bouts_are_caught(fights):
    fs = _normalized(fights)
    fs.append(dict(next(f for f in fs if f['sport'] == 'Boxing' and not f.get('is_main_event'))))
    assert {c['name'] for c in I.failures(fs)} - KNOWN == {'no_duplicate_bouts'}


def test_opener_as_main_event_is_caught(fights):
    """The 2026-10-01 incident, as the checks would have seen it."""
    fs = _normalized(fights)
    ufc332 = [f for f in fs if f['sport'] == 'UFC' and f['event_name'].startswith('UFC 332')]
    opener = next(f for f in ufc332 if f['fighter1'] == 'Court McGee')
    head = next(f for f in ufc332 if f['bout_order'] == 0)
    opener['bout_order'], head['bout_order'] = 0, opener['bout_order']
    names = {c['name'] for c in I.failures(fs)}
    assert 'ufc_main_event_matches_title' in names


def test_two_main_events_on_a_boxing_card_are_caught(fights):
    fs = _normalized(fights)
    card = [f for f in fs if f['sport'] == 'Boxing' and not f['is_main_event']][0]
    card['is_main_event'] = True
    assert 'one_main_event_per_boxing_card' in {c['name'] for c in I.failures(fs)}


def test_prelim_after_main_card_is_caught(fights):
    fs = _normalized(fights)
    pre = next(f for f in fs if f['sport'] == 'UFC' and f['card_type'] == 'Prelims')
    pre['date'], pre['time'] = '2026-12-31', '23:59'
    assert 'prelims_before_main_card' in {c['name'] for c in I.failures(fs)}


def test_bad_rows_are_caught():
    assert 'fighter1 missing' in I.row_checks({'fighter1': 'TBA', 'fighter2': 'X', 'date': '2026-10-01', 'sport': 'Boxing'})
    assert 'fighter1 equals fighter2' in I.row_checks({'fighter1': 'A', 'fighter2': 'a', 'date': '2026-10-01', 'sport': 'Boxing'})
    assert any('bad date' in p for p in I.row_checks({'fighter1': 'A', 'fighter2': 'B', 'date': '1/10/2026', 'sport': 'UFC', 'event_name': 'x'}))
    assert any('bad time' in p for p in I.row_checks({'fighter1': 'A', 'fighter2': 'B', 'date': '2026-10-01', 'time': '8pm', 'sport': 'Boxing'}))
    assert 'UFC fight without event_name' in I.row_checks({'fighter1': 'A', 'fighter2': 'B', 'date': '2026-10-01', 'sport': 'UFC'})
    assert I.row_checks({'fighter1': 'A', 'fighter2': 'TBA', 'date': '2026-10-01', 'time': 'TBA', 'sport': 'Boxing'}) == []


def test_floor_is_a_named_check():
    assert not I.check_counts([{'sport': 'UFC'}] * 3)[1]

"""Grounded previews: written from our stored facts, checked before showing."""
import json
import time

import app as A
import previews as P


def _profile(name, wins, losses, ko, age, height_cm, reach_in, fights, draws=0):
    return {'name': name, 'profile': {
        'has_tape': True, 'record': {'wins': wins, 'losses': losses, 'draws': draws, 'ko_wins': ko, 'total': wins + losses + draws},
        'age': age, 'height_text': f'{height_cm} cm', 'height_cm': height_cm, 'reach_text': f'{reach_in} in', 'reach_in': reach_in,
        'stance': 'Orthodox', 'birthplace': 'London, England', 'fights': fights,
        'url': 'https://en.wikipedia.org/wiki/' + name.replace(' ', '_')}}


PROFILES = {
    'daniel dubois': _profile('Daniel Dubois', 23, 3, 22, 29, 196, 78, [
        {'date': '2026-05-09', 'result': 'Win', 'opponent': 'Fabio Wardley', 'method': 'TKO', 'round': '11', 'notes': 'Won WBO heavyweight title'},
        {'date': '2025-07-19', 'result': 'Loss', 'opponent': 'Oleksandr Usyk', 'method': 'KO', 'round': '5', 'notes': 'Lost IBF heavyweight title'}]),
    'fabio wardley': _profile('Fabio Wardley', 20, 1, 19, 31, 196, 78, [
        {'date': '2026-05-09', 'result': 'Loss', 'opponent': 'Daniel Dubois', 'method': 'TKO', 'round': '11', 'notes': 'Lost WBO heavyweight title'},
        {'date': '2025-10-25', 'result': 'Win', 'opponent': 'Joseph Parker', 'method': 'TKO', 'round': '11', 'notes': 'Won WBO interim heavyweight title'}], draws=1),
}
GOOD = {'context': 'Rematch: Dubois stopped Wardley in round 11 in May to take the WBO title',
        'fighter1_edge': ['Stopped Wardley in their first fight', '22 of 23 wins by stoppage'],
        'fighter2_edge': ['19 of 20 wins by stoppage', 'Stopped Joseph Parker in round 11'],
        'what_to_watch': 'The first fight ended in round 11. Watch whether Wardley changes anything early.'}


def _facts():
    return P.build_facts('Daniel Dubois', 'Fabio Wardley', 'Boxing', 'Title Heavyweight', True,
                         PROFILES, A._tape, A._profile_key)


def test_facts_include_tape_recent_fights_and_earlier_meeting():
    facts, sources = _facts()
    assert facts['fighter1']['record'] == '23-3' and facts['fighter2']['record'] == '20-1-1'
    assert facts['fighter1']['current_champion'] is True and facts['fighter2']['current_champion'] is False
    assert facts['previous_meetings'] == [{'date': '2026-05-09', 'result': 'Daniel Dubois won', 'method': 'TKO',
                                           'round': '11', 'notes': 'Won WBO heavyweight title'}]
    assert [s['name'] for s in sources] == ['Daniel Dubois', 'Fabio Wardley']


def test_good_preview_passes():
    assert P.check(GOOD, _facts()[0]) == []


def test_unsupported_reach_and_size_are_rejected():
    bad = dict(GOOD, fighter2_edge=['Size and reach advantage in the division', '19 of 20 wins by stoppage'])
    probs = P.check(bad, _facts()[0])
    assert any('reach edge' in p for p in probs) and any('height/size edge' in p for p in probs)


def test_youth_edge_must_match_ages():
    assert P.check(dict(GOOD, fighter1_edge=['Youth advantage at 29', '22 of 23 wins by stoppage']), _facts()[0]) == []
    probs = P.check(dict(GOOD, fighter2_edge=['Younger and fresher', '19 of 20 wins by stoppage']), _facts()[0])
    assert any('age edge' in p for p in probs)


def test_numbers_must_come_from_the_facts():
    probs = P.check(dict(GOOD, fighter1_edge=['24 knockouts in his career', '22 of 23 wins by stoppage']), _facts()[0])
    assert any('number 24' in p for p in probs)


def test_missing_rematch_is_rejected_and_against_is_not_again():
    bad = dict(GOOD, context='Dubois defends his title against Wardley', fighter1_edge=['22 of 23 wins by stoppage'],
               what_to_watch='Watch the middle rounds.')
    assert 'it is a rematch but the preview does not say so' in P.check(bad, _facts()[0])


def test_unbeaten_and_former_champion_are_checked():
    probs = P.check(dict(GOOD, fighter2_edge=['Unbeaten puncher', '19 of 20 wins by stoppage']), _facts()[0])
    assert any('called unbeaten' in p for p in probs)
    probs = P.check(dict(GOOD, context='Rematch: Wardley faces the former champion Dubois again'), _facts()[0])
    assert any('former champion' in p for p in probs)


def test_no_record_means_no_edges():
    facts, _ = P.build_facts('Daniel Dubois', 'Nobody Known', 'Boxing', None, False, PROFILES, A._tape, A._profile_key)
    bad = {'context': 'Dubois returns', 'fighter1_edge': ['22 of 23 wins by stoppage'],
           'fighter2_edge': ['Dangerous puncher'], 'what_to_watch': 'Watch the early rounds.'}
    assert any('no record' in p for p in P.check(bad, facts))


def test_parse_handles_code_fences_and_bad_json():
    assert P.parse('```json\n' + json.dumps(GOOD) + '\n```')['context'] == GOOD['context']
    assert P.parse('not json') is None


# ── generation, caching, display ────────────────────────────────────────────

def _setup(monkeypatch, replies):
    calls = []
    A._runs.write_json_atomic(A.data_path('fight_previews.json'), {})   # seeded at import; start empty
    monkeypatch.setattr(A, 'load_profiles', lambda: PROFILES)
    monkeypatch.setattr(A, 'ANTHROPIC_API_KEY', 'test-key')

    def fake(prompt):
        calls.append(prompt)
        return replies.pop(0) if replies else None
    monkeypatch.setattr(A, '_call_preview_model', fake)
    return calls


def _get(wait=True):
    return A.get_or_generate_preview(A.boxing_preview_id('Daniel Dubois', 'Fabio Wardley', '2026-10-17'),
                                     'Daniel Dubois', 'Fabio Wardley', 'Boxing', True, 'Title Heavyweight', wait=wait)


def test_good_preview_is_stored_and_reused(data_dir, monkeypatch):
    calls = _setup(monkeypatch, [json.dumps(GOOD)])
    e = _get()
    assert e['ok'] and e['grounded'] and e['parsed']['context'] == GOOD['context']
    assert 'previous_meetings' in calls[0] and 'Do not use anything you remember' in calls[0]
    assert _get()['parsed'] == e['parsed'] and len(calls) == 1, 'cached, no second call'


def test_bad_preview_is_retried_then_hidden(data_dir, monkeypatch):
    bad = dict(GOOD, fighter2_edge=['Size and reach advantage', '19 of 20 wins by stoppage'])
    calls = _setup(monkeypatch, [json.dumps(bad), json.dumps(bad)])
    assert _get() is None
    assert len(calls) == 2 and 'rejected for these reasons' in calls[1]
    stored = A.load_previews()[A.boxing_preview_id('Daniel Dubois', 'Fabio Wardley', '2026-10-17')]
    assert stored['ok'] is False and stored['problems']
    assert _get() is None and len(calls) == 2, 'not retried until the facts change'


def test_retry_can_fix_it(data_dir, monkeypatch):
    bad = dict(GOOD, fighter2_edge=['Size and reach advantage', '19 of 20 wins by stoppage'])
    _setup(monkeypatch, [json.dumps(bad), json.dumps(GOOD)])
    assert _get()['ok']


def test_old_ungrounded_preview_is_not_shown(data_dir, monkeypatch):
    pid = A.boxing_preview_id('Daniel Dubois', 'Fabio Wardley', '2026-10-17')
    A.save_preview(pid, {'text': '{}', 'parsed': {'context': 'Made up'}, 'generated_at': '2026-01-01T00:00:00'})
    calls = _setup(monkeypatch, [json.dumps(GOOD)])
    assert _get()['parsed']['context'] == GOOD['context'] and len(calls) == 1


def test_new_facts_regenerate(data_dir, monkeypatch):
    calls = _setup(monkeypatch, [json.dumps(GOOD), json.dumps(GOOD)])
    _get()
    changed = json.loads(json.dumps(PROFILES))
    changed['daniel dubois']['profile']['age'] = 30          # e.g. a birthday, or a new fight result
    monkeypatch.setattr(A, 'load_profiles', lambda: changed)
    _get()
    assert len(calls) == 2 and '"age": 30' in calls[1]


def test_no_records_no_call(data_dir, monkeypatch):
    calls = _setup(monkeypatch, [json.dumps(GOOD)])
    assert A.get_or_generate_preview('x', 'Nobody One', 'Nobody Two', 'Boxing', False, wait=True) is None
    assert calls == []


def test_pages_never_wait_on_the_model(data_dir, monkeypatch):
    calls = _setup(monkeypatch, [json.dumps(GOOD)])
    assert _get(wait=False) is None          # made in the background
    pid = A.boxing_preview_id('Daniel Dubois', 'Fabio Wardley', '2026-10-17')
    for _ in range(50):
        if pid in A.load_previews():
            break
        time.sleep(0.05)
    assert _get(wait=False)['ok'] and len(calls) == 1


def test_panel_shows_ai_label_and_sources():
    with A.app.app_context():
        t = A.app.jinja_env.from_string("{% from '_fight.html' import preview_panel %}{{ preview_panel(ev) }}")
        html = t.render(ev={'main_event': {'fighter1': 'Daniel Dubois', 'fighter2': 'Fabio Wardley'},
                            'preview': {'parsed': GOOD, 'sources': [{'name': 'Daniel Dubois', 'url': 'https://en.wikipedia.org/wiki/Daniel_Dubois'}]}})
    assert '<span class="ai-tag">AI summary</span>' in html
    assert 'Based on Wikipedia records: <a href="https://en.wikipedia.org/wiki/Daniel_Dubois"' in html


def test_startup_script_uses_the_page_preview_id():
    src = open('generate_previews.py').read()
    assert 'boxing_preview_id(' in src and 'wait=True' in src


def test_the_fight_itself_never_leaks_into_its_preview():
    """After the fight, Wikipedia lists it; facts only use fights before the date."""
    later = json.loads(json.dumps(PROFILES))
    later['daniel dubois']['profile']['fights'].insert(0, {'date': '2026-10-17', 'result': 'Win', 'opponent': 'Fabio Wardley',
                                                            'method': 'KO', 'round': '3', 'notes': 'Retained WBO heavyweight title'})
    facts, _ = P.build_facts('Daniel Dubois', 'Fabio Wardley', 'Boxing', None, True, later, A._tape, A._profile_key, before='2026-10-17')
    assert [m['date'] for m in facts['previous_meetings']] == ['2026-05-09']
    assert all(f['date'] < '2026-10-17' for f in facts['fighter1']['recent_fights'])


def test_finished_fight_keeps_its_preview(data_dir, monkeypatch):
    calls = _setup(monkeypatch, [json.dumps(GOOD)])
    pid = A.boxing_preview_id('Daniel Dubois', 'Fabio Wardley', '2026-09-01')
    A.save_preview(pid, {'grounded': True, 'ok': True, 'parsed': GOOD, 'facts_hash': 'old'})
    e = A.get_or_generate_preview(pid, 'Daniel Dubois', 'Fabio Wardley', 'Boxing', True, wait=True, fight_date='2026-09-01')
    assert e['parsed'] == GOOD and calls == []
    assert A.get_or_generate_preview('other', 'Daniel Dubois', 'Fabio Wardley', 'Boxing', True, wait=True,
                                     fight_date='2026-09-01') is None and calls == []

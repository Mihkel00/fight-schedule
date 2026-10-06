"""
Grounded fight previews: the AI writes from our stored Wikipedia facts, and
every preview is checked against those facts before it is shown.

Facts per fighter: tale of the tape (record, KO/sub/decision wins, age,
height, reach, stance, country) and the last five fights; plus any earlier
meetings between the two. The model is told to use only these facts. Then
check() rejects a preview that:
  - uses a number that is not in the facts (records, counts, ages, years),
  - claims a reach, height/size or youth edge the numbers do not support,
  - calls a fighter unbeaten who has losses,
  - misses that the fight is a rematch, or invents one,
  - calls a sitting champion a "former champion",
  - writes "edges" for a fighter we have no record for.
A rejected preview is not shown (see app.get_or_generate_preview).
"""

import hashlib
import json
import re

RECENT_FIGHTS = 5
_REMATCH_WORDS = r'\b(?:rematch|again|first fight|first meeting|first bout|previous(?:ly)?|met before|last meeting|trilogy|second fight|second meeting|run it back)\b'


def _norm(s):
    import unicodedata
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9 ]+', ' ', s).split()


def _same_person(a, b):
    """'Fabio Wardley' vs 'Fabio Wardley (boxer)' / accents / order: all name words of the shorter appear in the longer."""
    wa, wb = set(_norm(a)), set(_norm(b))
    wa.discard('boxer'), wb.discard('boxer'), wa.discard('fighter'), wb.discard('fighter')
    if not wa or not wb:
        return False
    small, big = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return small <= big


def _clean(text):
    if not text:
        return None
    t = re.sub(r'\s*\+\s*1\s*⁄\s*2', '½', str(text))
    return re.sub(r'\s+', ' ', t).strip()


def _is_title_note(notes):
    return bool(re.search(r'(title|championship)', notes or '', re.I))


def _won_title(fight):
    """A win that won, defended, retained or unified a real title (not an eliminator or interim)."""
    notes = fight.get('notes') or ''
    return (fight.get('result') == 'Win' and _is_title_note(notes)
            and bool(re.search(r'\b(won|defended|retained|unified)\b', notes, re.I))
            and not re.search(r'\b(interim|eliminator)\b', notes, re.I))


def _current_champion(fights):
    """Latest fight is a win that won, defended, retained or unified a title."""
    if not fights:
        return False
    return _won_title(fights[0])


def _fighter_facts(name, profile_entry, tape, before=None):
    p = (profile_entry or {}).get('profile') or {}
    fights = sorted((f for f in p.get('fights') or [] if not before or (f.get('date') or '') < before),
                    key=lambda f: f.get('date') or '', reverse=True)
    has_record = bool(tape and tape.get('record'))
    f = {'name': name, 'has_record': has_record}
    if not has_record:
        return f, fights, None
    f.update({
        'record': tape.get('record'), 'wins': tape.get('wins'), 'losses': tape.get('losses'), 'draws': tape.get('draws') or 0,
        'ko_wins': tape.get('ko_wins'), 'sub_wins': tape.get('sub_wins'), 'dec_wins': tape.get('dec_wins'),
        'age': tape.get('age'), 'height': _clean(tape.get('height')), 'height_cm': tape.get('height_cm'),
        'reach': _clean(tape.get('reach')), 'reach_in': tape.get('reach_in'), 'stance': tape.get('stance'),
        'country': tape.get('nationality'), 'division': p.get('division'),
        'current_champion': _current_champion(fights),
        'recent_fights': [{k: x.get(k) for k in ('date', 'result', 'opponent', 'method', 'round', 'notes', 'event') if x.get(k)}
                          for x in fights[:RECENT_FIGHTS]],
    })
    return f, fights, p.get('url')


def build_facts(fighter1, fighter2, sport, weight_class, is_title, profiles, tape_fn, key_fn, before=None):
    """Everything the model may use. tape_fn(profile_entry) -> tape dict; key_fn(name) -> profiles key.
    before: the fight's date; only fights before it count (so the fight itself never leaks in)."""
    sides, sources = [], []
    histories = []
    for name in (fighter1, fighter2):
        entry = profiles.get(key_fn(name))
        f, fights, url = _fighter_facts(name, entry, tape_fn(entry), before)
        sides.append(f)
        histories.append(fights)
        if url and f['has_record']:
            sources.append({'name': name, 'url': url})
    meetings = []
    for x in histories[0]:
        if _same_person(x.get('opponent'), fighter2):
            winner = fighter1 if x.get('result') == 'Win' else fighter2 if x.get('result') == 'Loss' else None
            meetings.append({'date': x.get('date'), 'result': 'Draw' if x.get('result') == 'Draw' else ('No contest' if not winner else f'{winner} won'),
                             'method': x.get('method'), 'round': x.get('round'), 'notes': x.get('notes')})
    if not meetings:   # history only on the other side
        for x in histories[1]:
            if _same_person(x.get('opponent'), fighter1):
                winner = fighter2 if x.get('result') == 'Win' else fighter1 if x.get('result') == 'Loss' else None
                meetings.append({'date': x.get('date'), 'result': 'Draw' if x.get('result') == 'Draw' else ('No contest' if not winner else f'{winner} won'),
                                 'method': x.get('method'), 'round': x.get('round'), 'notes': x.get('notes')})
    facts = {'sport': sport, 'weight_class': weight_class, 'title_fight': bool(is_title),
             'fighter1': sides[0], 'fighter2': sides[1], 'previous_meetings': meetings}
    return facts, sources


def has_any_record(facts):
    return facts['fighter1']['has_record'] or facts['fighter2']['has_record']


def facts_hash(facts):
    return hashlib.sha1(json.dumps(facts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def build_prompt(facts, problems=None):
    f1, f2 = facts['fighter1']['name'], facts['fighter2']['name']
    no_record = [x['name'] for x in (facts['fighter1'], facts['fighter2']) if not x['has_record']]
    redo = ''
    if problems:
        redo = ('\nYour previous attempt was rejected for these reasons; fix them:\n- ' + '\n- '.join(problems) + '\n')
    return f"""Write a short fight preview as JSON, using ONLY the facts below. They come from Wikipedia.

FACTS:
{json.dumps(facts, indent=1, ensure_ascii=False)}

Return exactly this JSON structure:
{{
  "context": "One sentence (max 16 words): why this fight matters, from the facts",
  "fighter1_edge": ["fact-based strength of {f1} (max 12 words)", "second one"],
  "fighter2_edge": ["fact-based strength of {f2} (max 12 words)", "second one"],
  "what_to_watch": "Max two sentences (30 words) on what will decide it, from the facts. No predictions."
}}

RULES:
- Every claim must come from the FACTS. Do not use anything you remember about these fighters.
- Use numbers exactly as given (records, KO counts, ages, rounds, years). Do not compute new ones except "N of M wins".
- Do not claim a height, size, reach or age advantage unless the numbers above clearly differ in that direction.
- If previous_meetings is not empty, say it is a rematch and how the earlier fight ended.
- Only call someone champion if current_champion is true or the recent fight notes say so.
- {('No record is available for ' + ' and '.join(no_record) + '. Return an empty edge list for them and say nothing specific about them.') if no_record else 'Both fighters have records.'}
- No predictions, no picking a winner, no hype words like "legend".
- Respond with the JSON only.{redo}"""


def parse(text):
    if not text:
        return None
    t = text.replace('```json', '').replace('```', '').strip()
    m = re.search(r'\{.*\}', t, re.S)
    try:
        d = json.loads(m.group(0) if m else t)
    except (ValueError, AttributeError):
        return None
    if not isinstance(d, dict):
        return None
    out = {'context': str(d.get('context') or '').strip(), 'what_to_watch': str(d.get('what_to_watch') or '').strip()}
    for k in ('fighter1_edge', 'fighter2_edge'):
        v = d.get(k) or []
        out[k] = [str(x).strip() for x in v if str(x).strip()][:2] if isinstance(v, list) else []
    return out


# ── the check ────────────────────────────────────────────────────────────────

def _allowed_numbers(facts):
    nums = set(re.findall(r'\d+(?:\.\d+)?', json.dumps(facts, ensure_ascii=False)))
    for side in ('fighter1', 'fighter2'):
        f = facts[side]
        if not f.get('has_record'):
            continue
        w, l, d = f.get('wins') or 0, f.get('losses') or 0, f.get('draws') or 0
        derived = [w + l + d, w + l, (f.get('ko_wins') or 0) + (f.get('sub_wins') or 0), len(f.get('recent_fights') or [])]
        nums |= {str(x) for x in derived}
    for y in list(nums):
        if len(y) == 4 and y.startswith('20'):
            nums.add(y[2:])          # "2023–24"
    nums |= {str(i) for i in range(0, 6)}   # rounds / "twice" / "one of"
    return nums


_PHYS = [
    (r'\breach\b', 'reach_in', 'more', 'reach'),
    (r'\b(height|taller|size|bigger|larger|longer frame)\b', 'height_cm', 'more', 'height/size'),
    (r'\b(young|youth|younger|youthful)\b', 'age', 'less', 'age'),
]


def check(parsed, facts):
    """Problems with a preview, as plain sentences. Empty list = publishable."""
    if not parsed or not parsed.get('context') or not parsed.get('what_to_watch'):
        return ['missing context or what to watch']
    probs = []
    sides = [facts['fighter1'], facts['fighter2']]
    edges = [parsed.get('fighter1_edge') or [], parsed.get('fighter2_edge') or []]
    all_text = ' '.join([parsed['context'], parsed['what_to_watch']] + edges[0] + edges[1])

    # 1. numbers must come from the facts
    allowed = _allowed_numbers(facts)
    for n in re.findall(r'(?<![\w.])\d+(?:\.\d+)?', all_text):
        if n not in allowed:
            probs.append(f'number {n} is not in the facts')

    # 2. physical / age edges must match the numbers
    for i, (me, other) in enumerate(((sides[0], sides[1]), (sides[1], sides[0]))):
        text = ' '.join(edges[i]).lower()
        if edges[i] and not me.get('has_record'):
            probs.append(f"edges written for {me['name']}, who has no record")
        for rx, key, way, label in _PHYS:
            if re.search(rx, text):
                a, b = me.get(key), other.get(key)
                ok = a is not None and b is not None and ((a > b) if way == 'more' else (a < b))
                if not ok:
                    probs.append(f"{me['name']}'s {label} edge is not supported ({a} vs {b})")
        if re.search(r'\b(unbeaten|undefeated|perfect record)\b', text) and (me.get('losses') or 0) > 0:
            probs.append(f"{me['name']} is called unbeaten but has losses")

    if re.search(r'\b(unbeaten|undefeated|perfect record)\b', all_text, re.I) and not any(
            s.get('has_record') and (s.get('losses') or 0) == 0 for s in sides):
        probs.append('someone is called unbeaten but both have losses')

    # 3. rematch
    said_rematch = bool(re.search(_REMATCH_WORDS, all_text, re.I))
    if facts.get('previous_meetings') and not said_rematch:
        probs.append('it is a rematch but the preview does not say so')
    if not facts.get('previous_meetings') and re.search(r'\b(rematch|trilogy|run it back)\b', all_text, re.I):
        probs.append('calls it a rematch but they have not met')

    # 4. "former champion" for a sitting champion
    if re.search(r'\b(former|ex-|aging former|one-time)\s*champ', all_text, re.I) and any(s.get('current_champion') for s in sides):
        champs = [s['name'] for s in sides if s.get('current_champion')]
        others_former = [s for s in sides if not s.get('current_champion') and any(
            _won_title(x) for x in s.get('recent_fights') or [])]
        if not others_former:
            probs.append(f"calls someone a former champion, but {', '.join(champs)} is the current champion")
    return list(dict.fromkeys(probs))

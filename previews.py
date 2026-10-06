"""
Grounded fight previews: the AI writes from our stored Wikipedia facts, and
every preview is checked against those facts before it is shown.

Facts per fighter: tale of the tape (record, KO/sub/decision wins, age,
height, reach, stance, country) and the last five fights; plus any earlier
meetings between the two. The model is told to use only these facts. Then
check() rejects a preview that:
  - uses a number that is not in the facts (records, counts, ages, years),
  - states a reach / height / age gap that is not the real one,
  - claims a reach, height/size or youth edge the numbers do not support,
  - calls an older fight "recent" (only the last two count),
  - says something specific about a fighter we have no record for,
  - turns "N title wins" into "N title defenses",
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


# Bump when check() gets stricter: every stored preview is then written and checked again.
CHECK_VERSION = 3


def facts_hash(facts):
    return hashlib.sha1((str(CHECK_VERSION) + json.dumps(facts, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()[:16]


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
- Do not calculate gaps ("4-inch reach advantage"); give both values instead ("81 in vs 73 in").
- Call a fight "recent" only if it is one of that fighter's two latest fights in recent_fights.
- Say "title wins" or "title defenses" only exactly as the fight notes say.
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
# Built from real misses (see MISTAKES.md, 2026-10-06). Numbers are checked by
# what they claim, not by whether the digit appears somewhere in the facts
# (it usually does: "4" hides in a height, "28" in a date).

_MONTHS = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
_WORDS = {w: str(i) for i, w in enumerate(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen '
    'sixteen seventeen eighteen nineteen twenty'.split())}


def _num(x):
    """8.0 -> '8', 1.5 -> '1.5'"""
    return str(int(x)) if float(x).is_integer() else str(x)


def _digits(text):
    """'Four-inch' -> '4-inch', so spelled-out numbers are checked too."""
    return re.sub(r'\b(' + '|'.join(_WORDS) + r')\b', lambda m: _WORDS[m.group(1).lower()], text, flags=re.I)


def _without_dates(text):
    """'March 21, 2026' / '21 March 2026' -> '2026': a day of the month is not a claim."""
    text = re.sub(_MONTHS + r'\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(\d{4})', r'\1', text)
    return re.sub(r'\b\d{1,2}(?:st|nd|rd|th)?\s+' + _MONTHS + r'\.?\s+(\d{4})', r'\1', text)


def _clauses(parsed):
    """(owner index or None, clause text): each edge belongs to its fighter;
    context and what-to-watch sentences belong to nobody in particular."""
    out = []
    for i, k in enumerate(('fighter1_edge', 'fighter2_edge')):
        out += [(i, x) for x in parsed.get(k) or []]
    for k in ('context', 'what_to_watch'):
        out += [(None, x) for x in re.split(r'(?<=[.;!?])\s+', parsed.get(k) or '') if x.strip()]
    return out


def _surname(name):
    return (name or '').split()[-1] if name else ''


def _streak(fights):
    n = 0
    for f in fights or []:
        if f.get('result') != 'Win':
            break
        n += 1
    return n


def _fighter_numbers(f):
    """Numbers that describe this fighter, from structured fields only."""
    if not f.get('has_record'):
        return set()
    w, l, d = f.get('wins') or 0, f.get('losses') or 0, f.get('draws') or 0
    vals = [w, l, d, w + l + d, w + l, f.get('ko_wins'), f.get('sub_wins'), f.get('dec_wins'),
            (f.get('ko_wins') or 0) + (f.get('sub_wins') or 0), f.get('age'), f.get('height_cm'),
            f.get('reach_in'), _streak(f.get('recent_fights')), len(f.get('recent_fights') or [])]
    nums = {_num(v) for v in vals if v is not None}
    for x in ('height', 'reach'):
        nums |= set(re.findall(r'\d+(?:\.\d+)?', str(f.get(x) or '')))
    for fight in f.get('recent_fights') or []:
        nums |= set(re.findall(r'\d+', str(fight.get('round') or '')))
        nums |= set(re.findall(r'\b\d{4}\b', str(fight.get('date') or '')))
        for t in (fight.get('notes'), fight.get('event'), fight.get('method')):
            nums |= set(re.findall(r'\d+', str(t or '')))
    return nums


def _allowed_numbers(facts):
    nums = _fighter_numbers(facts['fighter1']) | _fighter_numbers(facts['fighter2'])
    for m in facts.get('previous_meetings') or []:
        nums |= set(re.findall(r'\d+', f"{m.get('round') or ''} {m.get('notes') or ''}"))
        nums |= set(re.findall(r'\b\d{4}\b', str(m.get('date') or '')))
    for y in [n for n in nums if len(n) == 4 and n.startswith('20')]:
        nums.add(y[2:])                                     # "2023–24"
    a, b = facts['fighter1'], facts['fighter2']
    for key in ('age', 'reach_in', 'height_cm'):            # stated differences
        if a.get(key) is not None and b.get(key) is not None:
            nums.add(_num(abs(a[key] - b[key])))
    if a.get('height_cm') is not None and b.get('height_cm') is not None:
        inches = abs(a['height_cm'] - b['height_cm']) / 2.54  # the same gap in inches
        nums |= {str(int(inches)), str(round(inches))}
    return nums


_PHYS = [   # (words, field, the owner should have 'more' or 'less' of it; 'disadvantage'/'shorter' flips it)
    (r'\breach\b', 'reach_in', 'more', 'reach'),
    (r'\b(taller|height|size|bigger|larger|shorter|smaller)\b', 'height_cm', 'more', 'height/size'),
    (r'\b(young|youth|younger|youthful)\b', 'age', 'less', 'age'),
    (r'\b(older)\b', 'age', 'more', 'age'),
]


def _owner(clause, sides, default):
    """Whose claim is it: the edge owner, or the one fighter named possessively ("Gane's reach")."""
    if default is not None:
        return default
    hits = [i for i, s in enumerate(sides) if re.search(r'\b' + re.escape(_surname(s['name'])) + r"[’']s\b", clause)]
    return hits[0] if len(hits) == 1 else None


def check(parsed, facts):
    """Problems with a preview, as plain sentences. Empty list = publishable."""
    if not parsed or not parsed.get('context') or not parsed.get('what_to_watch'):
        return ['missing context or what to watch']
    probs = []
    sides = [facts['fighter1'], facts['fighter2']]
    clauses = [(i, _without_dates(_digits(c))) for i, c in _clauses(parsed)]
    all_text = ' '.join(c for _, c in clauses)
    allowed = _allowed_numbers(facts)

    for i, side in enumerate(sides):
        if (parsed.get(('fighter1_edge', 'fighter2_edge')[i]) or []) and not side.get('has_record'):
            probs.append(f"edges written for {side['name']}, who has no record")

    for default, c in clauses:
        low = c.lower()
        who = _owner(c, sides, default)
        me = sides[who] if who is not None else None
        other = sides[1 - who] if who is not None else None

        # 1. every number is a fact, a real difference, or a round number
        rounds = {m for m in re.findall(r'\b(\d+)(?:\s|-)rounds?\b', c, re.I) + re.findall(r'\bround\s+(\d+)\b', c, re.I)
                  if 1 <= int(m) <= 12}
        for n in re.findall(r'(?<![\w.])\d+(?:\.\d+)?', c):
            if n not in allowed and n not in rounds:
                probs.append(f'number {n} is not in the facts')

        # 2. a stated difference must be the real one ("4-inch reach advantage" when it is 8).
        #    Each number belongs to the words right around it ("taller by 2 inches", "one-inch reach").
        a_, b_ = sides[0], sides[1]
        for m in re.finditer(r'(\d+(?:\.\d+)?)[\s-]*(inch(?:es)?|in\b|cm|years?)', c, re.I):
            n, u = m.group(1), m.group(2).lower()
            after, before = c[m.end():m.end() + 22].lower(), c[max(0, m.start() - 22):m.start()].lower()
            if u.startswith('year'):
                if re.match(r'\s*(younger|older)', after):
                    real = abs(a_['age'] - b_['age']) if a_.get('age') is not None and b_.get('age') is not None else None
                    if real is None or float(n) != real:
                        probs.append(f'{n} years age gap is wrong (real gap {real})')
                continue
            if 'reach' in after and not re.search(r'tall|height|short', before):
                if n in {_num(v) for v in (a_.get('reach_in'), b_.get('reach_in')) if v is not None}:
                    continue                                   # "81 inches" — a reach, not a gap
                real = abs(a_['reach_in'] - b_['reach_in']) if a_.get('reach_in') is not None and b_.get('reach_in') is not None else None
                if real is None or float(n) != real:
                    probs.append(f'{n}-inch reach difference is wrong (real {real})')
            elif re.search(r'tall|height|short', before + ' ' + after):
                ha, hb = a_.get('height_cm'), b_.get('height_cm')
                if ha is None or hb is None:
                    probs.append('height difference stated without both heights')
                    continue
                if n in {_num(v) for v in (ha, hb)}:
                    continue
                real_cm = abs(ha - hb)
                ok = (abs(float(n) - real_cm) <= 1) if u == 'cm' else (abs(float(n) - real_cm / 2.54) <= 1)
                if not ok:
                    probs.append(f'{n} {u} height difference is wrong (real {real_cm} cm)')

        # 3. physical / age edges must match the numbers
        if me is not None:
            for rx, key, way, label in _PHYS:
                if re.search(rx, low) and (default is not None or re.search(r'advantage|edge|taller|younger|older|longer|shorter', low)):
                    if re.search(r'\b(identical|same|equal|even)\b', low):
                        continue
                    if re.search(r'\b(disadvantage|shorter|smaller)\b', low) and key != 'age':
                        way = 'less' if way == 'more' else 'more'
                    a, b = me.get(key), other.get(key)
                    ok = a is not None and b is not None and ((a > b) if way == 'more' else (a < b))
                    if not ok:
                        probs.append(f"{me['name']}'s {label} edge is not supported ({a} vs {b})")
            if re.search(r'\b(unbeaten|undefeated|perfect record|perfect \d+-0)\b', low) and (me.get('losses') or 0) > 0:
                probs.append(f"{me['name']} is called unbeaten but has losses")

        # 4. nothing specific about a fighter we have no record for
        for s in sides:
            if not s.get('has_record') and re.search(r'\b' + re.escape(_surname(s['name'])) + r"[’']s\b(?![^.]*\b(record|information|data)\b[^.]*\b(unavailable|not available|unknown)\b)", c):
                probs.append(f"claims about {s['name']}, who has no record")

        # 5. "recently beat X" must be one of the last two fights
        if re.search(r'\b(recent|recently|latest|last)\b', low):
            for idx, s in enumerate(sides):
                for k, fight in enumerate(s.get('recent_fights') or []):
                    opp = fight.get('opponent') or ''
                    if opp and _surname(opp) and re.search(r'\b' + re.escape(_surname(opp)) + r'\b', c) and k >= 2:
                        probs.append(f"fight against {opp} ({fight.get('date')}) is called recent, but {s['name']} has fought since")

        # 6. "N title defenses" must be what the notes say (not N title wins)
        notes = ' '.join(x.get('notes') or '' for s_ in sides for x in s_.get('recent_fights') or [])
        for n in re.findall(r'\b(\d+)\s+(?:(?:[A-Z]{2,4}|title|world|successful|straight|consecutive|\w*weight|championship)\s+){0,3}defen[cs]es\b', c, re.I):
            if not re.search(r'defen[cs]e[^.]*\b' + n + r'\b|\b' + n + r'\b[^.]*defen[cs]e', notes, re.I):
                probs.append(f'{n} title defenses is not in the record notes')

    if re.search(r'\b(unbeaten|undefeated|perfect record)\b', all_text, re.I) and not any(
            s.get('has_record') and (s.get('losses') or 0) == 0 for s in sides):
        probs.append('someone is called unbeaten but both have losses')

    # 7. rematch
    said_rematch = bool(re.search(_REMATCH_WORDS, all_text, re.I))
    if facts.get('previous_meetings') and not said_rematch:
        probs.append('it is a rematch but the preview does not say so')
    if not facts.get('previous_meetings') and re.search(r'\b(rematch|trilogy|run it back)\b', all_text, re.I):
        probs.append('calls it a rematch but they have not met')

    # 8. "former champion" for a sitting champion
    if re.search(r'\b(former|ex-|aging former|one-time)\s*champ', all_text, re.I) and any(s.get('current_champion') for s in sides):
        champs = [s['name'] for s in sides if s.get('current_champion')]
        others_former = [s for s in sides if not s.get('current_champion') and any(
            _won_title(x) for x in s.get('recent_fights') or [])]
        if not others_former:
            probs.append(f"calls someone a former champion, but {', '.join(champs)} is the current champion")
    return list(dict.fromkeys(probs))

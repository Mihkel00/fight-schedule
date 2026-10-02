"""
Named checks that fight data must satisfy. Each check returns
(name, ok, detail). The same list runs in the tests against saved fixtures,
read-only over the current cache (debug API part=check), and — from step 3 of
the robustness plan — on every scrape before data is promoted.

Two levels:
    row_checks(fight)     -> problems with one fight dict (empty list = fine)
    model_checks(fights)  -> problems with the set as a whole
"""

import re
from collections import Counter, defaultdict

PLACEHOLDERS = {'', 'tba', 'tbd', 'tbc', 'opponent tba', 'to be announced'}
SPORTS = {'UFC', 'Boxing'}
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_TIME = re.compile(r'^\d{2}:\d{2}$')


def is_placeholder(name):
    return (name or '').strip().lower() in PLACEHOLDERS


def _key(f):
    return (tuple(sorted([(f.get('fighter1') or '').lower(), (f.get('fighter2') or '').lower()])), f.get('date'))


# ---------------------------------------------------------------- rows

def row_checks(f):
    """Problems with one fight. A fight with any problem should not be served."""
    problems = []
    f1, f2 = f.get('fighter1') or '', f.get('fighter2') or ''
    if is_placeholder(f1):
        problems.append('fighter1 missing')
    if f1 and f2 and f1.strip().lower() == f2.strip().lower():
        problems.append('fighter1 equals fighter2')
    if not _DATE.match(f.get('date') or ''):
        problems.append(f"bad date {f.get('date')!r}")
    t = f.get('time')
    if t not in (None, 'TBA') and not _TIME.match(str(t)):
        problems.append(f"bad time {t!r}")
    if f.get('sport') not in SPORTS:
        problems.append(f"bad sport {f.get('sport')!r}")
    if f.get('sport') == 'UFC' and not f.get('event_name'):
        problems.append('UFC fight without event_name')
    return problems


# ---------------------------------------------------------------- model

def _ufc_events(fights):
    ev = defaultdict(list)
    for f in fights:
        if f.get('sport') == 'UFC' and f.get('event_name'):
            ev[f['event_name']].append(f)
    return ev


def _boxing_cards(fights):
    cards = defaultdict(list)
    for f in fights:
        if f.get('sport') == 'Boxing':
            cards[(f.get('venue') or 'TBA', f.get('date'))].append(f)
    return cards


def check_rows(fights):
    bad = [(f.get('fighter1'), f.get('fighter2'), p) for f in fights for p in row_checks(f)]
    return ('rows_valid', not bad, f'{len(bad)} row problems' + (f', e.g. {bad[:3]}' if bad else ''))


def check_no_duplicates(fights):
    dups = [k for k, n in Counter(_key(f) for f in fights).items() if n > 1]
    return ('no_duplicate_bouts', not dups, f'{len(dups)} matchups listed twice' + (f', e.g. {dups[:3]}' if dups else ''))


def check_one_main_event_per_ufc_event(fights):
    """After normalize_ufc_cards every event's bouts carry bout_order; exactly
    one must be 0. Events without bout_order (not yet normalized) are reported."""
    bad = []
    for name, fs in _ufc_events(fights).items():
        if not all('bout_order' in f for f in fs):
            bad.append(f'{name}: not normalized')
            continue
        n = sum(1 for f in fs if f.get('bout_order') == 0)
        if n != 1:
            bad.append(f'{name}: {n} bouts at order 0')
    return ('one_main_event_per_ufc_event', not bad, '; '.join(bad[:4]) or 'ok')


def check_one_main_event_per_boxing_card(fights):
    bad = []
    for (venue, d), fs in _boxing_cards(fights).items():
        n = sum(1 for f in fs if f.get('is_main_event'))
        if n != 1:
            bad.append(f'{venue} {d}: {n} main events')
    return ('one_main_event_per_boxing_card', not bad, '; '.join(bad[:4]) or 'ok')


def check_prelims_before_main(fights):
    """Within a UFC event, no prelim starts after the main card starts."""
    bad = []
    for name, fs in _ufc_events(fights).items():
        main = [f'{f["date"]} {f["time"]}' for f in fs if f.get('card_type') == 'Main Card' and f.get('time') and f['time'] != 'TBA']
        pre = [f'{f["date"]} {f["time"]}' for f in fs if f.get('card_type') == 'Prelims' and f.get('time') and f['time'] != 'TBA']
        if main and pre and max(pre) > min(main):
            bad.append(f'{name}: prelim at {max(pre)} after main card at {min(main)}')
    return ('prelims_before_main_card', not bad, '; '.join(bad[:4]) or 'ok')


def check_main_event_named_in_title(fights):
    """Numbered UFC events are named after the main event ('UFC 332: Silva vs.
    Wang'); the bout at order 0 should be that pair. Reported, not fatal:
    ESPN titles sometimes lag a change of main event."""
    from app import _name_in_text  # local import: app imports this module
    bad = []
    for name, fs in _ufc_events(fights).items():
        if ':' not in name or not all('bout_order' in f for f in fs):
            continue
        head = next((f for f in fs if f.get('bout_order') == 0), None)
        title = name.split(':', 1)[1].lower()
        if head and not (_name_in_text(head['fighter1'], title) and _name_in_text(head['fighter2'], title)):
            bad.append(f"{name}: main event is {head['fighter1']} vs {head['fighter2']}")
    return ('ufc_main_event_matches_title', not bad, '; '.join(bad[:4]) or 'ok')


def check_counts(fights, floor_ufc=10, floor_boxing=5):
    n = Counter(f.get('sport') for f in fights)
    ok = n['UFC'] >= floor_ufc and n['Boxing'] >= floor_boxing
    return ('counts_above_floor', ok, f"UFC {n['UFC']} (floor {floor_ufc}), Boxing {n['Boxing']} (floor {floor_boxing})")


MODEL_CHECKS = [check_rows, check_no_duplicates, check_one_main_event_per_ufc_event,
                check_one_main_event_per_boxing_card, check_prelims_before_main,
                check_main_event_named_in_title, check_counts]


def model_checks(fights):
    """Run every model check. Returns a list of {'name', 'ok', 'detail'}."""
    out = []
    for fn in MODEL_CHECKS:
        try:
            name, ok, detail = fn(fights)
        except Exception as e:
            name, ok, detail = fn.__name__, False, f'check crashed: {e}'
        out.append({'name': name, 'ok': ok, 'detail': detail})
    return out


def failures(fights):
    return [c for c in model_checks(fights) if not c['ok']]

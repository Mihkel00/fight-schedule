"""
Fighter profiles from Wikipedia (tale of the tape, results) and the
background job that refreshes them; enrich_fights() attaches them to fights.

Moved out of app.py unchanged (2026-10); app.py imports every module so
the routes register on the one Flask app.
"""
import image_pipeline as _images
import json
import locks as _locks
import os
import runs as _runs
import threading
import time
from datetime import date, datetime, timedelta
from scrapers import fighter_profiles as _wiki
from core import data_path, logger
import fight_store
import seo


PROFILES_FILE = data_path('fighter_profiles.json')


PROFILE_TTL_HOURS = 24 * 7      # re-check a known fighter weekly


RESULT_TTL_HOURS = 6            # ...but every 6h while one of their fights is recent


NEGATIVE_TTL_HOURS = 24 * 7     # retry unknown names weekly


PROFILE_JOB_MIN_INTERVAL_S = 10 * 60


_profiles_lock = threading.Lock()


_profiles_mem = {'mtime': None, 'data': {}}


_profile_job_state = {'last_start': 0.0, 'running': False}


def _profile_key(name):
    return _wiki._norm(name)


def load_profiles():
    """Profiles dict keyed by normalized name, cached in memory by file mtime."""
    try:
        mtime = os.path.getmtime(PROFILES_FILE)
    except OSError:
        return {}
    if _profiles_mem['mtime'] != mtime:
        try:
            with open(PROFILES_FILE) as f:
                _profiles_mem['data'] = json.load(f)
            _profiles_mem['mtime'] = mtime
        except Exception as e:
            logger.error(f"Error loading profiles: {e}")
            return _profiles_mem['data'] or {}
    return _profiles_mem['data']


def save_profiles(data):
    _runs.write_json_atomic(PROFILES_FILE, data)


def _hours_since(ts):
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 3600
    except Exception:
        return 1e9


def _profile_work_list(fights, profiles):
    """Names to (re)fetch, most useful first: recent results, then soonest upcoming."""
    today = date.today()
    today_iso, recent_iso = today.isoformat(), (today - timedelta(days=4)).isoformat()
    wanted = {}
    for f in fights:
        d = f.get('date', '')
        for key in ('fighter1', 'fighter2'):
            name = f.get(key, '')
            if not name or name.upper() == 'TBA':
                continue
            k = _profile_key(name)
            entry = profiles.get(k)
            if recent_iso <= d < today_iso:
                # results pending: refresh often, and only for fighters with an article
                if entry and entry.get('title') and _hours_since(entry.get('fetched_at', '')) < RESULT_TTL_HOURS:
                    continue
                if entry and not entry.get('title') and _hours_since(entry.get('fetched_at', '')) < NEGATIVE_TTL_HOURS:
                    continue
                prio = (0, d)
            else:
                if entry and _hours_since(entry.get('fetched_at', '')) < (PROFILE_TTL_HOURS if entry.get('title') else NEGATIVE_TTL_HOURS):
                    continue
                prio = (1, d)
            if k not in wanted or prio < wanted[k][0]:
                wanted[k] = (prio, name, f.get('sport', 'Boxing'))
    return [(name, sport) for _, name, sport in sorted(wanted.values(), key=lambda x: x[0])]


def refresh_profiles(fights, max_fetch=150):
    """Background job: fetch/refresh Wikipedia profiles for fighters in the schedule."""
    if _profile_job_state['running']:
        return
    _profile_job_state['running'] = True
    _profile_job_state['last_start'] = time.time()
    lock = _locks.job_lock('profiles')
    if not lock.__enter__():
        lock.__exit__(None, None, None)
        _profile_job_state['running'] = False
        logger.info("Profile job already running in the other worker, skipping")
        return
    try:
        profiles = dict(load_profiles())
        work = _profile_work_list(fights, profiles)[:max_fetch]
        logger.info(f"Profile job: {len(work)} fighters to fetch")
        fetched = 0
        for name, sport in work:
            k = _profile_key(name)
            existing = profiles.get(k) or {}
            title = existing.get('title') or _wiki.resolve_title(name, sport)
            profile = _wiki.fetch_profile(title, sport) if title else None
            if title and profile is None and existing.get('profile'):
                profile = existing['profile']   # transient failure: keep what we had
            profiles[k] = {
                'name': name, 'sport': sport, 'title': title if profile else None,
                'profile': profile, 'fetched_at': datetime.now().isoformat(),
            }
            fetched += 1
            if fetched % 10 == 0:
                with _profiles_lock:
                    save_profiles(profiles)
            time.sleep(0.3)
        with _profiles_lock:
            save_profiles(profiles)
        logger.info(f"Profile job done: {fetched} fetched, {sum(1 for p in profiles.values() if p.get('title'))} with articles")
        if fetched:
            seo.sync_page_versions(fight_store.load_cache(max_age_hours=24 * 365) or [], reason='profiles')
        _images.autofill_new_fighters()
    except Exception as e:
        logger.error(f"Profile job failed: {e}", exc_info=True)
    finally:
        lock.__exit__(None, None, None)
        _profile_job_state['running'] = False


def _maybe_start_profile_job(fights):
    """Start a background profile refresh if there is work and none ran recently."""
    if _profile_job_state['running'] or time.time() - _profile_job_state['last_start'] < PROFILE_JOB_MIN_INTERVAL_S:
        return
    if _profile_work_list(fights, load_profiles()):
        threading.Thread(target=refresh_profiles, args=(fights,), daemon=True).start()


def _tape(profile_entry):
    """Slim tale-of-the-tape dict for templates, or None."""
    p = (profile_entry or {}).get('profile')
    if not p or not p.get('has_tape') and not p.get('record'):
        return None
    rec = p.get('record') or {}
    wins, losses, draws, total = rec.get('wins'), rec.get('losses'), rec.get('draws'), rec.get('total')
    if wins is not None and losses is None and total is not None:
        losses = max(0, total - wins - (draws or 0) - (rec.get('no_contests') or 0))
    record = None
    if wins is not None and losses is not None:
        record = f"{wins}-{losses}" + (f"-{draws}" if draws else '')
    # Prefer the birthplace country so the row reads "Brazil / South Africa" rather
    # than a mix of adjectives ("Filipino") and countries.
    nationality = None
    if p.get('birthplace'):
        nationality = p['birthplace'].split(',')[-1].strip()
        nationality = {'U.S.': 'United States', 'US': 'United States', 'USA': 'United States', 'UK': 'United Kingdom'}.get(nationality, nationality)
    if not nationality:
        nationality = p.get('nationality')
    return {
        'record': record, 'wins': wins, 'losses': losses, 'draws': draws,
        'ko_wins': rec.get('ko_wins'), 'sub_wins': rec.get('sub_wins'), 'dec_wins': rec.get('dec_wins'),
        'age': p.get('age'), 'height': p.get('height_text'), 'height_cm': p.get('height_cm'),
        'reach': p.get('reach_text'), 'reach_in': p.get('reach_in'),
        'stance': p.get('stance'), 'nationality': nationality, 'nickname': p.get('nickname'),
        'height_display': _height_display(p.get('height_cm')),
        'reach_display': _reach_display(p.get('reach_in'), p.get('reach_cm')),
        'url': p.get('url'),
    }


def _height_display(cm):
    if not cm:
        return None
    total_in = cm / 2.54
    ft, inch = int(total_in // 12), int(round(total_in % 12))
    if inch == 12:
        ft, inch = ft + 1, 0
    return f"{ft}'{inch}\" ({cm} cm)"


def _reach_display(inches, cm):
    if not inches and not cm:
        return None
    if inches and not cm:
        cm = int(round(inches * 2.54))
    if cm and not inches:
        inches = round(cm / 2.54)
    inches_s = str(int(inches)) if float(inches).is_integer() else f"{inches:g}"
    return f'{inches_s}" ({cm} cm)'


def _result_for(fight, profiles):
    """Winner/method/round for a completed fight, from either fighter's record table."""
    f1, f2, d = fight.get('fighter1', ''), fight.get('fighter2', ''), fight.get('date', '')
    for me, them in ((f1, f2), (f2, f1)):
        entry = profiles.get(_profile_key(me))
        row = _wiki.find_result((entry or {}).get('profile'), them, d) if entry else None
        if not row:
            continue
        res = (row.get('result') or '').lower()
        if res.startswith('win'):
            winner, loser, outcome = me, them, 'win'
        elif res.startswith('loss'):
            winner, loser, outcome = them, me, 'win'
        elif res.startswith('draw'):
            winner, loser, outcome = None, None, 'draw'
        elif 'nc' in res or 'no contest' in res:
            winner, loser, outcome = None, None, 'nc'
        else:
            continue
        return {
            'outcome': outcome, 'winner': winner, 'loser': loser,
            'method': row.get('method'), 'round': row.get('round'), 'time': row.get('time'),
            'notes': row.get('notes'), 'source_url': (entry.get('profile') or {}).get('url'),
        }
    return None


def enrich_fights(fights):
    """Attach fighter1_tape / fighter2_tape, is_past, and result (for past fights)."""
    profiles = load_profiles()
    today_iso = date.today().isoformat()
    grace_iso = (date.today() - timedelta(days=fight_store.RESULT_GRACE_DAYS)).isoformat()
    for f in fights:
        for k in ('fighter1', 'fighter2'):
            if _images.is_rejected(f.get(k, '')):
                f[f'{k}_image'] = None
            else:
                f[f'{k}_image'] = _images.image_for(f.get(k, '')) or f.get(f'{k}_image')
        f['fighter1_tape'] = _tape(profiles.get(_profile_key(f.get('fighter1', ''))))
        f['fighter2_tape'] = _tape(profiles.get(_profile_key(f.get('fighter2', ''))))
        f['is_past'] = f.get('date', '') < today_iso
        f['result'] = _result_for(f, profiles) if f['is_past'] else None
        # Only call it "pending" while a result could realistically still land:
        # inside the grace window, with at least one fighter whose Wikipedia
        # record we can read.
        f['result_pending'] = bool(
            f['is_past'] and not f['result'] and f.get('date', '') >= grace_iso
            and any((profiles.get(_profile_key(f.get(k, ''))) or {}).get('title')
                    for k in ('fighter1', 'fighter2'))
        )
    return fights

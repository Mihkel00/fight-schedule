"""
Grounded AI previews: storage, the model call, background generation
(facts and checks live in previews.py).

Moved out of app.py unchanged (2026-10); app.py imports every module so
the routes register on the one Flask app.
"""
import json
import locks as _locks
import os
import previews as _previews
import requests
import runs as _runs
import threading
from datetime import date, datetime
from core import data_path, logger
import profile_store


# Your Premium API Key
# Anthropic API Key for fight previews
# ⚠️ ADD YOUR NEW API KEY HERE (after creating it in console.anthropic.com)
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')  # Will load from environment variable


def load_previews():
    """Load cached fight previews from persistent data directory"""
    try:
        with open(data_path('fight_previews.json'), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load previews: {e}")
        return {}


def save_preview(preview_id, preview_data):
    """Save a fight preview to the cache file (atomic, safe across workers)."""
    try:
        with _locks.job_lock('previews', wait_seconds=15):
            previews = load_previews()
            previews[preview_id] = preview_data
            _runs.write_json_atomic(data_path('fight_previews.json'), previews)
        logger.info(f"Saved preview: {preview_id}")
    except Exception as e:
        logger.error(f"Failed to save preview: {e}")


PREVIEW_MODEL = 'claude-haiku-4-5-20251001'


_preview_jobs = set()


_preview_jobs_lock = threading.Lock()


def _call_preview_model(prompt):
    """One request to the model; the reply text, or None on any failure."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json", "x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01"},
            json={"model": PREVIEW_MODEL, "max_tokens": 600, "messages": [{"role": "user", "content": prompt}]},
            timeout=30)
        if r.status_code != 200:
            logger.error(f"Preview API request failed: {r.status_code}")
            return None
        return r.json()['content'][0]['text']
    except Exception as e:
        logger.error(f"Preview generation error: {e}")
        return None


def _make_grounded_preview(preview_id, facts, sources, fighter1, fighter2):
    """Write a preview from the facts, check it, retry once with the problems
    listed, and store the outcome (shown only if it passed)."""
    problems, text, parsed = None, None, None
    for _ in range(2):
        text = _call_preview_model(_previews.build_prompt(facts, problems))
        if text is None:
            return None                     # API down / no key: store nothing, try again later
        parsed = _previews.parse(text)
        problems = _previews.check(parsed, facts)
        if not problems:
            break
    entry = {'fighter1': fighter1, 'fighter2': fighter2, 'text': text, 'parsed': parsed,
             'generated_at': datetime.now().isoformat(), 'grounded': True,
             'facts_hash': _previews.facts_hash(facts), 'ok': not problems, 'problems': problems or [],
             'sources': sources, 'model': PREVIEW_MODEL, 'manual_override': False}
    if problems:
        logger.warning(f"Preview {preview_id} rejected: {problems}")
    save_preview(preview_id, entry)
    return entry


def boxing_preview_id(fighter1, fighter2, date_iso):
    """Cache key of a boxing preview (names sorted, so either order matches)."""
    a, b = sorted([fighter1, fighter2])
    slug = lambda n: n.lower().replace(' ', '-').replace("'", '')
    return f"boxing_{slug(a)}_{slug(b)}_{date_iso}"


def get_or_generate_preview(preview_id, fighter1, fighter2, sport, is_title, weight_class=None, wait=False, fight_date=None):
    """The checked preview for a fight, or None. Previews are written only from
    our stored Wikipedia facts (see previews.py) and regenerated when those facts
    change. Pages never wait on the model: a missing preview is made in the
    background (wait=True makes it now, for generate_previews.py)."""
    entry = load_previews().get(preview_id)
    if fight_date and fight_date < date.today().isoformat():
        # A finished fight keeps the preview it had; it is never rewritten with hindsight
        return entry if entry and entry.get('grounded') and entry.get('ok') else None
    facts, sources = _previews.build_facts(fighter1, fighter2, sport, weight_class, is_title,
                                           profile_store.load_profiles(), profile_store._tape, profile_store._profile_key, before=fight_date)
    if not _previews.has_any_record(facts):
        return None                         # nothing to ground it on: no preview
    if entry and entry.get('grounded') and entry.get('facts_hash') == _previews.facts_hash(facts):
        return entry if entry.get('ok') else None
    if not ANTHROPIC_API_KEY:
        return None
    if wait:
        entry = _make_grounded_preview(preview_id, facts, sources, fighter1, fighter2)
        return entry if entry and entry.get('ok') else None
    with _preview_jobs_lock:
        if preview_id in _preview_jobs:
            return None
        _preview_jobs.add(preview_id)

    def run():
        try:
            _make_grounded_preview(preview_id, facts, sources, fighter1, fighter2)
        finally:
            with _preview_jobs_lock:
                _preview_jobs.discard(preview_id)
    threading.Thread(target=run, daemon=True).start()
    return None

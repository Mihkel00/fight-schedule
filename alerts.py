"""
Outage alerts by email (Resend). Disabled unless RESEND_API_KEY and ALERT_EMAIL
are set. Tracks consecutive failures per source so you get one email when a
source has failed twice in a row, and one when it recovers.
"""

import json
import os
import threading
from datetime import datetime

import requests

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
STATE_FILE = os.path.join(DATA_DIR, 'alert_state.json')
FAILURES_BEFORE_ALERT = 2
_lock = threading.Lock()


def enabled():
    return bool(os.environ.get('RESEND_API_KEY') and os.environ.get('ALERT_EMAIL'))


def send(subject, body):
    """Send one email. Returns True on success; never raises."""
    if not enabled():
        return False
    try:
        r = requests.post('https://api.resend.com/emails',
                          headers={'Authorization': f"Bearer {os.environ['RESEND_API_KEY']}"},
                          json={'from': os.environ.get('ALERT_FROM', 'Fight Schedule <onboarding@resend.dev>'),
                                'to': [os.environ['ALERT_EMAIL']], 'subject': subject, 'text': body},
                          timeout=10)
        return r.status_code < 300
    except Exception:
        return False


def _load():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)


def report(source, ok, detail=''):
    """Record one scrape outcome for a source; email on the 2nd consecutive
    failure and again on recovery. Returns 'alerted' | 'recovered' | None."""
    with _lock:
        state = _load()
        s = state.get(source, {'failures': 0, 'notified': False})
        now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
        outcome = None
        if ok:
            if s.get('notified'):
                send(f'[fightschedule.live] {source} scraper recovered',
                     f'The {source} scraper is returning data again ({detail}) as of {now}.')
                outcome = 'recovered'
            s = {'failures': 0, 'notified': False, 'last_ok': now}
        else:
            s['failures'] = s.get('failures', 0) + 1
            s['last_failure'] = now
            if s['failures'] >= FAILURES_BEFORE_ALERT and not s.get('notified'):
                if send(f'[fightschedule.live] {source} scraper is failing',
                        f'The {source} scraper has returned no usable data {s["failures"]} runs in a row '
                        f'(last: {now}). Detail: {detail}\n\nThe site keeps serving the last good {source} data '
                        f'meanwhile, but it will go stale.\n\nDiagnose with the debug API: part=scrape_test, '
                        f'part=boxing_probe, part=scrape_log.'):
                    s['notified'] = True
                    outcome = 'alerted'
        state[source] = s
        _save(state)
        return outcome

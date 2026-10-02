"""
Raw snapshots, run records and health for the data sources.

Every page a source sends is saved exactly as it arrived (gzipped, with a
sidecar describing the request) before anything parses it, even when the
request failed. Every scrape attempt writes a run record per source saying
what happened: which layout parsed, how many rows, which checks passed, and a
status. The run records, not the cache timestamp, are what "when did we last
read this source" means. /health and the debug API read them.

Layout under DATA_DIR:
    snapshots/<source>/<fetched_at>-<label>.<ext>.gz   raw body
    snapshots/<source>/<fetched_at>-<label>.json       sidecar {url, status, error, bytes, ...}
    runs/<source>/<fetched_at>.json                    one record per attempt
    runs/<source>/latest.json                          copy of the newest record

Statuses: ok | partial | failed | manual
    ok       parsed, passed the checks, promoted to the cache
    partial  some of the source was read (e.g. 4 of 6 ESPN months); what was
             read is used, the rest is carried forward
    failed   nothing usable: HTTP error, unknown layout, or below the floor
    manual   data entered through the debug API backfill
"""

import glob
import gzip
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
SNAPSHOTS_PER_SOURCE = 80      # ~285 KB gz for a boxing page; ESPN months ~100 KB each
RUNS_PER_SOURCE = 200
SCRAPE_INTERVAL_HOURS = 6      # mirrors CACHE_DURATION in app.py
STALE_AFTER_HOURS = 30         # no ok run for this long -> unhealthy (4 scrape windows + slack)

_write_lock = threading.Lock()


def _now_iso():
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _stamp():
    # microseconds: several snapshots/runs can be written within one second
    return datetime.utcnow().strftime('%Y%m%dT%H%M%S.%fZ')


def _safe(label):
    return re.sub(r'[^A-Za-z0-9._-]+', '-', str(label))[:60] or 'x'


def write_json_atomic(path, data, **dump_kwargs):
    """Write JSON so a reader (the other gunicorn worker) never sees a half
    file: write to a temp file in the same directory, fsync, then rename."""
    d = os.path.dirname(path) or '.'
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, **dump_kwargs)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _prune(directory, pattern, keep):
    files = sorted(glob.glob(os.path.join(directory, pattern)))
    for old in files[:-keep] if keep else files:
        try:
            os.unlink(old)
        except OSError:
            pass


# ---------------------------------------------------------------- snapshots

def save_snapshot(source, label, url, status, body, error=None, ext='html', extra=None):
    """Store what a source sent (body bytes, possibly empty) plus a sidecar.
    Never raises: a snapshot failure must not stop a scrape. Returns the
    sidecar dict (with 'file' = relative path) or None."""
    try:
        d = os.path.join(DATA_DIR, 'snapshots', _safe(source))
        os.makedirs(d, exist_ok=True)
        base = f"{_stamp()}-{_safe(label)}"
        body = body or b''
        if isinstance(body, str):
            body = body.encode('utf-8', 'replace')
        data_file = os.path.join(d, f'{base}.{ext}.gz')
        with gzip.open(data_file, 'wb') as fh:
            fh.write(body)
        side = {
            'source': source, 'label': label, 'url': url, 'status': status, 'error': error,
            'bytes': len(body), 'fetched_at': _now_iso(),
            'file': os.path.relpath(data_file, DATA_DIR),
        }
        if extra:
            side.update(extra)
        write_json_atomic(os.path.join(d, f'{base}.json'), side)
        with _write_lock:
            _prune(d, '*.json', SNAPSHOTS_PER_SOURCE)
            _prune(d, '*.gz', SNAPSHOTS_PER_SOURCE)
        return side
    except Exception:
        return None


def list_snapshots(source, limit=20):
    d = os.path.join(DATA_DIR, 'snapshots', _safe(source))
    out = []
    for p in sorted(glob.glob(os.path.join(d, '*.json')))[-limit:]:
        try:
            with open(p, encoding='utf-8') as fh:
                out.append(json.load(fh))
        except Exception:
            continue
    return out


def read_snapshot(rel_file):
    """Raw bytes of a stored snapshot, by the 'file' value from its sidecar."""
    path = os.path.normpath(os.path.join(DATA_DIR, rel_file))
    if not path.startswith(os.path.normpath(os.path.join(DATA_DIR, 'snapshots'))):
        raise ValueError('not a snapshot path')
    with gzip.open(path, 'rb') as fh:
        return fh.read()


# ---------------------------------------------------------------- runs

def write_run(source, status, outcome, counts=None, checks=None, layout=None, snapshots=None,
              diagnostics=None, fetched_at=None, duration_s=None, note=None):
    """Record one scrape attempt for a source. Returns the record."""
    rec = {
        'source': source, 'status': status, 'outcome': outcome,
        'fetched_at': fetched_at or _now_iso(), 'recorded_at': _now_iso(),
        'duration_s': duration_s, 'layout': layout,
        'counts': counts or {}, 'checks': checks or [], 'snapshots': snapshots or [],
        'diagnostics': diagnostics or {}, 'note': note,
    }
    try:
        d = os.path.join(DATA_DIR, 'runs', _safe(source))
        os.makedirs(d, exist_ok=True)
        write_json_atomic(os.path.join(d, f'{_stamp()}.json'), rec)
        write_json_atomic(os.path.join(d, 'latest.json'), rec)
        with _write_lock:
            _prune(d, '2*.json', RUNS_PER_SOURCE)
    except Exception:
        pass
    return rec


def list_runs(source, limit=30):
    d = os.path.join(DATA_DIR, 'runs', _safe(source))
    out = []
    for p in sorted(glob.glob(os.path.join(d, '2*.json')))[-limit:]:
        try:
            with open(p, encoding='utf-8') as fh:
                out.append(json.load(fh))
        except Exception:
            continue
    return out


def last_run(source):
    p = os.path.join(DATA_DIR, 'runs', _safe(source), 'latest.json')
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None


def last_ok_run(source):
    for r in reversed(list_runs(source, limit=RUNS_PER_SOURCE)):
        if r.get('status') in ('ok', 'partial', 'manual'):
            return r
    return None


# ---------------------------------------------------------------- health

def _parse_iso(s):
    try:
        return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')
    except Exception:
        return None


def source_health(source, now=None):
    now = now or datetime.utcnow()
    last = last_run(source)
    ok = last_ok_run(source)
    ok_at = _parse_iso(ok['fetched_at']) if ok else None
    hours_since_ok = round((now - ok_at).total_seconds() / 3600, 1) if ok_at else None
    problems = []
    if last is None:
        problems.append('no run recorded yet')
    elif last.get('status') == 'failed':
        problems.append(f"last run failed: {last.get('outcome')}" + (f" — {last.get('note')}" if last.get('note') else ''))
    if ok_at is None:
        problems.append('no successful run recorded')
    elif hours_since_ok > STALE_AFTER_HOURS:
        problems.append(f'last successful run {hours_since_ok} h ago')
    next_due = (ok_at + timedelta(hours=SCRAPE_INTERVAL_HOURS)).strftime('%Y-%m-%dT%H:%M:%SZ') if ok_at else None
    return {
        'source': source,
        'healthy': not problems,
        'problems': problems,
        'last_run': {k: last.get(k) for k in ('fetched_at', 'status', 'outcome', 'layout', 'counts', 'note')} if last else None,
        'failed_checks': [c for c in (last or {}).get('checks', []) if not c.get('ok')],
        'last_ok_at': ok['fetched_at'] if ok else None,
        'hours_since_ok': hours_since_ok,
        'next_scrape_due': next_due,
    }


def health(sources=('UFC', 'Boxing'), extra=None):
    """Overall health view. 'healthy' is false if any source has a problem."""
    per = [source_health(s) for s in sources]
    out = {
        'healthy': all(p['healthy'] for p in per),
        'checked_at': _now_iso(),
        'sources': per,
    }
    if extra:
        out.update(extra)
    return out

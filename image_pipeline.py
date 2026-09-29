"""
Fighter image pipeline: identity-anchored sourcing, quality gate, smart crop,
provenance, and manual overrides.

Sources (both anchored to a known identity, never a loose search):
  - ESPN athlete headshot, only when ESPN's athlete name equals the fighter's
    name exactly (after normalisation)
  - the lead image of the fighter's own Wikipedia article (the title resolved
    by the fighter-profile job, or an exact-title match)

Every candidate must pass a quality gate (size, aspect, file-name checks)
before it is saved; saved images are cropped to a face-friendly square and
resized. Provenance and review state live in DATA_DIR/image_meta.json, keyed
by normalised fighter name:

    {
      "ryan garcia": {
        "name": "Ryan Garcia", "sport": "Boxing",
        "status": "auto" | "approved" | "manual" | "rejected",
        "source": "espn" | "wikipedia" | "url" | "upload" | "legacy",
        "source_url": "...", "path": "/persisted-fighters/ryan-garcia.jpg?v=...",
        "fetched_at": "...", "rejected_urls": [...], "note": "..."
      }
    }

Status meaning:
  auto      fetched automatically, not yet reviewed (shown in "Needs review")
  approved  a person confirmed it — never replaced automatically
  manual    set by a person (URL or upload) — never replaced automatically
  rejected  marked wrong — shows the placeholder; its URLs are never reused

Resolution order for display: image_meta entry (rejected -> no image), then
the legacy fighters.json / fighters_ufc.json databases.
"""

import io
import json
import os
import re
import threading
import time
from datetime import datetime

import requests

from scrapers import fighter_profiles as fp
import locks as _locks

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
META_FILE = os.path.join(DATA_DIR, 'image_meta.json')
JOB_FILE = os.path.join(DATA_DIR, 'image_job_status.json')
PERSIST_DIR = os.path.join(DATA_DIR, 'fighters')

_UA_BROWSER = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
_UA_BOT = 'FightScheduleBot/1.0 (https://fightschedule.live)'

REVIEWED = ('approved', 'manual')

# File-name fragments that mark an image as something other than a portrait
_BAD_FILE_TOKENS = {'flag', 'logo', 'map', 'belt', 'arena', 'stadium', 'signature', 'icon', 'emblem',
                    'seal', 'poster', 'trophy', 'medal', 'crest', 'location', 'locator', 'banner', 'wordmark'}

MIN_SHORT_SIDE = 200     # px; smaller images look blurry in the 80–96px circles on retina screens
MAX_LANDSCAPE = 1.6      # width / height above this is a scene, not a portrait
OUTPUT_SIZE = 400        # saved images are at most OUTPUT_SIZE x OUTPUT_SIZE


def key(name):
    return fp._norm(name)


def _slug(name):
    return re.sub(r'[^a-z0-9]+', '-', fp._norm(name)).strip('-') or 'fighter'


# ── metadata store ───────────────────────────────────────────────────────────

_meta_lock = threading.RLock()
_meta_cache = {'mtime': None, 'data': {}}


def load_meta():
    try:
        mtime = os.path.getmtime(META_FILE)
    except OSError:
        return {}
    if _meta_cache['mtime'] != mtime:
        try:
            with open(META_FILE) as f:
                _meta_cache['data'] = json.load(f)
            _meta_cache['mtime'] = mtime
        except Exception:
            return _meta_cache['data'] or {}
    return _meta_cache['data']


def _write_meta(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = META_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, META_FILE)


class _file_lock:
    """Cross-process lock: the bulk job runs in one gunicorn worker while admin
    actions land on another, and both read-modify-write the same file."""

    def __init__(self, path):
        self.path = path
        self.fh = None

    def __enter__(self):
        try:
            import fcntl
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self.fh = open(self.path, 'a+')
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        except Exception:
            self.fh = None
        return self

    def __exit__(self, *exc):
        if self.fh:
            try:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_UN)
            finally:
                self.fh.close()


def _fresh_meta():
    """Read the file directly (bypassing the mtime cache) inside a lock."""
    try:
        with open(META_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def update_entry(name, **fields):
    """Merge fields into one fighter's entry under an in-process and a
    cross-process lock, so a long-running job never clobbers a review action."""
    with _meta_lock, _file_lock(META_FILE + '.lock'):
        data = _fresh_meta()
        k = key(name)
        entry = dict(data.get(k) or {'name': name, 'rejected_urls': []})
        entry.update(fields)
        entry.setdefault('rejected_urls', [])
        data[k] = entry
        _write_meta(data)
        return entry


def delete_entry(name):
    with _meta_lock, _file_lock(META_FILE + '.lock'):
        data = _fresh_meta()
        data.pop(key(name), None)
        _write_meta(data)


# ── legacy databases (fighters.json / fighters_ufc.json) ─────────────────────

_legacy_cache = {'sig': None, 'data': {}}


def _legacy_db():
    paths = [os.path.join(DATA_DIR, 'fighters.json'), os.path.join(DATA_DIR, 'fighters_ufc.json')]
    sig = tuple(os.path.getmtime(p) if os.path.exists(p) else 0 for p in paths)
    if _legacy_cache['sig'] != sig:
        merged = {}
        for p in paths:          # UFC database last: it takes priority, as before
            try:
                with open(p, encoding='utf-8') as f:
                    merged.update(json.load(f))
            except Exception:
                pass
        _legacy_cache['sig'], _legacy_cache['data'] = sig, merged
    return _legacy_cache['data']


def legacy_image(name):
    return _legacy_db().get(name) or None


# ── resolution (used by the site) ────────────────────────────────────────────

def is_rejected(name):
    e = load_meta().get(key(name))
    return bool(e and e.get('status') == 'rejected' and not e.get('path'))


def image_for(name):
    """The image to display for a fighter, honouring reviews and overrides."""
    if not name or name.upper() == 'TBA':
        return None
    e = load_meta().get(key(name))
    if e:
        if e.get('path'):
            return e['path']
        if e.get('status') == 'rejected':
            return None
    return legacy_image(name)


def is_retrying(name):
    e = load_meta().get(key(name))
    return bool(e and e.get('retrying'))


# ── candidate sources ────────────────────────────────────────────────────────

def espn_candidate(name, sport):
    """ESPN headshot, only for an exact normalised name match."""
    sport_key = 'boxing' if sport == 'Boxing' else 'mma'
    try:
        r = requests.get('https://site.web.api.espn.com/apis/common/v3/search',
                         params={'query': name, 'sport': sport_key, 'type': 'athlete', 'limit': 5, 'lang': 'en'},
                         headers={'User-Agent': _UA_BROWSER}, timeout=10)
        results = r.json().get('results', [])
    except Exception:
        return None
    want = key(name)
    for res in results:
        for item in res.get('contents', []):
            data = item.get('data', item)
            aid, display = data.get('id'), data.get('displayName') or data.get('name') or ''
            if aid and key(display) == want:
                return {'url': f'https://a.espncdn.com/i/headshots/{sport_key}/players/full/{aid}.png',
                        'source': 'espn', 'file': f'{aid}.png', 'ref': f'espn:{aid}'}
    return None


def wikipedia_candidate(name, sport, title=None):
    """Lead image of the fighter's own Wikipedia article (exact-title identity)."""
    title = title or fp.resolve_title(name, sport)
    if not title:
        return None
    try:
        r = requests.get('https://en.wikipedia.org/w/api.php',
                         params={'action': 'query', 'titles': title, 'prop': 'pageimages',
                                 'piprop': 'thumbnail|name', 'pithumbsize': 600,
                                 'redirects': 1, 'format': 'json'},
                         headers={'User-Agent': _UA_BOT}, timeout=10)
        pages = r.json().get('query', {}).get('pages', {})
    except Exception:
        return None
    for page in pages.values():
        thumb = (page.get('thumbnail') or {}).get('source')
        if thumb:
            return {'url': thumb, 'source': 'wikipedia', 'file': page.get('pageimage') or thumb.rsplit('/', 1)[-1],
                    'ref': f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"}
    return None


def ufc_candidate(name, sport):
    """Official UFC.com athlete headshot. The athlete URL *is* the name
    (ufc.com/athlete/first-last), and the page title is checked against the
    fighter's name, so there is no search step to pick the wrong person."""
    if sport != 'UFC':
        return None
    slug = _slug(name)
    url = f'https://www.ufc.com/athlete/{slug}'
    try:
        r = requests.get(url, headers={'User-Agent': _UA_BROWSER}, timeout=12)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    html = r.text
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html) \
        or re.search(r'<title>([^<]+)</title>', html)
    title = m.group(1) if m else ''
    if key(name) not in key(title):
        return None          # redirected to a different athlete or a search page
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html) \
        or re.search(r'class=["\'][^"\']*hero-profile__image[^"\']*["\'][^>]+src=["\']([^"\']+)', html)
    if not m:
        return None
    img = m.group(1).replace('&amp;', '&')
    if img.startswith('/'):
        img = 'https://www.ufc.com' + img
    if 'ufc' not in img.lower() and 'dmxg' not in img.lower():
        return None          # og:image is the site logo / a share card, not the athlete
    fname = img.split('?')[0].rsplit('/', 1)[-1]
    if 'logo' in fname.lower() or 'default' in fname.lower() or 'silhouette' in fname.lower():
        return None
    return {'url': img, 'source': 'ufc', 'file': fname, 'ref': url}


_WD_API = 'https://www.wikidata.org/w/api.php'
# occupation / sport items that identify a fighter on Wikidata
_WD_FIGHTER_QIDS = {'Q11338576',   # boxer
                    'Q13381863',   # mixed martial artist
                    'Q32112',      # boxing (P641 sport)
                    'Q114466'}     # mixed martial arts (P641 sport)
_WD_DESC_WORDS = ('boxer', 'boxing', 'mixed martial', 'mma', 'pugilist', 'kickboxer')


def wikidata_candidate(name, sport):
    """Photo (P18) of the Wikidata item whose label is exactly the fighter's
    name and who is a boxer / MMA fighter. Catches fighters with a Spanish,
    Japanese, Tagalog... article but no English one."""
    want = key(name)
    hits = []
    try:
        for lang in ('en', 'es'):
            r = requests.get(_WD_API, params={'action': 'wbsearchentities', 'search': name, 'language': lang,
                                              'uselang': 'en', 'type': 'item', 'limit': 8, 'format': 'json'},
                             headers={'User-Agent': _UA_BOT}, timeout=10)
            hits += [h for h in r.json().get('search', []) if key(h.get('label', '')) == want
                     or any(key(a) == want for a in h.get('aliases', []) or [])]
            if hits:
                break
    except Exception:
        return None
    ids = list(dict.fromkeys(h['id'] for h in hits))[:6]
    if not ids:
        return None
    try:
        r = requests.get(_WD_API, params={'action': 'wbgetentities', 'ids': '|'.join(ids), 'props': 'claims|descriptions|sitelinks',
                                          'languages': 'en', 'format': 'json'},
                         headers={'User-Agent': _UA_BOT}, timeout=10)
        entities = r.json().get('entities', {})
    except Exception:
        return None
    for qid in ids:
        ent = entities.get(qid) or {}
        claims = ent.get('claims', {})

        def qids(prop):
            return {c.get('mainsnak', {}).get('datavalue', {}).get('value', {}).get('id') for c in claims.get(prop, [])}

        desc = (ent.get('descriptions', {}).get('en', {}) or {}).get('value', '').lower()
        is_fighter = bool((qids('P106') | qids('P641')) & _WD_FIGHTER_QIDS) or any(w in desc for w in _WD_DESC_WORDS)
        if not is_fighter:
            continue
        if sport == 'UFC' and 'boxer' in desc and 'mixed' not in desc:
            continue     # a boxer with the same name as a UFC fighter
        if sport == 'Boxing' and 'mixed martial' in desc and 'box' not in desc:
            continue
        for c in claims.get('P18', []):
            fname = c.get('mainsnak', {}).get('datavalue', {}).get('value')
            if fname:
                url = 'https://commons.wikimedia.org/wiki/Special:FilePath/' + requests.utils.quote(fname.replace(' ', '_')) + '?width=600'
                return {'url': url, 'source': 'wikidata', 'file': fname,
                        'ref': f'https://www.wikidata.org/wiki/{qid}', 'desc': desc}
    return None


# ── download, quality gate, processing ───────────────────────────────────────

def download(url, max_bytes=8 * 1024 * 1024):
    r = requests.get(url, headers={'User-Agent': _UA_BOT if 'wikimedia' in url else _UA_BROWSER},
                     timeout=15, stream=True)
    r.raise_for_status()
    ctype = r.headers.get('content-type', '')
    if 'image' not in ctype:
        raise ValueError(f'not an image ({ctype or "no content-type"})')
    data = r.raw.read(max_bytes + 1, decode_content=True)
    if len(data) > max_bytes:
        raise ValueError('image larger than 8 MB')
    return data


def open_image(data):
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(data))
    img.load()
    return ImageOps.exif_transpose(img)


def quality_gate(candidate, name, img, nbytes):
    """Return None if acceptable, else a short human-readable rejection reason."""
    fname = (candidate.get('file') or candidate['url'].rsplit('/', 1)[-1]).lower()
    if fname.endswith('.svg'):
        return 'vector graphic, not a photo'
    words = set(re.split(r'[^a-z0-9]+', fp._norm(re.sub(r'\.\w+$', '', fname).replace('_', ' '))))
    words -= set(key(name).split())          # a fighter's own name never counts against them
    if any(w.rstrip('s') in _BAD_FILE_TOKENS or w in _BAD_FILE_TOKENS for w in words) or 'coat of arms' in fp._norm(fname.replace('_', ' ')):
        return f'file looks like a non-portrait ({fname})'
    if candidate['source'] == 'wikipedia':
        # Infobox photos are almost always named after the person
        stem = fp._norm(re.sub(r'\.\w+$', '', fname).replace('_', ' ').replace('-', ' '))
        tokens = [t for t in key(name).split() if len(t) >= 3]
        if tokens and not any(t in stem for t in tokens):
            return f'file name does not mention the fighter ({fname})'
    if candidate['source'] == 'espn' and nbytes < 5000:
        return 'ESPN placeholder silhouette'
    w, h = img.size
    if min(w, h) < MIN_SHORT_SIDE:
        return f'too small ({w}x{h})'
    if w > MAX_LANDSCAPE * h:
        return f'landscape scene, not a portrait ({w}x{h})'
    return None


def process(img):
    """Crop to a face-friendly square and resize. Returns (bytes, ext)."""
    from PIL import Image
    has_alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)
    img = img.convert('RGBA' if has_alpha else 'RGB')
    w, h = img.size
    if h > 1.15 * w:
        # Tall portrait / full-body shot: faces sit at the top, so keep the top square
        img = img.crop((0, 0, w, w))
    elif w > h:
        # Wide headshot (e.g. ESPN 350x254): subject is centred
        x0 = (w - h) // 2
        img = img.crop((x0, 0, x0 + h, h))
    img.thumbnail((OUTPUT_SIZE, OUTPUT_SIZE), Image.LANCZOS)
    out = io.BytesIO()
    if has_alpha:
        img.save(out, 'PNG', optimize=True)
        return out.getvalue(), '.png'
    img.save(out, 'JPEG', quality=85, optimize=True, progressive=True)
    return out.getvalue(), '.jpg'


def store(name, data, ext):
    """Write a processed image to the volume; return its public path (cache-busted)."""
    os.makedirs(PERSIST_DIR, exist_ok=True)
    fname = f'{_slug(name)}{ext}'
    for other in ('.jpg', '.png'):
        if other != ext:
            try:
                os.remove(os.path.join(PERSIST_DIR, f'{_slug(name)}{other}'))
            except OSError:
                pass
    with open(os.path.join(PERSIST_DIR, fname), 'wb') as f:
        f.write(data)
    return f'/persisted-fighters/{fname}?v={int(time.time())}'


def _profile_titles():
    try:
        with open(os.path.join(DATA_DIR, 'fighter_profiles.json')) as f:
            return {k: v.get('title') for k, v in json.load(f).items() if v.get('title')}
    except Exception:
        return {}


def find_best(name, sport, rejected_urls=(), title=None):
    """First candidate that is not rejected and passes the gate.
    Returns (candidate_with_processed_image | None, [reasons for rejections])."""
    reasons = []
    for finder in (lambda: ufc_candidate(name, sport),
                   lambda: espn_candidate(name, sport),
                   lambda: wikipedia_candidate(name, sport, title),
                   lambda: wikidata_candidate(name, sport)):
        try:
            cand = finder()
        except Exception as e:
            reasons.append(f'lookup error: {e}')
            continue
        if not cand:
            continue
        if cand['url'] in rejected_urls:
            reasons.append(f"{cand['source']}: previously marked wrong")
            continue
        try:
            raw = download(cand['url'])
            img = open_image(raw)
        except Exception as e:
            reasons.append(f"{cand['source']}: {e}")
            continue
        why = quality_gate(cand, name, img, len(raw))
        if why:
            reasons.append(f"{cand['source']}: {why}")
            continue
        cand['image'] = img
        cand['size'] = img.size
        return cand, reasons
    if not reasons:
        reasons.append('no UFC.com page, ESPN athlete, Wikipedia article or Wikidata item with this exact name')
    return None, reasons


def probe(name, sport, title=None):
    """Diagnostics: what each source offers for a fighter and what the gate says.
    Downloads candidates but saves nothing."""
    out = {'name': name, 'sport': sport, 'sources': {}}
    for label, finder in (('ufc', lambda: ufc_candidate(name, sport)),
                          ('espn', lambda: espn_candidate(name, sport)),
                          ('wikipedia', lambda: wikipedia_candidate(name, sport, title)),
                          ('wikidata', lambda: wikidata_candidate(name, sport))):
        try:
            cand = finder()
        except Exception as e:
            out['sources'][label] = {'error': str(e)[:200]}
            continue
        if not cand:
            out['sources'][label] = None
            continue
        info = {k: v for k, v in cand.items() if k != 'image'}
        try:
            raw = download(cand['url'])
            img = open_image(raw)
            info['size'] = list(img.size)
            info['bytes'] = len(raw)
            info['gate'] = quality_gate(cand, name, img, len(raw)) or 'ok'
        except Exception as e:
            info['gate'] = f'download failed: {str(e)[:120]}'
        out['sources'][label] = info
    return out


# ── manual actions (admin) ───────────────────────────────────────────────────

def set_manual_from_bytes(name, sport, data, source, source_url=None):
    img = open_image(data)
    processed, ext = process(img)
    path = store(name, processed, ext)
    return update_entry(name, sport=sport, status='manual', source=source, source_url=source_url,
                        path=path, fetched_at=datetime.utcnow().isoformat() + 'Z', note=None)


def set_manual_from_url(name, sport, url):
    return set_manual_from_bytes(name, sport, download(url), 'url', url)


def approve(name, sport):
    e = load_meta().get(key(name))
    if e and e.get('path'):
        return update_entry(name, status='approved')
    current = legacy_image(name)
    if not current:
        return None
    return update_entry(name, sport=sport, status='approved', source='legacy', source_url=current, path=current)


_retry_queue = []
_retry_lock = threading.Lock()
_retry_worker = {'thread': None}


def _retry_one(name, sport, bad):
    cand, reasons = find_best(name, sport, rejected_urls=bad, title=_profile_titles().get(key(name)))
    if cand:
        data, ext = process(cand['image'])
        update_entry(name, status='auto', source=cand['source'], source_url=cand['url'], ref=cand.get('ref'),
                     path=store(name, data, ext), fetched_at=datetime.utcnow().isoformat() + 'Z',
                     note='replacement found after the previous image was marked wrong', retrying=False)
    else:
        update_entry(name, note='marked wrong; no other image found (' + '; '.join(reasons)[:160] + ')',
                     retrying=False)


def _retry_worker_loop():
    while True:
        with _retry_lock:
            if not _retry_queue:
                _retry_worker['thread'] = None
                return
            name, sport, bad = _retry_queue.pop(0)
        try:
            _retry_one(name, sport, bad)
        except Exception as ex:
            update_entry(name, note=f'marked wrong; retry failed ({str(ex)[:120]})', retrying=False)
        time.sleep(0.3)


def reject_and_retry(name, sport):
    """Mark the current image wrong (placeholder shows immediately), then look
    for a different one via the single background retry worker."""
    e = load_meta().get(key(name)) or {}
    bad = set(e.get('rejected_urls') or [])
    for u in (e.get('source_url'), e.get('path'), legacy_image(name)):
        if u:
            bad.add(u.split('?')[0] if u.startswith('/persisted-fighters/') else u)
    update_entry(name, sport=sport, status='rejected', path=None, rejected_urls=sorted(bad),
                 note='marked wrong; looking for another image', retrying=True)
    with _retry_lock:
        _retry_queue.append((name, sport, bad))
        if _retry_worker['thread'] is None or not _retry_worker['thread'].is_alive():
            _retry_worker['thread'] = threading.Thread(target=_retry_worker_loop, daemon=True)
            _retry_worker['thread'].start()


def reset(name):
    """Forget review state for a fighter (back to automatic / legacy)."""
    delete_entry(name)


# ── bulk job ─────────────────────────────────────────────────────────────────

_job_lock = threading.Lock()


def read_job():
    try:
        with open(JOB_FILE) as f:
            return json.load(f)
    except Exception:
        return None


JOB_STALE_SECONDS = 3 * 60


def _write_job(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    state['updated_at'] = datetime.utcnow().isoformat() + 'Z'
    tmp = JOB_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, JOB_FILE)


def job_view():
    """Job status for display: a 'running' job with no heartbeat for a few
    minutes (worker restarted, deploy mid-run) is reported as 'interrupted'."""
    job = read_job()
    if not job:
        return None
    if job.get('state') == 'running':
        try:
            beat = datetime.fromisoformat((job.get('updated_at') or job.get('started_at')).rstrip('Z'))
            if (datetime.utcnow() - beat).total_seconds() > JOB_STALE_SECONDS:
                job = {**job, 'state': 'interrupted'}
        except Exception:
            job = {**job, 'state': 'interrupted'}
    return job


def schedule_fighters():
    """(name, sport) for everyone in the cached schedule (upcoming + recent results)."""
    try:
        with open(os.path.join(DATA_DIR, 'fights_cache.json')) as f:
            fights = json.load(f).get('fights', [])
    except Exception:
        return []
    seen, out = set(), []
    for fight in fights:
        for k in ('fighter1', 'fighter2'):
            n = (fight.get(k) or '').strip()
            if n and n.upper() != 'TBA' and key(n) not in seen:
                seen.add(key(n))
                out.append((n, fight.get('sport', 'Boxing')))
    return out


def plan_for(name, sport, skip_recent_none=False):
    """Decide what the job should do with one fighter (without network calls).
    Returns 'skip:<why>' or 'check'. Manual runs re-check fighters with nothing
    found so far (a new source or a new article may have appeared); only the
    automatic fill honours the 7-day memory."""
    e = load_meta().get(key(name)) or {}
    if e.get('status') in REVIEWED:
        return 'skip:reviewed'
    if e.get('status') == 'auto' and e.get('source') != 'legacy' and e.get('path'):
        return 'skip:already-verified'
    if e.get('status') == 'none' and skip_recent_none:
        try:
            checked = datetime.fromisoformat((e.get('checked_at') or '').rstrip('Z'))
            if (datetime.utcnow() - checked).days < 7:
                return 'skip:none-recent'
        except Exception:
            pass
    current = legacy_image(name) if not e else e.get('path')
    if current and current.startswith('/static/'):
        # Git-tracked images (UFC.com headshots, early hand-picked uploads) are trusted
        return 'skip:trusted-static'
    return 'check'


def run_job(apply=False, fighters=None, limit=None, only_missing=False):
    """Re-check images for schedule fighters under the new rules.

    Dry run (apply=False) writes nothing except the job report. Apply saves
    verified images (status 'auto', so they appear under Needs review) and
    flags old unverifiable images for review instead of deleting them.
    """
    if not _job_lock.acquire(blocking=False):
        return False
    xlock = _locks.job_lock('image_job')
    if not xlock.__enter__():
        xlock.__exit__(None, None, None)
        _job_lock.release()
        return False
    try:
        fighters = fighters if fighters is not None else schedule_fighters()
        titles = _profile_titles()
        todo = [(n, s) for n, s in fighters if plan_for(n, s, skip_recent_none=only_missing) == 'check']
        if only_missing:
            # fill gaps only: never touch a fighter who already has an image or was marked wrong
            todo = [(n, s) for n, s in todo if not image_for(n) and (load_meta().get(key(n)) or {}).get('status') != 'rejected']
        if limit:
            todo = todo[:limit]
        report = {'would_replace': [], 'would_add': [], 'unverified': [], 'none_found': [], 'errors': []}
        state = {'state': 'running', 'mode': 'apply' if apply else 'dry-run', 'started_at': datetime.utcnow().isoformat() + 'Z',
                 'total': len(todo), 'done': 0, 'current': '', 'report': report,
                 'skipped': {r: sum(1 for n, s in fighters if plan_for(n, s, skip_recent_none=only_missing) == f'skip:{r}')
                             for r in ('reviewed', 'already-verified', 'trusted-static', 'none-recent')}}
        _write_job(state)
        for i, (name, sport) in enumerate(todo):
            state.update(done=i, current=name)
            if i % 3 == 0:
                _write_job(state)
            e = load_meta().get(key(name)) or {}
            current = e.get('path') or (None if e.get('status') == 'rejected' else legacy_image(name))
            try:
                cand, reasons = find_best(name, sport, rejected_urls=e.get('rejected_urls') or (), title=titles.get(key(name)))
            except Exception as ex:
                report['errors'].append({'name': name, 'error': str(ex)[:200]})
                continue
            if cand:
                row = {'name': name, 'sport': sport, 'source': cand['source'], 'url': cand['url'], 'size': list(cand['size'])}
                if current:
                    row['current'] = current
                    report['would_replace'].append(row)
                else:
                    report['would_add'].append(row)
                if apply:
                    data, ext = process(cand['image'])
                    update_entry(name, sport=sport, status='auto', source=cand['source'], source_url=cand['url'],
                                 ref=cand.get('ref'), path=store(name, data, ext), previous=current,
                                 fetched_at=datetime.utcnow().isoformat() + 'Z', note=None)
            elif current:
                report['unverified'].append({'name': name, 'sport': sport, 'current': current, 'why': reasons[:3]})
                if apply:
                    update_entry(name, sport=sport, status='auto', source='legacy', source_url=current, path=current,
                                 note='no verifiable source found; please review')
            else:
                report['none_found'].append({'name': name, 'sport': sport, 'why': reasons[:3]})
                if apply and e.get('status') != 'rejected':
                    update_entry(name, sport=sport, status='none', checked_at=datetime.utcnow().isoformat() + 'Z',
                                 note='; '.join(reasons)[:160])
            time.sleep(0.2)
        state.update(state='done', done=len(todo), current='', finished_at=datetime.utcnow().isoformat() + 'Z')
        _write_job(state)
        if apply and not only_missing:
            # The first reviewed bulk run arms automatic filling of new fighters
            _write_settings({**read_settings(), 'autofill': True})
        return True
    except Exception as ex:
        _write_job({'state': 'error', 'error': str(ex)[:500]})
        return False
    finally:
        xlock.__exit__(None, None, None)
        _job_lock.release()


def start_job(apply=False, limit=None, only_missing=False):
    if _job_lock.locked():
        return False
    # The in-process lock can't see other gunicorn workers; the shared status
    # file can. A job that is still heartbeating blocks a new one.
    if (job_view() or {}).get('state') == 'running':
        return False
    threading.Thread(target=run_job, kwargs={'apply': apply, 'limit': limit, 'only_missing': only_missing},
                     daemon=True).start()
    return True


SETTINGS_FILE = os.path.join(DATA_DIR, 'image_settings.json')


def read_settings():
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _write_settings(s):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(s, f)


def autofill_new_fighters(limit=40):
    """Called after each profile refresh: give new fighters a verified image.
    Does nothing until a bulk run has been applied once from the admin."""
    if read_settings().get('autofill'):
        return start_job(apply=True, limit=limit, only_missing=True)
    return False

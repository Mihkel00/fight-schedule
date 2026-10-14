"""
Photo metadata: where the face sits in each fighter photo and how to tone it,
so pages can place, crop and match photos (read through photos.photo_meta()).

One entry per image file, keyed by its site path without the query string
("/static/fighters/movsar-evloev.png", "/persisted-fighters/daniel-dubois.jpg").
What a page gets (photo_meta() / meta_for()):

    w, h      file pixels (after EXIF rotation, as browsers show it)
    face      True when a face was found; otherwise the geometry is FALLBACK's
    ex, ey    midpoint between the eyes, as fractions of width / height
    em        eye line to mouth line, as a fraction of height
    box_h     face box height / h
    crown     top of the head / h (cut-outs: read off the alpha channel;
              other photos: estimated from the eyes and mouth)
    score     detector confidence 0-1 (0 when no face)
    b, c      CSS brightness() / contrast() that bring the photo to the
              house tone (after grayscale(); see _tone())
    backdrop  'ko' near-white studio backdrop (keyed out), 'lt' light
              backdrop (toned down), or None
    cut       True for a transparent cut-out PNG
    x0, x1    usable horizontal range (0..1); narrower only where a person
              chose it (bystanders at the edge), see photo_overrides.json

Where it is kept:
    photo_meta_static.json     repo    static/fighters/*; regenerate with
                                       `python3 photo_analysis.py --static`
    photo_overrides.json       repo    hand-made corrections, per file
    DATA_DIR/photo_meta.json   volume  /persisted-fighters/* and any static
                                       image the repo file does not cover

When it is measured (never on a request thread, never at start-up):
    - image_pipeline saves or approves a photo  -> analyse_later(path)
    - after each scrape, and when a page asks for a photo that has none
      (at most every few minutes)               -> start_backfill()
    - the debug API: part=photo_meta&start=1    -> start_backfill()
The work runs in a child process (python3 photo_analysis.py --backfill), so
OpenCV's memory is returned when it ends and a crash cannot take a web worker
with it. Without OpenCV nothing is measured and photo_meta() returns None for
unmeasured photos; pages then use their fallback geometry.

Face detector: OpenCV YuNet, models/face_detection_yunet_2023mar.onnx (from
github.com/opencv/opencv_zoo, MIT licence). If it cannot be loaded, the Haar
cascade that ships with OpenCV. The main face is the largest one with a
confident score (see SURE_SCORE).
"""

import hashlib
import io
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.parse import unquote

import locks as _locks

logger = logging.getLogger('fight_schedule.photo_meta')   # the site's log (core.py) when run in the web process

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(ROOT, 'data'))
STORE_FILE = os.path.join(DATA_DIR, 'photo_meta.json')
JOB_FILE = os.path.join(DATA_DIR, 'photo_meta_job.json')
PERSIST_DIR = os.path.join(DATA_DIR, 'fighters')
STATIC_ROOT = os.path.join(ROOT, 'static')
STATIC_FIGHTERS = os.path.join(STATIC_ROOT, 'fighters')
STATIC_META_FILE = os.path.join(ROOT, 'photo_meta_static.json')
OVERRIDES_FILE = os.path.join(ROOT, 'photo_overrides.json')
# YuNet face detector, opencv_zoo models/face_detection_yunet (MIT licence: models/LICENSE-face_detection_yunet.txt)
MODEL_FILE = os.path.join(ROOT, 'models', 'face_detection_yunet_2023mar.onnx')

VERSION = 1              # bump when the measurement changes: the backfill re-measures older entries
MIN_SCORE = 0.6          # a face below this confidence is not a face
# The main face is the largest confident one (score >= SURE_SCORE), else the largest above MIN_SCORE.
# "Largest" alone picked a masked bystander in Ryan Garcia's photo (.65 against his .92), an arm in
# Nonito Donaire's (.70 against .94) and a torso in Ricardo Sandoval's (.61 against .93).
SURE_SCORE = 0.85
DETECT_MAX = 800         # px: images are measured at most this size (memory: ~60 MB at 800, 200 MB at 1600)
UPSCALE_MAX = 960        # px: a small image with no face found is tried again up to this size
CUT_MIN = 0.01           # a cut-out has at least 1 % transparent pixels (an RGBA file that is fully opaque is a photo)
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.jfif', '.webp', '.gif')

# What a page assumes for a photo with no face found (and for photo_meta() None): the face centred,
# a third of the way down, of a typical size.
FALLBACK = {'ex': 0.5, 'ey': 0.33, 'em': 0.08, 'box_h': 0.24, 'crown': 0.05}

# Crown estimate for photos that are not cut-outs: the top of the head is K_CROWN eye-to-mouth
# distances above the eye line. On the repo's 824 cut-outs, where the alpha channel shows the real
# crown, the ratio is 1.75 (p10 1.52, p90 2.0); the crowns read by eye on the mocks' hero photos give
# 1.5-2.1 (median 1.9). Erring high keeps hair inside a poster's top edge. Haar boxes carry no
# landmarks: the eye line and the eye-to-mouth distance are these fractions of the box (YuNet's
# median ratios on the same 1,029 photos).
K_CROWN = 1.9
HAAR_EY = 0.38
HAAR_EM = 0.35

# The house tone, as the approved mocks compute it (landing/hybrid4/build.py photo_tone()): the part of
# the photo a desktop poster card shows (a 358 x 520 half, 334 px of it wide, the upper 62 %), the photo
# covering its half but never enlarged past CAP; a cut-out is sized by its face (eye-to-mouth = CUT_M of
# the card height). Its mean and spread of luma are mapped to TONE by brightness(b) then contrast(c).
CARD_H, HALF_W, VIEW_W, SHOWN = 520, 358, 334, 0.62
CAP, CUT_M = 1.25, 0.11
TONE = (0.35, 0.21)
B_RANGE, C_RANGE = (0.6, 1.35), (0.85, 1.4)
LT_CURVE = (0, .2, .4, .54, .6, .62)    # a light backdrop's highlights compressed (CSS: SVG #lt filter)

# Backdrop beside the head (the outer 12 % on each side, from .15 above to .12 below the eye line),
# luma 0-1. Brighter than LT_MIN on average: a light backdrop ('lt', the mocks' rule). At least KO_SHARE
# of it at KO_WHITE or above: a white studio backdrop the pages key out ('ko'). KO_WHITE is where the
# pages' knockout filter (alpha = 15.52 - 16 x luma) is fully transparent; a flat light grey (.95) would
# turn into a see-through haze, so it stays 'lt'. Measured on the live photos: the four white studio
# shots reach .91-1.0, a bright sky or wall behind a fighter at most .84.
LT_MIN = 120 / 255
KO_WHITE, KO_SHARE = 0.97, 0.88

PUBLIC_KEYS = ('w', 'h', 'face', 'ex', 'ey', 'em', 'box_h', 'crown', 'score', 'b', 'c', 'backdrop', 'cut', 'x0', 'x1')
OVERRIDE_KEYS = {'ex', 'ey', 'em', 'box_h', 'crown', 'b', 'c', 'backdrop', 'x0', 'x1'}


# ── paths ────────────────────────────────────────────────────────────────────

def path_key(path):
    """'/persisted-fighters/x.jpg?v=1' -> '/persisted-fighters/x.jpg' (None for remote or other paths)."""
    if not path or not isinstance(path, str):
        return None
    bare = unquote(path.split('?', 1)[0].split('#', 1)[0])
    if bare.startswith('/persisted-fighters/') or bare.startswith('/static/'):
        return bare
    return None


def file_for(key):
    """Local file behind a path key, or None (never outside the two image folders)."""
    if not key:
        return None
    if key.startswith('/persisted-fighters/'):
        base, rel = PERSIST_DIR, key[len('/persisted-fighters/'):]
    elif key.startswith('/static/'):
        base, rel = STATIC_ROOT, key[len('/static/'):]
    else:
        return None
    full = os.path.normpath(os.path.join(base, rel))
    if not full.startswith(os.path.normpath(base) + os.sep):
        return None
    return full


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _signature(file_path):
    st = os.stat(file_path)
    return st.st_size, int(st.st_mtime)


def _sha1(data):
    return hashlib.sha1(data).hexdigest()


# ── OpenCV (optional) ────────────────────────────────────────────────────────

def _cv():
    """(cv2, numpy), or (None, None) when OpenCV is not installed or fails to load."""
    try:
        import cv2
        import numpy as np
        return cv2, np
    except Exception:
        return None, None


def available():
    """True when OpenCV can be imported here (checked without importing it)."""
    try:
        import importlib.util
        return importlib.util.find_spec('cv2') is not None and importlib.util.find_spec('numpy') is not None
    except Exception:
        return False


_detector_state = {'yunet': None, 'failed': False}


def _detect(cv2, np, bgr):
    """[(x, y, w, h, score, landmarks or None)] for every face; ('yunet' | 'haar', faces)."""
    h, w = bgr.shape[:2]
    if not _detector_state['failed']:
        try:
            det = _detector_state['yunet']
            if det is None:
                det = cv2.FaceDetectorYN.create(MODEL_FILE, '', (w, h), MIN_SCORE, 0.3, 50)
                _detector_state['yunet'] = det
            det.setInputSize((w, h))
            _, found = det.detect(bgr)
            faces = [] if found is None else [
                (float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[14]), [float(v) for v in r[4:14]])
                for r in found]
            return 'yunet', faces
        except Exception as e:
            logger.warning(f'photo meta: YuNet unavailable ({e}); using the Haar cascade')
            _detector_state['failed'] = True
    casc = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml'))
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    found = casc.detectMultiScale(gray, 1.06, 6)
    return 'haar', [(float(x), float(y), float(fw), float(fh), MIN_SCORE, None) for (x, y, fw, fh) in found]


def _find_face(cv2, np, rgb):
    """Main face in an RGB array: (detector, face, count) with face = (x, y, w, h, score, landmarks)
    in the array's pixels, or (detector, None, 0). Large images are measured at DETECT_MAX; a small
    one with no face is tried again enlarged (a 168 px press frame)."""
    h, w = rgb.shape[:2]
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    base = min(1.0, DETECT_MAX / max(w, h))
    scales = [base]
    if base == 1.0:
        scales += [s for s in (2.0, 3.0) if max(w, h) * s <= UPSCALE_MAX]
    used = 'yunet'
    for s in scales:
        img = bgr if s == 1.0 else cv2.resize(bgr, (max(1, round(w * s)), max(1, round(h * s))),
                                              interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
        used, faces = _detect(cv2, np, img)
        faces = [f for f in faces if f[4] >= MIN_SCORE and f[2] > 0 and f[3] > 0]
        if faces:
            sure = [f for f in faces if f[4] >= SURE_SCORE]
            x, y, fw, fh, sc, lm = max(sure or faces, key=lambda f: f[2] * f[3])
            k = 1.0 / s
            lm = [v * k for v in lm] if lm else None
            return used, (x * k, y * k, fw * k, fh * k, sc, lm), len(faces)
    return used, None, 0


# ── measurements ─────────────────────────────────────────────────────────────

def _luma(np, rgb):
    return (rgb.astype(np.float32) / 255.0) @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _backdrop(np, lum, alpha, w, h, ey):
    """'ko', 'lt' or None from the strips beside the head."""
    sw = max(1, int(w * 0.12))
    ya, yb = int(max(0.0, ey - 0.15) * h), int(min(1.0, ey + 0.12) * h)
    yb = max(ya + 1, yb)
    strips = [(slice(ya, yb), slice(0, sw)), (slice(ya, yb), slice(w - sw, w))]
    v = np.concatenate([lum[s][alpha[s] > 200 / 255].ravel() for s in strips])
    if v.size < 20:
        return None
    if (v >= KO_WHITE).mean() >= KO_SHARE:
        return 'ko'
    if float(v.mean()) > LT_MIN:
        return 'lt'
    return None


def _tone(np, lum, alpha, w, h, ex, em, cut, backdrop):
    """(b, c): CSS brightness() then contrast() that map the shown part's mean / spread of luma to
    TONE, as landing/hybrid4/build.py photo_tone() computes them for the approved pages."""
    if cut:
        s = min(CAP, CUT_M * CARD_H / max(em * h, 1e-3))
    else:
        s = min(CAP, max(HALF_W / w, CARD_H / h))
    vw, vh = VIEW_W / s, SHOWN * CARD_H / s
    x0 = max(0.0, min(w - vw, ex * w - vw / 2))
    xs, ys = slice(int(x0), int(min(w, x0 + vw))), slice(0, int(min(h, vh)))
    v = lum[ys, xs][alpha[ys, xs] >= 128 / 255]
    if backdrop == 'ko':
        v = v[v < 0.9]
    elif backdrop == 'lt':
        v = np.interp(v, np.linspace(0, 1, len(LT_CURVE)), LT_CURVE)
    if v.size < 50:
        return 0.95, 1.05
    m = max(float(v.mean()), 0.02)
    sd = max(0.05, float(v.std()))
    m0, s0 = TONE
    c = max(C_RANGE[0], min(C_RANGE[1], 2 * ((s0 / sd) * m - m0 + 0.5)))
    b = max(B_RANGE[0], min(B_RANGE[1], ((m0 - 0.5) / c + 0.5) / m))
    return round(b, 3), round(c, 3)


def _alpha_top(np, alpha, x_from, x_to, y_to):
    """First row (fraction of height) above y_to where the band x_from..x_to is opaque, or None."""
    h, w = alpha.shape
    xa, xb = max(0, int(x_from)), min(w, int(x_to))
    if xb <= xa:
        return None
    band = alpha[:max(1, int(y_to)), xa:xb] >= 0.5
    rows = np.nonzero(band.mean(axis=1) >= 0.05)[0]
    return float(rows[0]) / h if rows.size else None


def analyse_image(data, override=None):
    """Measure one image (file bytes). Returns the entry (public keys plus bookkeeping),
    or None when OpenCV is missing. Raises on a file that is not a readable image."""
    cv2, np = _cv()
    if cv2 is None:
        return None
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(data))
    im.load()
    im = ImageOps.exif_transpose(im)
    w, h = im.size
    rgba = np.asarray(im.convert('RGBA'))
    alpha = rgba[..., 3].astype(np.float32) / 255.0
    cut = bool((alpha < 0.5).mean() >= CUT_MIN)
    # detection on the photo laid over a dark grey, as the pages show cut-outs
    over = rgba[..., :3].astype(np.float32) * alpha[..., None] + 40.0 * (1 - alpha[..., None])
    detector, face, n = _find_face(cv2, np, over.astype(np.uint8))
    ov = dict(override or {})

    e = {'w': w, 'h': h, 'face': face is not None, 'score': 0.0, 'cut': cut, 'x0': 0.0, 'x1': 1.0}
    if face:
        x, y, fw, fh, sc, lm = face
        if lm:
            rex, rey, lex, ley, _nx, _ny, rmx, rmy, lmx, lmy = lm
            ex, ey = (rex + lex) / 2, (rey + ley) / 2
            em = (rmy + lmy) / 2 - ey
        else:                                     # Haar: a box only
            ex, ey, em = x + fw / 2, y + HAAR_EY * fh, HAAR_EM * fh
        e.update(ex=ex / w, ey=ey / h, em=max(em / h, 0.005), box_h=fh / h, score=round(sc, 3))
    else:
        x, y, fw, fh = w * 0.3, 0, w * 0.4, h
        e.update({k: FALLBACK[k] for k in ('ex', 'ey', 'em', 'box_h')})
    for k in ('ex', 'ey', 'em', 'box_h'):
        if k in ov:
            e[k] = float(ov[k])

    lum = _luma(np, rgba[..., :3])
    if cut:
        top = _alpha_top(np, alpha, x, x + fw, e['ey'] * h)
        crown = top if top is not None else max(0.0, e['ey'] - K_CROWN * e['em'])
        backdrop = None
    else:
        crown = max(0.0, e['ey'] - K_CROWN * e['em']) if e['face'] else FALLBACK['crown']
        backdrop = _backdrop(np, lum, alpha, w, h, e['ey'])
    e['crown'] = crown
    e['backdrop'] = ov['backdrop'] if 'backdrop' in ov else backdrop
    e['b'], e['c'] = _tone(np, lum, alpha, w, h, e['ex'], e['em'], cut, e['backdrop'])
    for k in ('crown', 'b', 'c', 'x0', 'x1'):
        if k in ov:
            e[k] = float(ov[k])
    for k in ('ex', 'ey', 'em', 'box_h', 'crown', 'x0', 'x1'):
        e[k] = round(min(1.0, max(0.0, float(e[k]))), 4)
    e.update(n=n, detector=detector if face else None, v=VERSION, sha1=_sha1(data), ov=_ov_sig(ov),
             at=_now())
    return e


def analyse_file(file_path, override=None):
    with open(file_path, 'rb') as fh:
        data = fh.read()
    e = analyse_image(data, override)
    if e is not None:
        e['size'] = len(data)
        try:
            e['mtime'] = int(os.stat(file_path).st_mtime)
        except OSError:
            pass
    return e


# ── overrides (hand-made, committed) ─────────────────────────────────────────

_files_cache = {}


def _load_json_cached(path):
    """Parsed JSON file, re-read when its mtime changes; {} if missing or unreadable."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _files_cache.pop(path, None)
        return {}
    hit = _files_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except Exception as e:
        logger.warning(f'photo meta: cannot read {os.path.basename(path)}: {e}')
        return hit[1] if hit else {}
    _files_cache[path] = (mtime, data)
    return data


def _clean_override(raw):
    out = {}
    for k, v in (raw or {}).items():
        if k == 'backdrop' and v in ('ko', 'lt', None):
            out[k] = v
        elif k in OVERRIDE_KEYS and k != 'backdrop' and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = float(v)
    return out


def override_for(key, sha1=None):
    """The corrections for one file. An override that names a file's sha1 applies to that file
    only, so a replaced photo never inherits the old photo's crop."""
    raw = _load_json_cached(OVERRIDES_FILE).get(key)
    if not isinstance(raw, dict):
        return {}
    want = raw.get('sha1')
    if want and sha1 and want != sha1:
        return {}
    if want and not sha1:
        return {}
    return _clean_override(raw)


def _ov_sig(ov):
    return _sha1(json.dumps(ov or {}, sort_keys=True).encode())[:10] if ov else ''


# ── store ────────────────────────────────────────────────────────────────────

def load_store():
    return _load_json_cached(STORE_FILE)


def load_static():
    return _load_json_cached(STATIC_META_FILE)


def _write_json_atomic(path, data, one_per_line=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        if one_per_line:
            fh.write('{\n')
            items = sorted(data.items())
            for i, (k, v) in enumerate(items):
                fh.write(f'{json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False, sort_keys=True)}'
                         + (',\n' if i < len(items) - 1 else '\n'))
            fh.write('}\n')
        else:
            json.dump(data, fh, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def record(entries):
    """Merge {key: entry} into DATA_DIR/photo_meta.json under the cross-process lock."""
    if not entries:
        return True
    with _locks.job_lock('photo_meta_store', wait_seconds=30) as got:
        if not got:
            logger.warning(f'photo meta: store busy, {len(entries)} entries not saved (the next backfill retries)')
            return False
        try:
            with open(STORE_FILE, encoding='utf-8') as fh:
                data = json.load(fh)
        except Exception:
            data = {}
        data.update(entries)
        _write_json_atomic(STORE_FILE, data)
        _files_cache.pop(STORE_FILE, None)
    return True


def _fresh(entry, key, check_file=True):
    """True when a stored entry still describes the file on disk and the current rules."""
    if not isinstance(entry, dict) or entry.get('v') != VERSION:
        return False
    if check_file:
        f = file_for(key)
        try:
            size, mtime = _signature(f)
        except (OSError, TypeError):
            return False
        if entry.get('size') != size or entry.get('mtime') != mtime:
            return False
    return True


def _public(entry, override):
    out = {k: entry.get(k) for k in PUBLIC_KEYS}
    if override:
        out.update(override)
        for k in ('ex', 'ey', 'em', 'box_h', 'crown', 'x0', 'x1'):
            out[k] = min(1.0, max(0.0, float(out[k])))
    return out


def stored_entry(key):
    """The current entry for a path key (committed file first for static images), or None."""
    if key.startswith('/static/'):
        e = load_static().get(key)
        if isinstance(e, dict) and e.get('v') == VERSION and not e.get('error'):
            return e
    e = load_store().get(key)
    if _fresh(e, key) and not e.get('error'):
        return e
    return None


def meta_for(path):
    """photos.photo_meta(): the contract dict for a stored photo, or None (not measured yet, a
    remote URL, or any error). Reads only; a miss for a local file asks for a background backfill."""
    try:
        key = path_key(path)
        if not key:
            return None
        e = stored_entry(key)
        if e is None:
            _note_miss(key)
            return None
        return _public(e, override_for(key, e.get('sha1')))
    except Exception as ex:
        logger.warning(f'photo meta lookup failed for {path!r}: {ex}')
        return None


# ── what to measure ──────────────────────────────────────────────────────────

def _referenced_paths():
    """Image paths the site uses: reviewed/auto images and the legacy databases."""
    out = set()
    for name in ('image_meta.json', 'fighters.json', 'fighters_ufc.json'):
        try:
            with open(os.path.join(DATA_DIR, name), encoding='utf-8') as fh:
                data = json.load(fh)
        except Exception:
            continue
        for v in data.values():
            p = v.get('path') if isinstance(v, dict) else v
            k = path_key(p)
            if k:
                out.add(k)
    return out


def candidate_keys():
    """Every local image that may be shown: the volume's photos, the repo's static/fighters and
    any other local path the data refers to."""
    keys = set(_referenced_paths())
    for folder, prefix in ((PERSIST_DIR, '/persisted-fighters/'), (STATIC_FIGHTERS, '/static/fighters/')):
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        keys.update(prefix + n for n in names if n.lower().endswith(IMAGE_EXT))
    return sorted(k for k in keys if file_for(k) and os.path.isfile(file_for(k)))


def needs_measuring(key):
    """True when a path has no current entry (or its overrides changed since it was measured)."""
    if key.startswith('/static/'):
        e = load_static().get(key)
        if isinstance(e, dict) and e.get('v') == VERSION:
            return False
    e = load_store().get(key)
    if not _fresh(e, key):
        return True
    if e.get('error'):
        return False                          # unreadable file: not retried until it changes
    return (e.get('ov') or '') != _ov_sig(override_for(key, e.get('sha1')))


# ── backfill (runs in the child process, or in-process from tests / the CLI) ──

def backfill(keys=None, limit=None, force=False, save_every=25):
    """Measure every image without current metadata (or just `keys`). Returns counts."""
    counts = {'measured': 0, 'faces': 0, 'no_face': 0, 'failed': 0, 'skipped': 0, 'unchanged': 0}
    if not _cv()[0]:
        counts['error'] = 'OpenCV is not available'
        return counts
    todo = []
    for k in (keys if keys is not None else candidate_keys()):
        k = path_key(k)
        if not k:
            continue
        if force or needs_measuring(k):
            todo.append(k)
        else:
            counts['skipped'] += 1
    if limit:
        todo = todo[:limit]
    pending = {}
    store = load_store()
    for i, k in enumerate(todo):
        f = file_for(k)
        try:
            with open(f, 'rb') as fh:
                data = fh.read()
            sha = _sha1(data)
            old = store.get(k)
            ov = override_for(k, sha)
            if (not force and isinstance(old, dict) and old.get('v') == VERSION and old.get('sha1') == sha
                    and not old.get('error') and (old.get('ov') or '') == _ov_sig(ov)):
                # same bytes, new mtime (file copied or rewritten): keep the measurement
                old = dict(old, size=len(data), mtime=int(os.stat(f).st_mtime))
                pending[k] = old
                counts['unchanged'] += 1
            else:
                e = analyse_image(data, ov)
                e['size'], e['mtime'] = len(data), int(os.stat(f).st_mtime)
                pending[k] = e
                counts['measured'] += 1
                counts['faces' if e['face'] else 'no_face'] += 1
        except Exception as ex:
            counts['failed'] += 1
            try:
                size, mtime = _signature(f)
            except Exception:
                size, mtime = None, None
            pending[k] = {'v': VERSION, 'error': str(ex)[:200], 'size': size, 'mtime': mtime,
                          'at': _now()}
        if len(pending) >= save_every:
            record(pending)
            pending = {}
    record(pending)
    return counts


def build_static(out_file=None):
    """Measure every image in static/fighters into the committed photo_meta_static.json."""
    cv2, _ = _cv()
    if cv2 is None:
        raise RuntimeError('OpenCV is not available')
    out = {}
    counts = {'measured': 0, 'faces': 0, 'no_face': 0, 'failed': 0}
    for name in sorted(os.listdir(STATIC_FIGHTERS)):
        if not name.lower().endswith(IMAGE_EXT):
            continue
        key = '/static/fighters/' + name
        with open(os.path.join(STATIC_FIGHTERS, name), 'rb') as fh:
            data = fh.read()
        try:
            e = analyse_image(data, override_for(key, _sha1(data)))
        except Exception as ex:
            counts['failed'] += 1
            out[key] = {'v': VERSION, 'error': str(ex)[:200], 'sha1': _sha1(data)}
            continue
        e.pop('at', None)
        e['size'] = len(data)
        out[key] = e
        counts['measured'] += 1
        counts['faces' if e['face'] else 'no_face'] += 1
    _write_json_atomic(out_file or STATIC_META_FILE, out, one_per_line=True)
    return counts


# ── background runs (web process side) ───────────────────────────────────────

_run_lock = threading.Lock()
_queue = []
_queue_lock = threading.Lock()
_worker = {'thread': None}
_miss = {'last': 0.0}
MISS_INTERVAL = 600          # s: a page that finds photos without metadata starts a backfill at most this often
CHILD_TIMEOUT = 1800         # s


def read_job():
    try:
        with open(JOB_FILE, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None


def _write_job(state):
    try:
        _write_json_atomic(JOB_FILE, state)
    except Exception as e:
        logger.warning(f'photo meta: cannot write job status: {e}')


def _run_child(args):
    """Run `python3 photo_analysis.py <args>` and return its JSON summary (last stdout line)."""
    proc = subprocess.run([sys.executable, os.path.abspath(__file__)] + args, cwd=ROOT,
                          capture_output=True, text=True, timeout=CHILD_TIMEOUT,
                          env=dict(os.environ, DATA_DIR=DATA_DIR))
    lines = [ln for ln in (proc.stdout or '').strip().splitlines() if ln.strip()]
    try:
        out = json.loads(lines[-1]) if lines else {}
    except ValueError:
        out = {}
    if proc.returncode != 0:
        out.setdefault('error', ((proc.stderr or '').strip().splitlines() or [f'exit {proc.returncode}'])[-1][:300])
    return out


def run_backfill(keys=None, reason='', force=False):
    """One backfill in a child process, under the cross-process lock. Blocks; returns counts or None
    when another backfill is running. Call from a background thread (start_backfill)."""
    if not available():
        logger.info('photo meta backfill skipped: OpenCV is not installed')
        return None
    if not _run_lock.acquire(blocking=False):
        return None
    try:
        with _locks.job_lock('photo_meta') as got:
            if not got:
                return None
            started = time.time()
            _write_job({'state': 'running', 'reason': reason, 'started_at': _now(),
                        'paths': len(keys) if keys else None})
            args = ['--backfill'] + (['--force'] if force else []) + (['--paths'] + list(keys) if keys else [])
            try:
                counts = _run_child(args)
            except Exception as e:
                counts = {'error': str(e)[:300]}
            counts['seconds'] = round(time.time() - started, 1)
            _write_job({'state': 'error' if counts.get('error') else 'done', 'reason': reason,
                        'finished_at': _now(), 'counts': counts})
            logger.info(f'photo meta backfill ({reason or "manual"}): ' + ', '.join(f'{k} {v}' for k, v in counts.items()))
            _files_cache.pop(STORE_FILE, None)
            return counts
    finally:
        _run_lock.release()


def start_backfill(reason=''):
    """Start a backfill in a background thread; False when one is already running here.
    Never raises: callers (the scrape, a page lookup) must not fail because of it."""
    try:
        if _run_lock.locked() or not available():
            return False
        threading.Thread(target=run_backfill, kwargs={'reason': reason}, daemon=True).start()
        return True
    except Exception as e:
        logger.warning(f'photo meta: backfill not started: {e}')
        return False


def _worker_loop():
    while True:
        with _queue_lock:
            keys = sorted(set(_queue))
            _queue.clear()
            if not keys:
                _worker['thread'] = None
                return
        try:
            for _ in range(60):              # another backfill holds the lock: wait for it (up to ~10 min)
                if run_backfill(keys=keys, reason='image saved') is not None:
                    break
                time.sleep(10)
        except Exception as e:
            logger.warning(f'photo meta: measuring saved images failed: {e}')


def analyse_later(path):
    """Measure a just-saved photo in the background (image_pipeline's store/approve path).
    Never raises: saving a photo must not fail because of its metadata."""
    try:
        key = path_key(path)
        if not key or not available() or not needs_measuring(key):
            return False
        with _queue_lock:
            _queue.append(key)
            if _worker['thread'] is None or not _worker['thread'].is_alive():
                _worker['thread'] = threading.Thread(target=_worker_loop, daemon=True)
                _worker['thread'].start()
        return True
    except Exception as e:
        logger.warning(f'photo meta: {path!r} not queued: {e}')
        return False


def _note_miss(key):
    """A page asked for a local photo with no metadata: start a backfill, at most every MISS_INTERVAL."""
    now = time.time()
    if now - _miss['last'] < MISS_INTERVAL:
        return
    f = file_for(key)
    if not f or not os.path.isfile(f):
        return
    _miss['last'] = now
    start_backfill(reason='page found a photo without metadata')


def summary():
    """Counts for the debug API."""
    store, static = load_store(), load_static()
    def tally(d):
        vals = [e for e in d.values() if isinstance(e, dict)]
        return {'entries': len(vals), 'faces': sum(1 for e in vals if e.get('face')),
                'no_face': sum(1 for e in vals if not e.get('error') and not e.get('face')),
                'errors': sum(1 for e in vals if e.get('error')),
                'cut_outs': sum(1 for e in vals if e.get('cut')),
                'backdrop_ko': sum(1 for e in vals if e.get('backdrop') == 'ko'),
                'backdrop_lt': sum(1 for e in vals if e.get('backdrop') == 'lt')}
    return {'opencv': available(), 'model': os.path.exists(MODEL_FILE), 'static': tally(static),
            'volume': tally(store), 'job': read_job()}


# ── command line ─────────────────────────────────────────────────────────────

def _main(argv):
    import argparse
    ap = argparse.ArgumentParser(description='Measure fighter photos (face position, tone).')
    ap.add_argument('--static', action='store_true', help='regenerate photo_meta_static.json (repo images)')
    ap.add_argument('--backfill', action='store_true', help='measure images without metadata into DATA_DIR')
    ap.add_argument('--paths', nargs='*', help='only these site paths')
    ap.add_argument('--force', action='store_true', help='measure again even when current')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--file', help='print the measurement of one local file')
    a = ap.parse_args(argv)
    cv2, _ = _cv()
    if cv2 is not None:
        cv2.setNumThreads(2)
    if a.file:
        e = analyse_file(a.file)
        print(json.dumps(e, sort_keys=True))
        return 0 if e else 1
    if a.static:
        print(json.dumps(build_static()))
        return 0
    if a.backfill:
        counts = backfill(keys=a.paths or None, limit=a.limit, force=a.force)
        print(json.dumps(counts))
        return 0 if not counts.get('error') else 1
    ap.print_help()
    return 2


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    sys.exit(_main(sys.argv[1:]))

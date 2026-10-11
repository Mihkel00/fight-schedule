"""
Fighter photos: which image to show, same-picture checks, photo credits.

Moved out of app.py unchanged (2026-10); app.py imports every module so
the routes register on the one Flask app.
"""
import image_pipeline as _images
import json
import os
from flask import send_from_directory
from core import app, data_path


def load_fighter_database():
    """Load fighters.json and fighters_ufc.json from persistent data directory"""
    fighters_db = {}

    # Load general fighter database
    try:
        with open(data_path('fighters.json'), 'r', encoding='utf-8') as f:
            fighters_db.update(json.load(f))
    except:
        pass

    # Load UFC-specific database (from UFC.com scraper)
    try:
        with open(data_path('fighters_ufc.json'), 'r', encoding='utf-8') as f:
            ufc_db = json.load(f)
            # UFC database takes priority for UFC fighters
            fighters_db.update(ufc_db)
    except:
        pass

    return fighters_db


def get_fighter_image(fighter_name):
    """Image to display for a fighter: reviewed/manual overrides first, then the
    legacy fighters.json / fighters_ufc.json databases (see image_pipeline.py)."""
    return _images.image_for(fighter_name)


@app.route('/persisted-fighters/<path:filename>')
def persisted_fighter_image(filename):
    """Serve fighter images stored in the persistent data volume."""
    fighters_dir = data_path('fighters')
    return send_from_directory(fighters_dir, filename)


_photo_thumb_cache = {}


def _photo_file(url):
    """Local file behind a fighter photo URL, or None for remote images."""
    bare = (url or '').split('?')[0]
    if bare.startswith('/persisted-fighters/'):
        return os.path.join(data_path('fighters'), bare[len('/persisted-fighters/'):])
    if bare.startswith('/static/'):
        return os.path.join(app.root_path, bare.lstrip('/'))
    return None


def _photo_thumb(path):
    """32px-wide greyscale thumbnail of a stored photo, cached by file mtime."""
    mtime = os.path.getmtime(path)
    cached = _photo_thumb_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        g = ImageOps.exif_transpose(im).convert('L')
        thumb = g.resize((32, max(1, round(g.height * 32 / g.width))))
    _photo_thumb_cache[path] = (mtime, thumb)
    return thumb


def _same_picture(url_a, url_b):
    """True when two fighter photos show the same picture. Saved photos are
    square crops, so the same source can be stored twice with different crops
    and bytes (e.g. one walkout photo saved for both fighters). Compare small
    greyscale thumbnails, sliding the shorter one along the taller one. Same
    picture scores ~3, different fighters 24+ on live data; the cut-off is 12."""
    if url_a.split('?')[0] == url_b.split('?')[0]:
        return True
    pa, pb = _photo_file(url_a), _photo_file(url_b)
    if not pa or not pb or not os.path.exists(pa) or not os.path.exists(pb):
        return False
    a, b = _photo_thumb(pa), _photo_thumb(pb)
    if a.height > b.height:
        a, b = b, a
    da = a.tobytes()
    best = 255.0
    for off in range(0, b.height - a.height + 1):
        db = b.crop((0, off, 32, off + a.height)).tobytes()
        best = min(best, sum(abs(x - y) for x, y in zip(da, db)) / len(da))
    return best < 12


def _two_distinct_photos(ev):
    a, b = ev.get('fighter1_image'), ev.get('fighter2_image')
    if not a or not b:
        return False
    for u in (a, b):
        f = _photo_file(u)
        if f and not os.path.exists(f):   # a photo that would render broken
            return False
    try:
        return not _same_picture(a, b)
    except Exception:
        return a.split('?')[0] != b.split('?')[0]


def photo_credits(sport, m):
    """Credits for the two hero photos on a fight page: a list of
    {'credit': …, 'who': surname or None}. Same credit for both → one entry."""
    out = []
    for side in ('fighter1', 'fighter2'):
        img = m.get(f'{side}_image') if hasattr(m, 'get') else None
        c = _images.credit_for(m.get(side), sport, shown=img) if img else None
        out.append((c, (m.get(side) or '').split()[-1] if m.get(side) else None))
    known = [(c, who) for c, who in out if c]
    if not known:
        return []
    if len(known) == 2 and known[0][0] == known[1][0]:
        return [{'credit': known[0][0], 'who': None}]
    return [{'credit': c, 'who': who} for c, who in known]

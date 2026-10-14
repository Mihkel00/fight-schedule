"""Photo metadata (photos.photo_meta / photo_analysis.py): the contract pages
code against, the fallback without OpenCV, the store, and the backfill."""
import hashlib
import json
import os
import shutil
import sys
import threading

import pytest

import app as A  # noqa: F401  (conftest has set DATA_DIR)
import image_pipeline
import locks
import photo_analysis as pa
import photos

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACE_PNG = '/static/fighters/movsar-evloev.png'          # UFC.com cut-out, one face
CROWD_JPG = '/static/fighters/nonito-donaire.jpg'        # three "faces": an arm scores .70, his face .94
NO_FACE_PNG = '/static/fighters/estefani-almeida.png'    # UFC.com's "no photo" silhouette
needs_cv = pytest.mark.skipif(not pa.available(), reason='OpenCV not installed')


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A private DATA_DIR for the metadata store, with an empty fighters folder."""
    d = tmp_path / 'data'
    (d / 'fighters').mkdir(parents=True)
    monkeypatch.setattr(pa, 'DATA_DIR', str(d))
    monkeypatch.setattr(pa, 'STORE_FILE', str(d / 'photo_meta.json'))
    monkeypatch.setattr(pa, 'JOB_FILE', str(d / 'photo_meta_job.json'))
    monkeypatch.setattr(pa, 'PERSIST_DIR', str(d / 'fighters'))
    monkeypatch.setattr(locks, 'DATA_DIR', str(d))
    monkeypatch.setitem(pa._miss, 'last', float('inf'))     # no self-started backfills behind a test's back
    pa._files_cache.clear()
    yield d
    pa._files_cache.clear()


def _persist(store, name, src=FACE_PNG):
    shutil.copy(os.path.join(ROOT, src.lstrip('/')), store / 'fighters' / name)
    return f'/persisted-fighters/{name}'


def _check_contract(m):
    assert set(m) == set(pa.PUBLIC_KEYS)
    assert isinstance(m['w'], int) and isinstance(m['h'], int) and m['w'] > 0 and m['h'] > 0
    assert isinstance(m['face'], bool) and isinstance(m['cut'], bool)
    for k in ('ex', 'ey', 'em', 'box_h', 'crown', 'x0', 'x1', 'score'):
        assert isinstance(m[k], float) and 0 <= m[k] <= 1, k
    assert m['x0'] < m['x1']
    assert m['backdrop'] in (None, 'ko', 'lt')
    assert 0.6 <= m['b'] <= 1.35 and 0.85 <= m['c'] <= 1.4


# ── the contract ────────────────────────────────────────────────────────────

def test_contract_for_a_repo_photo():
    m = photos.photo_meta(FACE_PNG)
    _check_contract(m)
    assert m['face'] and m['cut'] and m['backdrop'] is None
    assert (m['w'], m['h']) == (400, 300)
    assert m['ex'] == pytest.approx(0.50, abs=0.02) and m['ey'] == pytest.approx(0.38, abs=0.02)
    assert m['crown'] < m['ey'] and (m['x0'], m['x1']) == (0.0, 1.0)


def test_query_string_and_encoding_are_ignored():
    m = photos.photo_meta(FACE_PNG)
    assert photos.photo_meta(FACE_PNG + '?v=1790699802') == m
    assert photos.photo_meta('/static/fighters/Kevin%20Brown.png') == photos.photo_meta('/static/fighters/Kevin Brown.png')
    assert photos.photo_meta('/static/fighters/Kevin Brown.png') is not None


@pytest.mark.parametrize('path', [None, '', 'https://ufc.com/images/x.png', '/themes/custom/ufc/a.png',
                                  '/persisted-fighters/../../etc/passwd', '/static/../app.py', 42])
def test_remote_odd_or_unsafe_paths_return_none(store, path):
    assert photos.photo_meta(path) is None


def test_photo_without_a_face_still_has_geometry():
    m = photos.photo_meta(NO_FACE_PNG)
    _check_contract(m)
    assert not m['face'] and m['score'] == 0
    assert (m['ex'], m['ey'], m['em']) == (pa.FALLBACK['ex'], pa.FALLBACK['ey'], pa.FALLBACK['em'])


def test_committed_metadata_covers_every_repo_photo():
    """photo_meta_static.json is current: regenerate with `python3 photo_analysis.py --static`
    after adding or changing a file in static/fighters (or an override for one)."""
    static = pa.load_static()
    names = [n for n in os.listdir(pa.STATIC_FIGHTERS) if n.lower().endswith(pa.IMAGE_EXT)]
    assert names
    for n in names:
        key = '/static/fighters/' + n
        e = static.get(key)
        assert e and e.get('v') == pa.VERSION and not e.get('error'), f'{key}: no metadata; run photo_analysis.py --static'
        with open(os.path.join(pa.STATIC_FIGHTERS, n), 'rb') as fh:
            sha = hashlib.sha1(fh.read()).hexdigest()
        assert e['sha1'] == sha, f'{key} changed since it was measured; run photo_analysis.py --static'
        assert e['ov'] == pa._ov_sig(pa.override_for(key, sha)), f'{key}: overrides changed; run photo_analysis.py --static'
        _check_contract(pa._public(e, None))


def test_overrides_file_is_well_formed():
    with open(pa.OVERRIDES_FILE, encoding='utf-8') as fh:
        raw = json.load(fh)
    for key, o in raw.items():
        if key.startswith('_'):
            continue
        assert pa.path_key(key) == key, key
        assert set(o) - pa.OVERRIDE_KEYS - {'sha1', 'why'} == set(), key
        assert o.get('why'), f'{key}: say why'
        clean = pa._clean_override(o)
        assert clean, key
        assert clean.get('x0', 0) < clean.get('x1', 1)


# ── measuring ───────────────────────────────────────────────────────────────

@needs_cv
def test_measures_a_face_like_the_approved_mocks():
    """Movsar Evloev's cut-out as the mocks measured it (hybrid4/work/faces.json, photo_tone())."""
    e = pa.analyse_file(os.path.join(ROOT, FACE_PNG.lstrip('/')))
    assert e['face'] and e['cut'] and e['detector'] == 'yunet'
    assert (e['ex'], e['ey'], e['em'], e['box_h']) == pytest.approx((0.4995, 0.3831, 0.1903, 0.4949), abs=0.003)
    assert (e['b'], e['c']) == pytest.approx((0.811, 1.017), abs=0.005)
    assert e['crown'] == pytest.approx(0.033, abs=0.01)       # top of the alpha over the face


@needs_cv
def test_main_face_is_the_largest_confident_one():
    """The largest box in Nonito Donaire's photo is his raised arm (score .70); his face scores .94."""
    e = pa.analyse_file(os.path.join(ROOT, CROWD_JPG.lstrip('/')))
    assert e['face'] and e['score'] >= pa.SURE_SCORE
    assert e['ex'] == pytest.approx(0.41, abs=0.03) and e['ey'] < 0.1


@needs_cv
def test_haar_fallback_when_yunet_cannot_load(monkeypatch):
    monkeypatch.setattr(pa, 'MODEL_FILE', '/nonexistent/model.onnx')
    monkeypatch.setitem(pa._detector_state, 'yunet', None)
    monkeypatch.setitem(pa._detector_state, 'failed', False)
    e = pa.analyse_file(os.path.join(ROOT, FACE_PNG.lstrip('/')))
    assert e['detector'] == 'haar' and e['face']
    assert e['ex'] == pytest.approx(0.50, abs=0.05) and e['ey'] == pytest.approx(0.38, abs=0.06)


@needs_cv
def test_white_studio_backdrop_and_a_photo_without_one():
    from PIL import Image
    white = Image.open(os.path.join(ROOT, FACE_PNG.lstrip('/'))).convert('RGBA')
    bg = Image.new('RGBA', white.size, (255, 255, 255, 255))
    bg.alpha_composite(white)
    import io
    buf = io.BytesIO()
    bg.convert('RGB').save(buf, 'JPEG', quality=95)
    e = pa.analyse_image(buf.getvalue())
    assert not e['cut'] and e['backdrop'] == 'ko' and e['face']
    grey = Image.new('RGBA', white.size, (40, 40, 40, 255))
    grey.alpha_composite(white)
    buf = io.BytesIO()
    grey.convert('RGB').save(buf, 'JPEG', quality=95)
    assert pa.analyse_image(buf.getvalue())['backdrop'] is None


# ── without OpenCV ──────────────────────────────────────────────────────────

def test_without_opencv_nothing_is_measured_and_pages_get_none(store, monkeypatch):
    monkeypatch.setitem(sys.modules, 'cv2', None)            # `import cv2` now raises ImportError
    monkeypatch.setattr(pa, 'available', lambda: False)
    assert pa._cv() == (None, None)
    path = _persist(store, 'no-cv.png')
    assert pa.analyse_file(str(store / 'fighters' / 'no-cv.png')) is None
    assert pa.backfill(keys=[path])['error']
    assert not os.path.exists(pa.STORE_FILE)
    assert photos.photo_meta(path) is None                   # fallback geometry on the page
    assert pa.analyse_later(path) is False and pa.start_backfill() is False
    assert photos.photo_meta(FACE_PNG) is not None           # committed metadata needs no OpenCV


def test_a_broken_store_never_breaks_a_page(store):
    path = _persist(store, 'broken.png')
    with open(pa.STORE_FILE, 'w') as fh:
        fh.write('{not json')
    assert photos.photo_meta(path) is None
    with open(pa.STORE_FILE, 'w') as fh:
        json.dump({pa.path_key(path): 'nonsense'}, fh)
    assert photos.photo_meta(path) is None


# ── store and backfill ──────────────────────────────────────────────────────

@needs_cv
def test_store_round_trip_and_stale_files(store):
    path = _persist(store, 'fighter-a.png')
    assert photos.photo_meta(path) is None
    counts = pa.backfill(keys=[path])
    assert counts['measured'] == 1 and counts['faces'] == 1
    m = photos.photo_meta(path + '?v=123')
    _check_contract(m)
    assert m == photos.photo_meta(FACE_PNG)                  # same file, same numbers
    saved = json.load(open(pa.STORE_FILE))[path]
    assert saved['sha1'] and saved['size'] and saved['mtime']
    # a different photo saved under the same name: the old numbers are not used
    shutil.copy(os.path.join(ROOT, CROWD_JPG.lstrip('/')), store / 'fighters' / 'fighter-a.png')
    assert photos.photo_meta(path) is None and pa.needs_measuring(path)
    assert pa.backfill(keys=[path])['measured'] == 1
    assert photos.photo_meta(path)['w'] == 700


@needs_cv
def test_backfill_skips_photos_that_have_metadata(store, monkeypatch):
    a, b = _persist(store, 'a.png'), _persist(store, 'b.jpg', CROWD_JPG)
    first = pa.backfill()
    assert first['measured'] == 2 and first['skipped'] >= 885     # static/fighters: committed already
    monkeypatch.setattr(pa, 'analyse_image', lambda *a, **k: pytest.fail('measured again'))
    again = pa.backfill()
    assert again['measured'] == 0 and again['skipped'] == first['skipped'] + 2
    # same bytes, new mtime (a file copied or restored): kept, not measured again
    os.utime(store / 'fighters' / 'a.png', (1, 1))
    assert photos.photo_meta(a) is None
    assert pa.backfill()['unchanged'] == 1
    assert photos.photo_meta(a) is not None and photos.photo_meta(b) is not None


@needs_cv
def test_unreadable_file_is_recorded_and_not_retried(store, monkeypatch):
    with open(store / 'fighters' / 'bad.jpg', 'wb') as fh:
        fh.write(b'not an image')
    path = '/persisted-fighters/bad.jpg'
    assert pa.backfill(keys=[path])['failed'] == 1
    assert photos.photo_meta(path) is None
    assert not pa.needs_measuring(path)
    assert pa.backfill(keys=[path])['skipped'] == 1


@needs_cv
def test_override_applies_to_its_own_file_only(store, monkeypatch, tmp_path):
    path = _persist(store, 'curated.png')
    sha = hashlib.sha1(open(store / 'fighters' / 'curated.png', 'rb').read()).hexdigest()
    ov_file = tmp_path / 'overrides.json'
    ov_file.write_text(json.dumps({path: {'sha1': sha, 'x1': 0.6, 'crown': 0.02, 'why': 'test'}}))
    monkeypatch.setattr(pa, 'OVERRIDES_FILE', str(ov_file))
    pa.backfill(keys=[path])
    m = photos.photo_meta(path)
    assert m['x1'] == 0.6 and m['crown'] == 0.02 and m['x0'] == 0.0
    # an edited override is read at once, and the next backfill measures the photo again
    ov_file.write_text(json.dumps({path: {'sha1': sha, 'x1': 0.7, 'backdrop': 'lt', 'why': 'test'}}))
    os.utime(ov_file, (2e9, 2e9))
    assert photos.photo_meta(path)['x1'] == 0.7 and pa.needs_measuring(path)
    assert pa.backfill(keys=[path])['measured'] == 1
    assert photos.photo_meta(path)['backdrop'] == 'lt'
    # a replaced photo does not inherit the crop
    shutil.copy(os.path.join(ROOT, CROWD_JPG.lstrip('/')), store / 'fighters' / 'curated.png')
    pa.backfill(keys=[path])
    assert photos.photo_meta(path)['x1'] == 1.0


@needs_cv
def test_backfill_in_a_child_process(store):
    path = _persist(store, 'child.png')
    counts = pa.run_backfill(keys=[path], reason='test')
    assert counts['measured'] == 1 and not counts.get('error'), counts
    assert photos.photo_meta(path) is not None
    assert pa.read_job()['state'] == 'done'


# ── when it runs ────────────────────────────────────────────────────────────

def test_backfill_never_runs_on_the_calling_thread(store, monkeypatch):
    ran = {}
    done = threading.Event()

    def fake(keys=None, reason='', force=False):
        ran['thread'] = threading.current_thread()
        done.set()
        return {}
    monkeypatch.setattr(pa, 'available', lambda: True)
    monkeypatch.setattr(pa, 'run_backfill', fake)
    assert pa.start_backfill(reason='test') is True
    assert done.wait(5) and ran['thread'] is not threading.current_thread()


def test_a_page_missing_metadata_asks_for_one_backfill(store, monkeypatch):
    calls = []
    monkeypatch.setattr(pa, 'start_backfill', lambda reason='': calls.append(reason) or True)
    monkeypatch.setitem(pa._miss, 'last', 0.0)
    path = _persist(store, 'new.png')
    assert photos.photo_meta(path) is None
    assert photos.photo_meta(path) is None
    assert len(calls) == 1                                    # at most every MISS_INTERVAL
    monkeypatch.setitem(pa._miss, 'last', 0.0)
    photos.photo_meta('/persisted-fighters/not-on-disk.png')
    assert len(calls) == 1                                    # nothing to measure, nothing started


def test_saving_an_image_queues_its_measurement(data_dir, monkeypatch):
    queued = []
    monkeypatch.setattr(pa, 'analyse_later', lambda p: queued.append(p) or True)
    path = image_pipeline.store('Test Fighter', b'\xff\xd8 not really a jpeg', '.jpg')
    assert queued == [path] and path.startswith('/persisted-fighters/test-fighter.jpg?v=')


def test_debug_api_reports_and_starts(client, monkeypatch):
    started = []
    monkeypatch.setattr(pa, 'start_backfill', lambda reason='': started.append(reason) or True)
    r = client.get('/api/debug/state?token=t&part=photo_meta&path=' + FACE_PNG + '%3Fv%3D1')
    body = r.get_json()
    assert r.status_code == 200 and body['started'] is None and not started
    assert body['path']['key'] == FACE_PNG and body['path']['meta']['face'] is True
    assert body['static']['entries'] >= 885 and 'volume' in body
    body = client.get('/api/debug/state?token=t&part=photo_meta&start=1').get_json()
    assert body['started'] is True and started == ['debug API']


def test_each_scrape_starts_a_backfill(data_dir, monkeypatch):
    import pipeline
    started = []
    monkeypatch.setattr(pa, 'start_backfill', lambda reason='': started.append(reason) or True)
    monkeypatch.setattr(pipeline, '_scrape_all_sources', lambda: [{'fighter1': 'A', 'fighter2': 'B'}])
    assert pipeline._refresh_cache() == [{'fighter1': 'A', 'fighter2': 'B'}]
    assert started == ['after scrape']

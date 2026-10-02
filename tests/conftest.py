"""Test setup. DATA_DIR must point at a scratch directory before `app` is
imported, because app.py computes its file paths at import time."""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, 'tests', 'fixtures')
_SCRATCH = tempfile.mkdtemp(prefix='fs-tests-')
os.environ['DATA_DIR'] = _SCRATCH
os.environ['DEBUG_API_TOKEN'] = 't'
os.environ.pop('RESEND_API_KEY', None)
os.environ.pop('ANTHROPIC_API_KEY', None)
sys.path.insert(0, ROOT)

import pytest  # noqa: E402
import app as A  # noqa: E402

A.app.config['WTF_CSRF_ENABLED'] = False
A.ping_indexnow = lambda u: None
A.refresh_profiles = lambda *a, **k: None
A._maybe_start_profile_job = lambda f: None
_SEEDED = set(os.listdir(_SCRATCH))   # files app.py copies in at import; keep them


def fixture_path(name):
    return os.path.join(FIXTURES, name)


def read_fixture(name, mode='rb'):
    with open(fixture_path(name), mode) as fh:
        return fh.read()


def load_cache_fixture():
    with open(fixture_path('cache_2026-10-01.json'), encoding='utf-8') as fh:
        return json.load(fh)['fights']


@pytest.fixture
def data_dir():
    """A clean DATA_DIR for each test (seeded reference files are kept)."""
    for name in os.listdir(_SCRATCH):
        if name in _SEEDED:
            continue
        p = os.path.join(_SCRATCH, name)
        shutil.rmtree(p) if os.path.isdir(p) else os.unlink(p)
    yield _SCRATCH


@pytest.fixture
def fights():
    return [dict(f) for f in load_cache_fixture()]


@pytest.fixture
def seeded_cache(data_dir, fights):
    """DATA_DIR with the fixture written as a fresh cache; returns the fights."""
    import datetime
    A._runs.write_json_atomic(A.CACHE_FILE, {'timestamp': datetime.datetime.now().isoformat(), 'fights': fights})
    return fights


@pytest.fixture
def client(seeded_cache):
    return A.app.test_client()


class FakeResponse:
    def __init__(self, status, body, url='https://example.test/'):
        self.status_code, self.content, self.url = status, body, url

    def json(self):
        return json.loads(self.content)

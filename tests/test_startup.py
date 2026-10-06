"""The site must start even when the optional preview step fails."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_procfile_does_not_gate_the_server_on_previews():
    proc = open(os.path.join(ROOT, 'Procfile')).read()
    assert 'generate_previews.py &&' not in proc
    assert 'gunicorn app:app' in proc


def test_preview_script_exits_zero_when_it_fails(tmp_path):
    env = dict(os.environ, DATA_DIR=str(tmp_path), ANTHROPIC_API_KEY='', PYTHONPATH=ROOT,
               HTTPS_PROXY='http://127.0.0.1:9', HTTP_PROXY='http://127.0.0.1:9')
    r = subprocess.run([sys.executable, '-c',
                        'import runpy, app; app._refresh_cache = lambda wait=False: None; '
                        'runpy.run_path("generate_previews.py", run_name="__main__")'],
                       cwd=ROOT, env=env, capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode()[-800:]

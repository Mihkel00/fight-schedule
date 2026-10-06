"""The site must start even when the optional preview step fails."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_start_command_does_not_gate_the_server_on_previews():
    """Railway builds with Railpack; railpack.json is the one place the start
    command lives (no Procfile, no legacy nixpacks.toml)."""
    import json
    cfg = json.load(open(os.path.join(ROOT, 'railpack.json')))
    cmd = cfg['deploy']['startCommand']
    assert cfg['provider'] == 'python'
    assert 'generate_previews.py &&' not in cmd and 'gunicorn app:app' in cmd and '$PORT' in cmd
    for legacy in ('nixpacks.toml', 'Procfile'):
        assert not os.path.exists(os.path.join(ROOT, legacy)), legacy


def test_preview_script_exits_zero_when_it_fails(tmp_path):
    env = dict(os.environ, DATA_DIR=str(tmp_path), ANTHROPIC_API_KEY='', PYTHONPATH=ROOT,
               HTTPS_PROXY='http://127.0.0.1:9', HTTP_PROXY='http://127.0.0.1:9')
    r = subprocess.run([sys.executable, '-c',
                        'import runpy, app; app._refresh_cache = lambda wait=False: None; '
                        'runpy.run_path("generate_previews.py", run_name="__main__")'],
                       cwd=ROOT, env=env, capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode()[-800:]

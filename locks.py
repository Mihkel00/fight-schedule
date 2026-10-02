"""
Cross-process locks for background jobs.

The site runs 2 gunicorn workers; each has its own threads and in-memory
state, so a threading.Lock only stops duplicates *within* a worker. These
locks use flock on files in DATA_DIR, which every worker shares, so a job
(scrape, profile refresh, image job, page-version sync) runs in one place at
a time. flock is released automatically if the process dies.
"""

import logging
import os
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)
last_error = None   # set when flock itself fails (not "busy"); shown on /health

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))


@contextmanager
def job_lock(name, wait_seconds=0.0):
    """Yields True if this process got the lock, False if another holds it
    (after waiting up to wait_seconds)."""
    try:
        import fcntl
    except ImportError:          # non-POSIX dev machine: behave as unlocked
        yield True
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    fh = open(os.path.join(DATA_DIR, f'.{name}.lock'), 'a+')
    acquired = False
    deadline = time.time() + wait_seconds
    try:
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                # another worker holds it
                if time.time() >= deadline:
                    break
                time.sleep(0.5)
            except OSError as e:
                # flock is not supported here (unusual filesystem). Treating that
                # as "busy" would stop every job forever; run unlocked and say so.
                global last_error
                last_error = f'{name}: flock failed: {e}'
                logger.warning(last_error)
                acquired = True
                break
        yield acquired
    finally:
        if acquired:
            try:
                fcntl.flock(fh, fcntl.LOCK_UN)
            except OSError:
                pass
        fh.close()

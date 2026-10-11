"""
Flask app object, data directory, start-up seeding, logging, admin wiring.

Moved out of app.py unchanged (2026-10); app.py imports every module so
the routes register on the one Flask app.
"""
from dotenv import load_dotenv

# Before every other import: admin_setup_simple reads ADMIN_PASSWORD and
# ADMIN_PASSWORD_HASH from the environment when it is imported.
load_dotenv()  # Load environment variables from .env file

import logging  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
from admin_setup_simple import setup_admin  # noqa: E402
from datetime import datetime  # noqa: E402
from flask import Flask, redirect, request, session  # noqa: E402
from flask_compress import Compress  # noqa: E402
from functools import wraps  # noqa: E402
from logging.handlers import RotatingFileHandler  # noqa: E402


# ============================================================================
# PERSISTENT DATA DIRECTORY
# ============================================================================
# On Railway: mount a persistent volume at /data and set DATA_DIR=/data
# Locally: defaults to ./data (relative to project root)
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))


def data_path(filename):
    """Get full path for a file in the persistent data directory"""
    return os.path.join(DATA_DIR, filename)


def _seed_data_files():
    """
    On first deploy, copy git-tracked seed files into DATA_DIR if they
    don't already exist there. This ensures a fresh Railway volume gets
    populated with the initial fighter databases and config.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, 'logs'), exist_ok=True)

    project_root = os.path.dirname(os.path.abspath(__file__))

    # Files to seed: (source relative to project root, dest relative to DATA_DIR)
    seed_files = [
        ('fighters.json', 'fighters.json'),
        ('fighters_ufc.json', 'fighters_ufc.json'),
        ('time_overrides.json', 'time_overrides.json'),
        ('data/big_name_fighters.json', 'big_name_fighters.json'),
        ('data/fight_previews.json', 'fight_previews.json'),
    ]

    for src_rel, dest_rel in seed_files:
        src = os.path.join(project_root, src_rel)
        dest = data_path(dest_rel)
        if not os.path.exists(dest) and os.path.exists(src):
            shutil.copy2(src, dest)
            print(f"[SEED] Copied {src_rel} → {dest}")


_seed_data_files()


app = Flask(__name__)


app.config['UPLOAD_FOLDER'] = 'static/fighters'


app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max file size


app.config['DATA_DIR'] = DATA_DIR  # Make available to admin views


Compress(app)  # Enable gzip compression for all responses


@app.context_processor
def inject_current_date():
    now = datetime.now()
    month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']
    return {
        'current_year': now.year,
        'current_month_year': f"{month_names[now.month - 1]} {now.year}"
    }


# Setup Flask-Admin
admin = setup_admin(app)


def admin_required(f):
    """Require the Flask-Admin session login for app-level /admin/* routes."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('admin_authenticated'):
            return redirect('/admin/')
        return f(*args, **kwargs)
    return wrapper


@app.before_request
def redirect_www():
    """Redirect www to non-www for canonical URLs"""
    if request.host.startswith('www.'):
        return redirect(request.url.replace('www.', '', 1), code=301)


# ============================================================================
# LOGGING SETUP
# ============================================================================
# Create logs directory if it doesn't exist
log_dir = os.path.join(DATA_DIR, 'logs')


os.makedirs(log_dir, exist_ok=True)


# Set up logging to both file and console
logger = logging.getLogger('fight_schedule')


logger.setLevel(logging.DEBUG)


# File handler (rotates at 10MB, keeps 3 backup files)
file_handler = RotatingFileHandler(os.path.join(log_dir, 'app.log'), maxBytes=10*1024*1024, backupCount=3)


file_handler.setLevel(logging.DEBUG)


# Console handler (shows in terminal)
console_handler = logging.StreamHandler()


console_handler.setLevel(logging.INFO)  # Only show INFO+ in console


# Format: [2025-01-15 14:30:45] INFO: Message here
formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')


file_handler.setFormatter(formatter)


console_handler.setFormatter(formatter)


# Add handlers to logger
logger.addHandler(file_handler)


logger.addHandler(console_handler)


logger.info("="*70)


logger.info("FIGHT SCHEDULE APP STARTING")


logger.info("="*70)

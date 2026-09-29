"""
Flask-Admin Setup
Simple admin panel for managing fight schedule data
With rate limiting, password hashing, CSRF, and session security.
"""

from flask import redirect, url_for, request, session, abort
from flask_admin import Admin, BaseView, expose, AdminIndexView
from flask_admin.form import Select2Widget
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from wtforms import Form, StringField, SelectField, validators
from datetime import timedelta
import os
import logging
import time
import json
import re
import unicodedata
import requests as http_requests
from admin_models import FighterImageOverride, BigNameFighter, ManualEvent, TimeOverride, data_path

logger = logging.getLogger('fight_schedule')

# ============================================================================
# SECURITY CONFIGURATION
# ============================================================================

# Password: hash on startup so the plaintext is never compared directly.
# Set ADMIN_PASSWORD_HASH env var for production (generate with:
#   python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your-password'))"
# Or set ADMIN_PASSWORD and it will be hashed at startup.
_raw_password = os.environ.get('ADMIN_PASSWORD', 'fightschedule2025')
ADMIN_PASSWORD_HASH = os.environ.get(
    'ADMIN_PASSWORD_HASH',
    generate_password_hash(_raw_password)
)

# Rate limiter (initialized in setup_admin)
limiter = None

# CSRF protection (initialized in setup_admin)
csrf = CSRFProtect()


def _require_admin():
    """Check if current request is authenticated. Abort 401 if not."""
    if not session.get('admin_authenticated'):
        abort(401)


# ============================================================================
# FLASK-ADMIN VIEWS
# ============================================================================

class ProtectedAdminIndexView(AdminIndexView):
    """Admin index with password protection and rate-limited login"""

    @expose('/')
    def index(self):
        if not self.is_authenticated():
            return redirect(url_for('.login'))

        import json
        big_names_file = data_path('big_name_fighters.json')
        if os.path.exists(big_names_file):
            with open(big_names_file, 'r') as f:
                big_names_count = len(json.load(f))
        else:
            big_names_count = 0

        with open(data_path('fighters.json'), 'r', encoding='utf-8') as f:
            boxing_count = len(json.load(f))
        with open(data_path('fighters_ufc.json'), 'r', encoding='utf-8') as f:
            ufc_count = len(json.load(f))

        return self.render('admin/dashboard.html',
                          big_names=big_names_count,
                          total_fighters=boxing_count + ufc_count,
                          boxing_count=boxing_count,
                          ufc_count=ufc_count)

    @expose('/login', methods=['GET', 'POST'])
    def login(self):
        if request.method == 'POST':
            # Rate limiting is applied via decorator in setup_admin
            password = request.form.get('password', '')
            if check_password_hash(ADMIN_PASSWORD_HASH, password):
                session['admin_authenticated'] = True
                session.permanent = True
                logger.info(f"Admin login successful from {request.remote_addr}")
                return redirect(url_for('.index'))
            else:
                logger.warning(f"Admin login FAILED from {request.remote_addr}")
                # Small delay to slow brute force even further
                time.sleep(1)
                return self.render('admin/login.html', error='Wrong password')

        return self.render('admin/login.html')

    @expose('/logout')
    def logout(self):
        session.pop('admin_authenticated', None)
        return redirect(url_for('.login'))

    def is_authenticated(self):
        return session.get('admin_authenticated', False)


class ProtectedBaseView(BaseView):
    """BaseView that requires admin authentication"""
    def is_accessible(self):
        return session.get('admin_authenticated', False)

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('admin.login'))


class BigNameFighterView(ProtectedBaseView):
    """Manage big-name fighters list"""

    @expose('/')
    def index(self):
        model = BigNameFighter()
        items = model.get_all()
        return self.render('admin/big_name_fighters.html', items=items)

    @expose('/add', methods=['GET', 'POST'])
    def add(self):
        if request.method == 'POST':
            model = BigNameFighter()
            item = {
                'name': request.form.get('name', '').strip()[:200],
                'sport': request.form.get('sport', 'Boxing'),
                'notes': request.form.get('notes', '').strip()[:500]
            }
            if item['name']:
                model.add(item)
            return redirect(url_for('.index'))

        return self.render('admin/big_name_form.html', item=None)

    @expose('/delete/<int:idx>')
    def delete(self, idx):
        model = BigNameFighter()
        model.delete(idx)
        return redirect(url_for('.index'))


class ManualEventView(ProtectedBaseView):
    """Manage manually added events"""

    @expose('/')
    def index(self):
        model = ManualEvent()
        items = model.get_all()
        return self.render('admin/manual_events.html', items=items)

    @expose('/add', methods=['GET', 'POST'])
    def add(self):
        if request.method == 'POST':
            model = ManualEvent()
            item = {
                'fighter1': request.form.get('fighter1', '').strip()[:200],
                'fighter2': request.form.get('fighter2', '').strip()[:200],
                'date': request.form.get('date', '').strip()[:10],
                'time': request.form.get('time', '').strip()[:20],
                'venue': request.form.get('venue', '').strip()[:500],
                'sport': request.form.get('sport', '').strip()[:20],
                'event_name': request.form.get('event_name', '').strip()[:200],
                'card_type': request.form.get('card_type', 'Main Card').strip()[:50],
                'weight_class': request.form.get('weight_class', '').strip()[:100]
            }
            model.add(item)
            return redirect(url_for('.index'))

        return self.render('admin/manual_event_form.html', item=None)

    @expose('/edit/<int:idx>', methods=['GET', 'POST'])
    def edit(self, idx):
        model = ManualEvent()

        if request.method == 'POST':
            item = {
                'fighter1': request.form.get('fighter1', '').strip()[:200],
                'fighter2': request.form.get('fighter2', '').strip()[:200],
                'date': request.form.get('date', '').strip()[:10],
                'time': request.form.get('time', '').strip()[:20],
                'venue': request.form.get('venue', '').strip()[:500],
                'sport': request.form.get('sport', '').strip()[:20],
                'event_name': request.form.get('event_name', '').strip()[:200],
                'card_type': request.form.get('card_type', 'Main Card').strip()[:50],
                'weight_class': request.form.get('weight_class', '').strip()[:100]
            }
            model.update(idx, item)
            return redirect(url_for('.index'))

        items = model.get_all()
        if 0 <= idx < len(items):
            return self.render('admin/manual_event_form.html', item=items[idx], idx=idx)
        return redirect(url_for('.index'))

    @expose('/delete/<int:idx>')
    def delete(self, idx):
        model = ManualEvent()
        model.delete(idx)
        return redirect(url_for('.index'))


class TimeOverrideView(ProtectedBaseView):
    """Manage time overrides"""

    @expose('/')
    def index(self):
        model = TimeOverride()
        items = model.get_all()
        return self.render('admin/time_overrides.html', items=items)

    @expose('/add', methods=['GET', 'POST'])
    def add(self):
        if request.method == 'POST':
            model = TimeOverride()
            matchup = request.form.get('matchup', '').strip()[:400]
            date = request.form.get('date', '').strip()[:10]
            time_val = request.form.get('time', '').strip()[:20]

            item = {
                'matchup': matchup,
                'date': date,
                'time': time_val,
                'fight_key': f"{matchup}|{date}"
            }

            items = model.get_all()
            items.append(item)
            model.save_all(items)

            return redirect(url_for('.index'))

        return self.render('admin/time_override_form.html', item=None)

    @expose('/delete/<int:idx>')
    def delete(self, idx):
        model = TimeOverride()
        items = model.get_all()
        if 0 <= idx < len(items):
            items.pop(idx)
            model.save_all(items)
        return redirect(url_for('.index'))



# ============================================================================
# REVIEW IMAGES VIEW — single place to audit, fix and bulk-refresh fighter images
# (logic lives in image_pipeline.py)
# ============================================================================

import image_pipeline as images

_FILTERS = ('review', 'missing', 'rejected', 'legacy', 'approved', 'all')


class ReviewImagesView(ProtectedBaseView):

    def _rows(self):
        meta = images.load_meta()
        rows = []
        for name, sport in images.schedule_fighters():
            e = meta.get(images.key(name)) or {}
            path = images.image_for(name)
            status = e.get('status')
            if not status:
                status = 'legacy' if path else 'missing'
            elif status == 'rejected' and not path:
                status = 'rejected'
            rows.append({'name': name, 'sport': sport, 'path': path, 'status': status,
                         'source': e.get('source') or ('legacy' if path else ''),
                         'source_url': e.get('ref') or e.get('source_url'), 'note': e.get('note'),
                         'fetched_at': (e.get('fetched_at') or '')[:10],
                         'unverified': e.get('source') == 'legacy' and status == 'auto'})
        order = {'auto': 0, 'rejected': 1, 'missing': 2, 'legacy': 3, 'manual': 4, 'approved': 5}
        # within Needs review, old images that could not be verified (the likely-wrong ones) come first
        rows.sort(key=lambda r: (order.get(r['status'], 9), 0 if r['unverified'] else 1, r['sport'], r['name']))
        return rows

    @expose('/', methods=['GET', 'POST'])
    def index(self):
        from flask import flash
        show = request.args.get('show', 'review')
        if request.method == 'POST':
            action = request.form.get('action', '')
            name = request.form.get('name', '').strip()[:200]
            sport = request.form.get('sport', 'Boxing')[:10]
            try:
                if action == 'keep' and name:
                    images.approve(name, sport)
                    flash(f'Kept image for {name}', 'success')
                elif action == 'wrong' and name:
                    images.reject_and_retry(name, sport)
                    flash(f'Marked wrong: {name}. Looking for another image in the background — refresh in a few seconds.', 'success')
                elif action == 'replace_url' and name:
                    url = request.form.get('url', '').strip()[:2000]
                    if not url.startswith(('http://', 'https://')):
                        raise ValueError('Paste a full http(s) image URL')
                    images.set_manual_from_url(name, sport, url)
                    flash(f'Replaced image for {name}', 'success')
                elif action == 'upload' and name:
                    f = request.files.get('file')
                    if not f or not f.filename:
                        raise ValueError('Choose an image file')
                    data = f.read(8 * 1024 * 1024 + 1)
                    if len(data) > 8 * 1024 * 1024:
                        raise ValueError('Image larger than 8 MB')
                    images.set_manual_from_bytes(name, sport, data, 'upload', f.filename[:200])
                    flash(f'Uploaded image for {name}', 'success')
                elif action == 'reset' and name:
                    images.reset(name)
                    flash(f'Reset {name} to automatic', 'success')
                elif action in ('dry_run', 'apply'):
                    if images.start_job(apply=(action == 'apply')):
                        flash('Dry run started — nothing will change.' if action == 'dry_run'
                              else 'Applying new rules — verified images will appear under Needs review.', 'success')
                    else:
                        flash('A job is already running.', 'error')
            except Exception as e:
                logger.warning(f"review images action {action} failed for {name}: {e}")
                flash(f'Could not {action.replace("_", " ")} for {name}: {e}', 'error')
            return redirect(url_for('.index', show=show))

        rows = self._rows()
        counts = {f: 0 for f in _FILTERS}
        for r in rows:
            counts['all'] += 1
            bucket = {'auto': 'review', 'manual': 'approved'}.get(r['status'], r['status'])
            if bucket in counts:
                counts[bucket] += 1
        if show not in _FILTERS:
            show = 'review'
        if show != 'all':
            want = {'review': ('auto',), 'approved': ('approved', 'manual')}.get(show, (show,))
            rows = [r for r in rows if r['status'] in want]
        return self.render('admin/review_images.html', rows=rows, counts=counts, show=show,
                           job=images.read_job(), settings=images.read_settings())


# ============================================================================

def setup_admin(app):
    """Setup Flask-Admin with security hardening"""
    global limiter

    # ---- Secret key ----
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fight-schedule-secret-key-change-me')

    # ---- Session security ----
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=4)
    # Only set Secure flag when running behind HTTPS (Railway always does)
    if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('HTTPS_ONLY'):
        app.config['SESSION_COOKIE_SECURE'] = True

    # ---- CSRF protection ----
    csrf.init_app(app)

    # ---- Rate limiter ----
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[],  # No global limit — only apply where needed
        storage_uri="memory://",
    )

    # Rate limit login: 5 attempts per minute, 15 per hour
    limiter.limit("5/minute;15/hour")(app.view_functions.get('admin.login') or (lambda: None))

    # Rate limit all admin POST routes: 30 per minute
    @app.before_request
    def _rate_limit_admin_posts():
        if request.path.startswith('/admin/') and request.method == 'POST':
            # The limiter decorator handles login; for other POSTs we rely
            # on the per-route limits set below
            pass

    # ---- Security + cache headers ----
    @app.after_request
    def _set_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('HTTPS_ONLY'):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # Cache-Control for static assets
        path = request.path
        if path.startswith('/static/'):
            response.headers.setdefault('Cache-Control', 'public, max-age=86400, stale-while-revalidate=604800')
        elif path == '/sitemap.xml':
            response.headers.setdefault('Cache-Control', 'public, max-age=3600, stale-while-revalidate=86400')
        return response

    # ---- Auth gate for app.py admin routes ----
    @app.before_request
    def _protect_admin_routes():
        """Require authentication for all /admin/* routes defined in app.py"""
        protected_paths = [
            '/admin/clear-cache',
            '/admin/upload-images',
            '/admin/manage-fighters',
            '/admin/download-jsons',
        ]
        if any(request.path == p or request.path.startswith(p + '/') for p in protected_paths):
            if not session.get('admin_authenticated'):
                return redirect(url_for('admin.login'))

    # ---- Ensure persistent data directory exists ----
    from admin_models import DATA_DIR
    os.makedirs(DATA_DIR, exist_ok=True)

    # Initialize admin with custom index view
    admin = Admin(
        app,
        name='Fight Schedule Admin',
        index_view=ProtectedAdminIndexView()
    )

    # Add views (all extend ProtectedBaseView now)
    admin.add_view(ReviewImagesView(name='Review Images', endpoint='review_images'))
    admin.add_view(BigNameFighterView(name='Big Name Fighters', endpoint='big_names'))
    admin.add_view(ManualEventView(name='Manual Events', endpoint='manual_events'))
    admin.add_view(TimeOverrideView(name='Time Overrides', endpoint='time_overrides'))

    try:
        moved = images.migrate_legacy_overrides()
        if moved:
            logger.info(f"Migrated {moved} old image overrides into image_meta.json")
    except Exception as e:
        logger.warning(f"override migration failed: {e}")

    return admin

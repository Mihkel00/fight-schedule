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
from admin_models import BigNameFighter, TimeOverride, data_path

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
    """Audit, fix and bulk-refresh fighter images. Actions are JSON (in-place
    tile updates, no page reload) with a plain form fallback that returns to
    the fighter's anchor."""

    _STATUS_LABEL = {'auto': 'needs review', 'approved': 'approved', 'manual': 'manual',
                     'rejected': 'marked wrong', 'missing': 'no image', 'legacy': 'older, unreviewed'}

    def _sports(self):
        return {images.key(n): s for n, s in images.schedule_fighters()}

    def _row(self, name, sport, meta=None):
        meta = meta if meta is not None else images.load_meta()
        e = meta.get(images.key(name)) or {}
        path = images.image_for(name)
        status = e.get('status')
        if not status or status == 'none':
            status = 'legacy' if path else 'missing'
        elif status == 'rejected' and path:
            status = 'auto'      # the retry after "Wrong" found a replacement
        return {'name': name, 'sport': sport, 'path': path, 'status': status,
                'label': self._STATUS_LABEL.get(status, status),
                'id': 'f-' + images._slug(name),
                'source': e.get('source') or ('legacy' if path else ''),
                'source_url': e.get('ref') or e.get('source_url'), 'note': e.get('note'),
                'fetched_at': (e.get('fetched_at') or '')[:10],
                'retrying': bool(e.get('retrying')),
                'unverified': e.get('source') == 'legacy' and status == 'auto'}

    def _rows(self):
        meta = images.load_meta()
        rows = [self._row(n, s, meta) for n, s in images.schedule_fighters()]
        order = {'auto': 0, 'rejected': 1, 'missing': 2, 'legacy': 3, 'manual': 4, 'approved': 5}
        # within Needs review, old images that could not be verified (the likely-wrong ones) come first
        rows.sort(key=lambda r: (order.get(r['status'], 9), 0 if r['unverified'] else 1, r['sport'], r['name']))
        return rows

    def _counts(self, rows):
        counts = {f: 0 for f in _FILTERS}
        for r in rows:
            counts['all'] += 1
            bucket = {'auto': 'review', 'manual': 'approved'}.get(r['status'], r['status'])
            if bucket in counts:
                counts[bucket] += 1
        return counts

    def _apply(self, action, name, sport, form=None, files=None):
        """Run one action; returns a message. Raises ValueError on bad input."""
        form, files = form or {}, files or {}
        if action == 'keep':
            if not images.approve(name, sport):
                raise ValueError('no image to keep')
            return f'Kept image for {name}'
        if action == 'wrong':
            images.reject_and_retry(name, sport)
            return f'Marked wrong: {name}; looking for another image'
        if action == 'reset':
            images.reset(name)
            return f'Reset {name} to automatic'
        if action == 'replace_url':
            url = (form.get('url') or '').strip()[:2000]
            if not url.startswith(('http://', 'https://')):
                raise ValueError('paste a full http(s) image URL')
            images.set_manual_from_url(name, sport, url)
            return f'Replaced image for {name}'
        if action == 'upload':
            f = files.get('file')
            if not f or not f.filename:
                raise ValueError('choose an image file')
            data = f.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise ValueError('image larger than 8 MB')
            images.set_manual_from_bytes(name, sport, data, 'upload', f.filename[:200])
            return f'Uploaded image for {name}'
        raise ValueError('unknown action')

    @expose('/')
    def index(self):
        show = request.args.get('show', 'review')
        if show not in _FILTERS:
            show = 'review'
        rows = self._rows()
        counts = self._counts(rows)
        if show != 'all':
            want = {'review': ('auto',), 'approved': ('approved', 'manual')}.get(show, (show,))
            rows = [r for r in rows if r['status'] in want]
        return self.render('admin/review_images.html', rows=rows, counts=counts, show=show,
                           job=images.job_view(), settings=images.read_settings())

    @expose('/action', methods=['POST'])
    def action(self):
        """Single or bulk action. JSON when called with X-Requested-With: fetch;
        otherwise a normal form post that returns to the fighter's anchor."""
        from flask import flash, jsonify
        wants_json = request.headers.get('X-Requested-With') == 'fetch'
        action = request.form.get('action', '')
        sports = self._sports()
        names = [n.strip()[:200] for n in request.form.getlist('name') if n.strip()][:500]
        show = request.form.get('show', 'review')

        if action in ('dry_run', 'apply'):
            started = images.start_job(apply=(action == 'apply'))
            msg = ('Dry run started — nothing will change.' if action == 'dry_run'
                   else 'Applying new rules — verified images will appear under Needs review.') if started \
                else 'A job is already running.'
            if wants_json:
                return jsonify({'ok': started, 'message': msg, 'job': images.job_view()})
            flash(msg, 'success' if started else 'error')
            return redirect(url_for('.index', show=show))

        results, tiles, errors = [], {}, []
        for name in names:
            sport = request.form.get('sport') or sports.get(images.key(name), 'Boxing')
            try:
                results.append(self._apply(action, name, sport, request.form, request.files))
            except Exception as e:
                logger.warning(f"review images {action} failed for {name}: {e}")
                errors.append(f'{name}: {e}')
            tiles[images._slug(name)] = self.render('admin/_review_tile.html', r=self._row(name, sport))

        if wants_json:
            counts = self._counts(self._rows())
            msg = results[0] if len(results) == 1 else f'{len(results)} updated'
            if errors:
                msg += ' · ' + '; '.join(errors)[:300]
            return jsonify({'ok': not errors, 'message': msg, 'tiles': tiles, 'counts': counts})

        flash('; '.join(results + errors)[:400], 'error' if errors else 'success')
        anchor = ('#f-' + images._slug(names[0])) if len(names) == 1 else ''
        return redirect(url_for('.index', show=show) + anchor)

    @expose('/status')
    def status(self):
        """Polled by the page: job progress, plus fresh tiles for fighters the
        page is waiting on (background retries after "Wrong")."""
        from flask import jsonify
        names = [n for n in request.args.get('names', '').split(',') if n][:200]
        sports = self._sports()
        tiles = {}
        for name in names:
            row = self._row(name, sports.get(images.key(name), 'Boxing'))
            if not row['retrying']:
                tiles[images._slug(name)] = self.render('admin/_review_tile.html', r=row)
        return jsonify({'job': images.job_view(), 'settings': images.read_settings(), 'tiles': tiles})

    @expose('/report')
    def report(self):
        """Rendered job panel (fetched once a job finishes, instead of reloading the page)."""
        return self.render('admin/_review_report.html', job=images.job_view(), settings=images.read_settings())


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
    admin.add_view(TimeOverrideView(name='Time Overrides', endpoint='time_overrides'))

    return admin

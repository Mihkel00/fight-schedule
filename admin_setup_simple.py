"""
Flask-Admin Setup
Simple admin panel for managing fight schedule data
"""

from flask import redirect, url_for, request, session
from flask_admin import Admin, BaseView, expose, AdminIndexView
from flask_admin.form import Select2Widget
from wtforms import Form, StringField, SelectField, validators
import os
import logging
from admin_models import FighterImageOverride, BigNameFighter, ManualEvent, TimeOverride

# Simple password protection (you can change this password)
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'fightschedule2025')


class ProtectedAdminIndexView(AdminIndexView):
    """Admin index with password protection"""
    
    @expose('/')
    def index(self):
        # Check if authenticated
        if not self.is_authenticated():
            return redirect(url_for('.login'))
        return super(ProtectedAdminIndexView, self).index()
    
    @expose('/login', methods=['GET', 'POST'])
    def login(self):
        if request.method == 'POST':
            password = request.form.get('password')
            if password == ADMIN_PASSWORD:
                # Set session flag
                session['admin_authenticated'] = True
                return redirect(url_for('.index'))
            else:
                return self.render('admin/login.html', error='Wrong password')
        
        return self.render('admin/login.html')
    
    def is_authenticated(self):
        """Check if user is authenticated"""
        return session.get('admin_authenticated', False)


class FighterImageView(BaseView):
    """Manage fighter image overrides"""
    
    @expose('/')
    def index(self):
        model = FighterImageOverride()
        items = model.get_all()
        return self.render('admin/fighter_images.html', items=items)
    
    @expose('/add', methods=['GET', 'POST'])
    def add(self):
        if request.method == 'POST':
            model = FighterImageOverride()
            item = {
                'fighter_name': request.form.get('fighter_name'),
                'image_url': request.form.get('image_url'),
                'sport': request.form.get('sport', 'Boxing')
            }
            model.add(item)
            return redirect(url_for('.index'))
        
        return self.render('admin/fighter_image_form.html', item=None)
    
    @expose('/edit/<int:idx>', methods=['GET', 'POST'])
    def edit(self, idx):
        model = FighterImageOverride()
        
        if request.method == 'POST':
            item = {
                'fighter_name': request.form.get('fighter_name'),
                'image_url': request.form.get('image_url'),
                'sport': request.form.get('sport', 'Boxing')
            }
            model.update(idx, item)
            return redirect(url_for('.index'))
        
        items = model.get_all()
        if 0 <= idx < len(items):
            return self.render('admin/fighter_image_form.html', item=items[idx], idx=idx)
        return redirect(url_for('.index'))
    
    @expose('/delete/<int:idx>')
    def delete(self, idx):
        model = FighterImageOverride()
        model.delete(idx)
        return redirect(url_for('.index'))


class BigNameFighterView(BaseView):
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
                'name': request.form.get('name'),
                'sport': request.form.get('sport', 'Boxing'),
                'notes': request.form.get('notes', '')
            }
            model.add(item)
            return redirect(url_for('.index'))
        
        return self.render('admin/big_name_form.html', item=None)
    
    @expose('/delete/<int:idx>')
    def delete(self, idx):
        model = BigNameFighter()
        model.delete(idx)
        return redirect(url_for('.index'))


class ManualEventView(BaseView):
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
                'fighter1': request.form.get('fighter1'),
                'fighter2': request.form.get('fighter2'),
                'date': request.form.get('date'),
                'time': request.form.get('time'),
                'venue': request.form.get('venue'),
                'sport': request.form.get('sport'),
                'event_name': request.form.get('event_name'),
                'card_type': request.form.get('card_type', 'Main Card'),
                'weight_class': request.form.get('weight_class', '')
            }
            model.add(item)
            return redirect(url_for('.index'))
        
        return self.render('admin/manual_event_form.html', item=None)
    
    @expose('/edit/<int:idx>', methods=['GET', 'POST'])
    def edit(self, idx):
        model = ManualEvent()
        
        if request.method == 'POST':
            item = {
                'fighter1': request.form.get('fighter1'),
                'fighter2': request.form.get('fighter2'),
                'date': request.form.get('date'),
                'time': request.form.get('time'),
                'venue': request.form.get('venue'),
                'sport': request.form.get('sport'),
                'event_name': request.form.get('event_name'),
                'card_type': request.form.get('card_type', 'Main Card'),
                'weight_class': request.form.get('weight_class', '')
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


class TimeOverrideView(BaseView):
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
            matchup = request.form.get('matchup')
            date = request.form.get('date')
            time = request.form.get('time')
            
            item = {
                'matchup': matchup,
                'date': date,
                'time': time,
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


class MissingFighterImagesView(BaseView):
    """View and add missing fighter images"""
    
    @expose('/', methods=['GET', 'POST'])
    def index(self):
        if request.method == 'POST':
            import logging
            # Save submitted images
            saved = 0
            logger = logging.getLogger(__name__)
            
            for key, value in request.form.items():
                if key.startswith('image_') and value.strip():
                    fighter_name = key.replace('image_', '').replace('_', ' ')
                    sport = request.form.get(f'sport_{key.replace("image_", "")}')
                    
                    logger.info(f"Attempting to save: {fighter_name} = {value[:50]}... (Sport: {sport})")
                    
                    # Save to appropriate JSON file
                    if self.save_fighter_image(fighter_name, value.strip(), sport):
                        saved += 1
                        logger.info(f"✓ Saved: {fighter_name}")
            
            from flask import flash
            logger.info(f"Total saved: {saved}")
            flash(f'Updated {saved} fighter images', 'success')
            return redirect(url_for('.index'))
        
        # Get all fighters
        fighters_data = self.get_all_fighters()
        
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Missing fighters: {len(fighters_data['missing'])}")
        logger.info(f"Existing fighters: {len(fighters_data['existing'])}")
        
        return self.render('admin/missing_fighter_images.html', 
                         missing_fighters=fighters_data['missing'],
                         existing_fighters=fighters_data['existing'])
    
    def get_all_fighters(self):
        """Get all fighters split into missing and existing images"""
        import json
        import logging
        from collections import defaultdict
        
        logger = logging.getLogger(__name__)
        
        # Load databases from root directory
        fighters_db = {}
        try:
            with open('fighters.json', 'r') as f:
                fighters_db.update(json.load(f))
        except: pass
        try:
            with open('fighters_ufc.json', 'r') as f:
                fighters_db.update(json.load(f))
        except: pass
        
        # Get fights
        import os
        cache_path = 'fights_cache.json'  # Cache is in root directory
        logger = logging.getLogger(__name__)
        
        if not os.path.exists(cache_path):
            logger.warning(f"Cache file not found: {cache_path}")
            return {'missing': {}, 'existing': {}}
        
        try:
            with open(cache_path, 'r') as f:
                cache_data = json.load(f)
                fights = cache_data.get('fights', [])
                logger.info(f"Loaded {len(fights)} fights from cache")
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
            return {'missing': {}, 'existing': {}}
        
        # Collect all fighters
        all_fighters = defaultdict(lambda: {'count': 0, 'sport': '', 'example': '', 'image_url': None})
        for fight in fights:
            for fighter in [fight.get('fighter1'), fight.get('fighter2')]:
                if fighter and fighter != 'TBA':
                    all_fighters[fighter]['count'] += 1
                    all_fighters[fighter]['sport'] = fight.get('sport')
                    if not all_fighters[fighter]['example']:
                        all_fighters[fighter]['example'] = f"{fight['fighter1']} vs {fight['fighter2']}"
                    # Add image URL if exists
                    if fighter in fighters_db:
                        all_fighters[fighter]['image_url'] = fighters_db.get(fighter)
        
        # Split into missing and existing
        missing = {k: v for k, v in all_fighters.items() if not v['image_url']}
        existing = {k: v for k, v in all_fighters.items() if v['image_url']}
        
        # Sort by count (most appearances first)
        missing = dict(sorted(missing.items(), key=lambda x: x[1]['count'], reverse=True))
        existing = dict(sorted(existing.items(), key=lambda x: x[1]['count'], reverse=True))
        
        return {'missing': missing, 'existing': existing}
    
    def save_fighter_image(self, fighter_name, image_url, sport):
        """Save fighter image to JSON"""
        import json
        
        # Save to root directory where app.py loads from
        file = 'fighters_ufc.json' if sport == 'UFC' else 'fighters.json'
        
        try:
            with open(file, 'r') as f:
                db = json.load(f)
        except:
            db = {}
        
        db[fighter_name] = image_url
        
        with open(file, 'w') as f:
            json.dump(db, f, indent=2)
        
        return True


def setup_admin(app):
    """Setup Flask-Admin with all views"""
    
    # Set secret key for session management
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fight-schedule-secret-key-change-me')
    
    # Create data directory if it doesn't exist
    os.makedirs('data', exist_ok=True)
    
    # Initialize admin with custom index view (password protected)
    admin = Admin(
        app,
        name='Fight Schedule Admin',
        index_view=ProtectedAdminIndexView()
    )
    
    # Add views
    admin.add_view(MissingFighterImagesView(name='Missing Images', endpoint='missing_images'))
    admin.add_view(FighterImageView(name='Fighter Images', endpoint='fighter_images'))
    admin.add_view(BigNameFighterView(name='Big Name Fighters', endpoint='big_names'))
    admin.add_view(ManualEventView(name='Manual Events', endpoint='manual_events'))
    admin.add_view(TimeOverrideView(name='Time Overrides', endpoint='time_overrides'))
    
    return admin

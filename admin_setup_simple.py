"""
Flask-Admin Setup - Simplified with Auto-Generated Views
No custom templates needed
"""

from flask import redirect, url_for, request, session
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.fileadmin import FileAdmin
import os
import json

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'fightschedule2025')


class SecureAdminIndexView(AdminIndexView):
    """Password-protected admin dashboard"""
    
    @expose('/')
    def index(self):
        if not session.get('admin_authenticated'):
            return redirect(url_for('.login'))
        
        # Load data for dashboard
        stats = self.get_stats()
        return self.render('admin/dashboard.html', **stats)
    
    @expose('/login', methods=['GET', 'POST'])
    def login(self):
        if request.method == 'POST':
            if request.form.get('password') == ADMIN_PASSWORD:
                session['admin_authenticated'] = True
                return redirect(url_for('.index'))
            return self.render('admin/login.html', error='Wrong password')
        return self.render('admin/login.html')
    
    @expose('/logout')
    def logout(self):
        session.pop('admin_authenticated', None)
        return redirect(url_for('.login'))
    
    def get_stats(self):
        """Get dashboard statistics"""
        stats = {
            'big_names': 0,
            'overrides': 0,
            'manual_events': 0,
            'time_overrides': 0
        }
        
        try:
            with open('data/big_name_fighters.json', 'r') as f:
                stats['big_names'] = len(json.load(f))
        except: pass
        
        try:
            with open('data/fighter_image_overrides.json', 'r') as f:
                stats['overrides'] = len(json.load(f))
        except: pass
        
        try:
            with open('data/manual_events.json', 'r') as f:
                stats['manual_events'] = len(json.load(f))
        except: pass
        
        try:
            with open('time_overrides.json', 'r') as f:
                stats['time_overrides'] = len(json.load(f))
        except: pass
        
        return stats


def setup_admin(app):
    """Setup Flask-Admin"""
    
    # Configure session
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fight-schedule-secret-key')
    
    # Create data directory
    os.makedirs('data', exist_ok=True)
    
    # Initialize admin
    admin = Admin(
        app,
        name='Fight Schedule Admin',
        index_view=SecureAdminIndexView()
    )
    
    # Add file browser for JSON editing (simple solution)
    admin.add_view(FileAdmin('data', '/data/', name='Data Files'))
    
    return admin

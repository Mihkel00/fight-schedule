"""
Admin Data Models for Flask-Admin
Uses JSON files as the data store (no database needed)
"""

import json
import os
from datetime import datetime

class JSONModel:
    """Base class for JSON-backed models"""
    
    def __init__(self, filepath):
        self.filepath = filepath
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        """Create file if it doesn't exist"""
        if not os.path.exists(self.filepath):
            with open(self.filepath, 'w') as f:
                json.dump([], f)
    
    def get_all(self):
        """Get all items"""
        with open(self.filepath, 'r') as f:
            return json.load(f)
    
    def save_all(self, data):
        """Save all items"""
        with open(self.filepath, 'w') as f:
            json.dump(data, f, indent=2)
    
    def add(self, item):
        """Add a new item"""
        data = self.get_all()
        data.append(item)
        self.save_all(data)
        return item
    
    def update(self, index, item):
        """Update an item by index"""
        data = self.get_all()
        if 0 <= index < len(data):
            data[index] = item
            self.save_all(data)
            return item
        return None
    
    def delete(self, index):
        """Delete an item by index"""
        data = self.get_all()
        if 0 <= index < len(data):
            deleted = data.pop(index)
            self.save_all(data)
            return deleted
        return None


class FighterImageOverride(JSONModel):
    """Manage fighter image overrides"""
    
    def __init__(self):
        super().__init__('data/fighter_image_overrides.json')
    
    def get_image_for_fighter(self, fighter_name):
        """Get override image URL for a fighter"""
        data = self.get_all()
        for item in data:
            if item['fighter_name'].lower() == fighter_name.lower():
                return item['image_url']
        return None


class BigNameFighter(JSONModel):
    """Manage big-name fighters list"""
    
    def __init__(self):
        super().__init__('data/big_name_fighters.json')
    
    def is_big_name(self, fighter_name):
        """Check if fighter is in big-name list"""
        data = self.get_all()
        fighter_lower = fighter_name.lower()
        for item in data:
            if item['name'].lower() in fighter_lower or fighter_lower in item['name'].lower():
                return True
        return False


class ManualEvent(JSONModel):
    """Manage manually added events"""
    
    def __init__(self):
        super().__init__('data/manual_events.json')
    
    def get_upcoming_events(self):
        """Get events that haven't happened yet"""
        data = self.get_all()
        today = datetime.now().date().isoformat()
        return [e for e in data if e.get('date', '') >= today]


class TimeOverride(JSONModel):
    """Manage time overrides (already exists in time_overrides.json)"""
    
    def __init__(self):
        # Use existing file
        self.filepath = 'time_overrides.json'
        if not os.path.exists(self.filepath):
            with open(self.filepath, 'w') as f:
                json.dump({}, f)
    
    def get_all(self):
        """Get all overrides as list for display"""
        with open(self.filepath, 'r') as f:
            data = json.load(f)
        
        # Convert dict to list of objects
        result = []
        for fight_key, time in data.items():
            # Parse fight_key: "Fighter1 vs Fighter2|YYYY-MM-DD"
            parts = fight_key.split('|')
            if len(parts) == 2:
                result.append({
                    'matchup': parts[0],
                    'date': parts[1],
                    'time': time,
                    'fight_key': fight_key
                })
        return result
    
    def save_all(self, data):
        """Save overrides back to dict format"""
        result = {}
        for item in data:
            if 'fight_key' in item:
                result[item['fight_key']] = item['time']
        
        with open(self.filepath, 'w') as f:
            json.dump(result, f, indent=2)

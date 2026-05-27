"""Application settings singleton."""
import json
import os
from config import (
    API_RATE_LIMIT_DELAY,
    DEFAULT_ARTWORK_EMBED,
    DEFAULT_PAGE_SIZE,
    DEFAULT_VALIDATE_TAGS,
    FUZZY_THRESHOLD,
    MAX_SEARCH_RETRIES,
    OVERWRITE_EXISTING_TAGS,
)

DEFAULT_SETTINGS = {
    'embed_artwork': DEFAULT_ARTWORK_EMBED,
    'validate_tags': DEFAULT_VALIDATE_TAGS,
    'overwrite_existing_tags': OVERWRITE_EXISTING_TAGS,
    'fuzzy_threshold': FUZZY_THRESHOLD,
    'default_page_size': DEFAULT_PAGE_SIZE,
    'max_search_retries': MAX_SEARCH_RETRIES,
    'api_rate_limit_delay': API_RATE_LIMIT_DELAY,
}

class Settings:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._settings = {}
        return cls._instance
        
    def __init__(self):
        self.config_path = os.path.expanduser("~/.metadata_tagger/settings.json")
        self._load()
        
    def _load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    self._settings = json.load(f)
            except (OSError, json.JSONDecodeError):
                self._settings = {}
        for key, value in DEFAULT_SETTINGS.items():
            self._settings.setdefault(key, value)

    def reload(self):
        self._settings = {}
        self._load()

    def get(self, key, default=None):
        return self._settings.get(key, default)
        
    def set(self, key, value):
        self._settings[key] = value
        self._save()

    def update(self, values):
        self._settings.update(values)
        self._save()
        
    def _save(self):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(self._settings, f, indent=2)
            
    def init_defaults(self):
        for key, value in DEFAULT_SETTINGS.items():
            self.get(key, value)

SETTINGS = Settings()

"""Application settings singleton."""

import json
import os
from config import DEFAULT_ARTWORK_EMBED, DEFAULT_VALIDATE_TAGS


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
                with open(self.config_path, "r") as f:
                    self._settings = json.load(f)
            except:
                pass
        self._settings.setdefault("embed_artwork", DEFAULT_ARTWORK_EMBED)
        self._settings.setdefault("validate_tags", DEFAULT_VALIDATE_TAGS)

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def set(self, key, value):
        self._settings[key] = value
        self._save()

    def _save(self):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self._settings, f, indent=2)

    def init_defaults(self):
        self.get("embed_artwork", DEFAULT_ARTWORK_EMBED)
        self.get("validate_tags", DEFAULT_VALIDATE_TAGS)


SETTINGS = Settings()

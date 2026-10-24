"""Plugin settings. The API key is never stored in source code.

Priority: environment variables > application preferences > defaults.
Outside the slicer (dev mode, tests) a JSON file in the home dir is used.
"""
import json
import os

DEFAULTS = {
    "base_url": "https://api.timeweb.ai/v1",
    "api_key": "",
    "model": "dashscope/qwen3.8-flash",
    "output_dir": "",
    "max_steps": 25,
    "request_timeout": 120,
}
ENV = {"base_url": "LLM_BASE_URL", "api_key": "LLM_API_KEY", "model": "LLM_MODEL"}
PREF = "ai_assistant/"


class _PreferencesStore(object):
    def __init__(self):
        try:
            from UM.Preferences import Preferences
            self._p = Preferences.getInstance()
        except Exception:
            from UM.Application import Application
            self._p = Application.getInstance().getPreferences()
        for k, v in DEFAULTS.items():
            self._p.addPreference(PREF + k, v)

    def get(self, key):
        return self._p.getValue(PREF + key)

    def set(self, key, value):
        self._p.setValue(PREF + key, value)


class _FileStore(object):
    def __init__(self, path=None):
        self._path = path or os.path.join(os.path.expanduser("~"), ".ai_assistant_dev.json")
        self._data = {}
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (OSError, ValueError):
                self._data = {}

    def get(self, key):
        return self._data.get(key, DEFAULTS[key])

    def set(self, key, value):
        self._data[key] = value
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f)


class Settings(object):
    def __init__(self, store=None):
        if store is None:
            try:
                store = _PreferencesStore()
            except Exception:
                store = _FileStore()
        self._store = store

    def get(self, key):
        env = ENV.get(key)
        if env and os.environ.get(env):
            return os.environ[env]
        value = self._store.get(key)
        return DEFAULTS[key] if value in (None, "") and key != "api_key" else value

    def set(self, key, value):
        if key in DEFAULTS:
            self._store.set(key, value)

    def public(self):
        """What the browser may see: never the key itself."""
        return {"base_url": self.get("base_url"), "model": self.get("model"),
                "output_dir": self.output_dir(), "has_key": bool(self.get("api_key"))}

    def output_dir(self):
        d = self.get("output_dir") or os.path.join(os.path.expanduser("~"), "AIAssistant_output")
        os.makedirs(d, exist_ok=True)
        return d

    def uploads_dir(self):
        d = os.path.join(self.output_dir(), "uploads")
        os.makedirs(d, exist_ok=True)
        return d

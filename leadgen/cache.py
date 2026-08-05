"""A small on-disk cache so re-running research doesn't re-pay for API calls.

Google bills per Place Details call, and research runs are naturally iterative
— you tweak the ICP weights and re-score, or add a market and re-run. Caching
the raw API responses means only the genuinely new lookups cost money.
"""

import json
import os
import tempfile
import time


class Cache:
    def __init__(self, path, ttl_days=30, enabled=True):
        self.path = path
        self.ttl_seconds = ttl_days * 86400
        self.enabled = enabled
        self._data = {}
        self._dirty = False
        self.hits = 0
        self.misses = 0
        if enabled:
            self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                self._data = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._data = {}

    def get(self, key):
        if not self.enabled:
            return None
        entry = self._data.get(key)
        if not entry:
            self.misses += 1
            return None
        if self.ttl_seconds and time.time() - entry.get("cached_at", 0) > self.ttl_seconds:
            self.misses += 1
            return None
        self.hits += 1
        return entry.get("value")

    def set(self, key, value):
        if not self.enabled:
            return
        self._data[key] = {"cached_at": time.time(), "value": value}
        self._dirty = True

    def save(self):
        """Write atomically so an interrupted run can't corrupt the cache."""
        if not self.enabled or not self._dirty:
            return
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle)
            os.replace(tmp, self.path)
            self._dirty = False
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

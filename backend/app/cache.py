"""Tiny cache abstraction: Redis when REDIS_URL is set, otherwise an in-process TTL dict."""
import json
import threading
import time
from typing import Any

from .config import settings


class MemoryCache:
    def __init__(self):
        self._d: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._d.get(key)
            if not item:
                return None
            if item[0] < time.time():
                self._d.pop(key, None)
                return None
            return item[1]

    def set(self, key, value, ttl):
        with self._lock:
            self._d[key] = (time.time() + ttl, value)

    def delete(self, key):
        with self._lock:
            self._d.pop(key, None)

    def incr(self, key, ttl):
        with self._lock:
            now = time.time()
            exp, val = self._d.get(key, (0, 0))
            if exp < now:
                exp, val = now + ttl, 0
            self._d[key] = (exp, val + 1)
            return val + 1

    def clear(self):
        with self._lock:
            self._d.clear()


class RedisCache:
    def __init__(self, url):
        import redis
        self.r = redis.Redis.from_url(url, decode_responses=True)

    def get(self, key):
        raw = self.r.get(key)
        return json.loads(raw) if raw else None

    def set(self, key, value, ttl):
        self.r.set(key, json.dumps(value), ex=ttl)

    def delete(self, key):
        self.r.delete(key)

    def incr(self, key, ttl):
        pipe = self.r.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)
        return pipe.execute()[0]

    def clear(self):
        self.r.flushdb()


def _build():
    if settings.redis_url:
        try:
            c = RedisCache(settings.redis_url)
            c.r.ping()
            return c
        except Exception as exc:  # pragma: no cover
            print(f"[cache] Redis unavailable ({exc}); using in-memory cache")
    return MemoryCache()


cache = _build()


def public_events_key(org_id: int) -> str:
    return f"public:events:{org_id}"

"""Test doubles shared by the evolution tests."""
import fnmatch


class FakeRedis:
    """Enough of redis-py for locks, counters and the response cache."""

    def __init__(self):
        self.store: dict[str, object] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def setex(self, key, ttl, value):
        self.store[key] = value

    def exists(self, key):
        return int(key in self.store)

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)
        return len(keys)

    def incr(self, key):
        self.store[key] = int(self.store.get(key) or 0) + 1
        return self.store[key]

    def incrby(self, key, n):
        self.store[key] = int(self.store.get(key) or 0) + n
        return self.store[key]

    def expire(self, key, ttl):
        return True

    def scan_iter(self, match, count=100):
        return [k for k in list(self.store) if fnmatch.fnmatch(k, match)]

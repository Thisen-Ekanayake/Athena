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

    # Hashes and lists, for the sync's progress and log

    def hset(self, key, field=None, value=None, mapping=None):
        h = self.store.setdefault(key, {})
        if field is not None:
            h[field] = value
        h.update(mapping or {})
        return 1

    def hget(self, key, field):
        return self.store.get(key, {}).get(field)

    def hgetall(self, key):
        return dict(self.store.get(key, {}))

    def hincrby(self, key, field, n=1):
        h = self.store.setdefault(key, {})
        h[field] = int(h.get(field) or 0) + n
        return h[field]

    def rpush(self, key, *values):
        self.store.setdefault(key, []).extend(values)
        return len(self.store[key])

    def lpop(self, key):
        items = self.store.get(key)
        return items.pop(0) if items else None

    def lrange(self, key, start, end):
        items = self.store.get(key, [])
        return items[start:None if end == -1 else end + 1]

    def ltrim(self, key, start, end):
        items = self.store.get(key, [])
        self.store[key] = items[start:None if end == -1 else end + 1]
        return True

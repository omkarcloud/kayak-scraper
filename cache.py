"""A tiny in-memory response cache with the same call shape the kayak
module uses. Results live in this process only and expire after `ttl`
(a datetime.timedelta), so details + rates + nearby + price insights on the
same hotel cost one fetch from kayak.com.

Entries are stored as JSON and decoded into a fresh object on every hit, so
a caller that changes the result it gets back (routes.paginate pops the
`pagination` block) never changes what the next caller receives.
"""
import json
import threading
import time

_store = {}
_lock = threading.Lock()
MAX_ENTRIES = 2000


def _key(namespace, data):
    return namespace + ":" + json.dumps(data, sort_keys=True, default=str)


def cached_call(namespace, data, fn, ttl, cache=True, refresh=False):
    """Serve fn(**data) from memory for `ttl`, else run it and keep the result.
    Exceptions from fn propagate uncached."""
    if not (cache and ttl):
        return fn(**data)
    key = _key(namespace, data)
    now = time.time()
    if not refresh:
        with _lock:
            hit = _store.get(key)
        if hit and hit[0] > now:
            return json.loads(hit[1])
    result = fn(**data)
    with _lock:
        if len(_store) >= MAX_ENTRIES:
            for stale in [k for k, (expires, _) in _store.items() if expires <= now] or list(_store)[:100]:
                _store.pop(stale, None)
        _store[key] = (now + ttl.total_seconds(), json.dumps(result, ensure_ascii=False, default=str))
    return result

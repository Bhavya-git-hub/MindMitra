"""A small sliding-window rate limiter for the public auth endpoints.

In-process only: with several API replicas each enforces its own window. A shared (Redis)
limiter replaces it when Redis is wired in; the dependency interface stays the same.
"""

import collections
import time
from collections.abc import Callable


class SlidingWindowRateLimiter:
    def __init__(
        self, limit: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, collections.deque[float]] = {}

    def hit(self, key: str) -> float | None:
        """Record a request. Returns ``None`` if allowed, else seconds until a slot frees up."""
        now = self._clock()
        q = self._hits.setdefault(key, collections.deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return max(q[0] + self.window - now, 0.0)
        q.append(now)
        if len(self._hits) > 100_000:  # bound memory under a flood of distinct keys
            self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - self.window}
        return None

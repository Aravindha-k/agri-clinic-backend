"""Rate limiting for attendance endpoints.

DRF's default throttle ident trusts X-Forwarded-For unconditionally; behind
no proxy (or a misconfigured one) a client could rotate IPs per request and
defeat per-IP limits. These throttles resolve the client IP through
`attendance.permissions.client_ip`, which honours BEHIND_TRUSTED_PROXY.
"""

from __future__ import annotations

from django.core.cache import cache
from django.utils import timezone
from rest_framework.throttling import ScopedRateThrottle

from attendance.permissions import client_ip


class TrustedScopedRateThrottle(ScopedRateThrottle):
    def get_ident(self, request):
        return client_ip(request) or "unknown"


def global_pairing_attempt_limited(limit_per_minute: int) -> bool:
    """Shared (cache-backed) global ceiling on pairing attempts/minute.

    Guards against distributed guessing across many IPs: even with perfect
    per-IP rotation, total guesses stay under `limit_per_minute`.
    Returns True when the caller must back off.
    """
    bucket = int(timezone.now().timestamp() // 60)
    key = f"attendance:pairing:global:{bucket}"
    try:
        count = cache.get(key)
        if count is None:
            cache.add(key, 1, timeout=120)
            count = 1
        else:
            count = cache.incr(key)
    except Exception:
        return False  # fail open on cache backend issues; per-IP throttle still applies
    return count > limit_per_minute

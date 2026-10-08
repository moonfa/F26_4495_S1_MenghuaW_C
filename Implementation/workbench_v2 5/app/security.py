"""Request guards for a local, single-user app. Pure functions so they can be unit-tested without a web server.

Threat model: the server listens on 127.0.0.1 and has no login. The realistic attacks are therefore a web page you visit
in another tab that tries to talk to localhost (cross-site request forgery) or a DNS-rebinding page that makes your
browser treat an attacker's hostname as 127.0.0.1. Both are stopped by checking the Host and Origin headers."""
from __future__ import annotations

import os
from urllib.parse import urlparse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_DEFAULT_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}


def allowed_hosts() -> set[str]:
    extra = {h.strip().lower() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()}
    return _DEFAULT_HOSTS | extra


def hostname(host_header: str | None) -> str:
    h = (host_header or "").strip().lower()
    if h.startswith("["):                       # IPv6 literal, e.g. [::1]:8000
        return h.split("]")[0] + "]"
    return h.rsplit(":", 1)[0] if ":" in h else h


def host_ok(host_header: str | None) -> bool:
    return hostname(host_header) in allowed_hosts()


def origin_ok(method: str, origin: str | None, host_header: str | None) -> bool:
    """State-changing requests that carry an Origin must come from this same host. No Origin (curl, scripts) is allowed."""
    if method.upper() in SAFE_METHODS or not origin:
        return True
    if origin == "null":
        return False
    return urlparse(origin).netloc.lower() == (host_header or "").strip().lower()


MAX_UPLOAD = 5 * 1024 * 1024                    # a broker export is a few hundred KB

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"}

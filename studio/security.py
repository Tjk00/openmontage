"""Security utilities for OpenMontage AI Studio.

- Token-based admin auth with HMAC-signed session cookies.
- Per-IP fixed-window request throttling.
- Safe file path resolution (no traversal outside the data dir).
- URL validation + SSRF guard for server-side fetches (blocks private ranges).
- Secret masking for the UI.

The studio must never expose an unrestricted public rendering endpoint:
when ``OM_STUDIO_TOKEN`` is not configured the instance runs in "open local
mode" and the diagnostics endpoint reports it prominently.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import socket
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

MASK = "••••••••"


def mask_secret(value: Optional[str]) -> str:
    """Mask a secret for display: shows only that it is configured."""
    if not value:
        return ""
    return MASK


def generate_session_token(secret: str, ttl_seconds: int) -> str:
    """Return ``exp.sig`` where sig = HMAC(secret, exp)."""
    exp = str(int(time.time()) + ttl_seconds)
    sig = hmac.new(secret.encode(), exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def verify_session_token(secret: str, token: Optional[str]) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.rsplit(".", 1)
    try:
        if int(exp) < time.time():
            return False
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def ensure_session_secret(configured: str) -> str:
    """Return configured secret or an ephemeral random one (per-process)."""
    return configured or secrets.token_hex(32)


class RateLimiter:
    """Fixed-window per-key rate limiter (thread-safe enough for FastAPI use)."""

    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, max_per_minute: Optional[int] = None) -> bool:
        limit = max_per_minute if max_per_minute is not None else self.max_per_minute
        now = time.time()
        q = self._hits[key]
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


_PATH_OK = re.compile(r"^[A-Za-z0-9._\- /]+$")


def safe_join(base: Path, *parts: str) -> Path:
    """Join path parts under base; raise ValueError on traversal attempts."""
    for p in parts:
        if not p or ".." in p.split("/") or ".." in p.split("\\"):
            raise ValueError("invalid path component")
        if p.startswith("/") or (len(p) > 1 and p[1] == ":"):
            raise ValueError("absolute path component not allowed")
    resolved = (base.joinpath(*parts)).resolve()
    base_resolved = base.resolve()
    if not str(resolved).startswith(str(base_resolved)):
        raise ValueError("path escapes base directory")
    return resolved


_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost")


def is_safe_url(url: str, *, allow_private: bool = False) -> bool:
    """Validate scheme/host for server-side fetches (basic SSRF defense)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    if host.lower() in ("localhost",) or host.lower().endswith(_BLOCKED_HOST_SUFFIXES):
        return allow_private
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if allow_private:
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True


def validate_and_normalize_url(url: str) -> str:
    """Raise ValueError if the URL is not a safe public http(s) URL."""
    url = url.strip()
    if len(url) > 2048:
        raise ValueError("URL too long")
    if not is_safe_url(url):
        raise ValueError("URL must be a public http(s) address")
    return url


def safe_error(exc: BaseException) -> str:
    """Return a short, non-sensitive error string safe to show in the UI."""
    msg = str(exc).strip() or exc.__class__.__name__
    # Redact anything that looks like a token/key
    msg = re.sub(r"(?i)(key|token|secret|password|authorization)[=: ]+\S+", r"\1=" + MASK, msg)
    msg = re.sub(r"Bearer\s+\S+", "Bearer " + MASK, msg)
    return msg[:500]

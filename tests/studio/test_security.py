"""Security tests: auth, sessions, rate limiting, path safety, SSRF, masking."""
from __future__ import annotations

import time

import pytest

from studio import security as S


def test_mask_secret():
    assert S.mask_secret("") == ""
    assert S.mask_secret(None) == ""
    assert S.mask_secret("sk-abcdef123456") == S.MASK
    assert "sk-abcdef" not in S.mask_secret("sk-abcdef123456")


def test_session_token_roundtrip():
    secret = "test-secret"
    tok = S.generate_session_token(secret, ttl_seconds=60)
    assert S.verify_session_token(secret, tok) is True
    assert S.verify_session_token("other-secret", tok) is False
    assert S.verify_session_token(secret, "garbage") is False
    assert S.verify_session_token(secret, None) is False


def test_session_token_expiry():
    secret = "s"
    tok = S.generate_session_token(secret, ttl_seconds=-10)
    assert S.verify_session_token(secret, tok) is False


def test_rate_limiter():
    rl = S.RateLimiter(max_per_minute=3)
    assert rl.allow("ip1") and rl.allow("ip1") and rl.allow("ip1")
    assert rl.allow("ip1") is False
    assert rl.allow("ip2") is True
    assert rl.allow("ip1", max_per_minute=10) is True


def test_safe_join_blocks_traversal(tmp_path):
    with pytest.raises(ValueError):
        S.safe_join(tmp_path, "../etc/passwd")
    with pytest.raises(ValueError):
        S.safe_join(tmp_path, "/etc/passwd")
    with pytest.raises(ValueError):
        S.safe_join(tmp_path, "a/../../b")
    ok = S.safe_join(tmp_path, "renders", "final.mp4")
    assert str(ok).startswith(str(tmp_path.resolve()))


def test_is_safe_url_blocks_private_targets():
    assert S.is_safe_url("https://example.com/x") in (True, False)  # DNS dependent
    assert S.is_safe_url("ftp://example.com/x") is False
    assert S.is_safe_url("file:///etc/passwd") is False
    assert S.is_safe_url("http://localhost:8080/x") is False
    assert S.is_safe_url("http://127.0.0.1/admin") is False
    assert S.is_safe_url("http://192.168.1.1/router") is False
    assert S.is_safe_url("http://10.0.0.5/internal") is False
    assert S.is_safe_url("http://[::1]/x") is False
    with pytest.raises(ValueError):
        S.validate_and_normalize_url("http://169.254.169.254/latest/meta-data")


def test_safe_error_redacts_secrets():
    msg = S.safe_error(Exception("failed: api_key=sk-secret1234 and Bearer abc.def.ghi"))
    assert "sk-secret1234" not in msg
    assert "abc.def.ghi" not in msg
    assert S.MASK in msg


def test_safe_join_rejects_empty_and_weird(tmp_path):
    with pytest.raises(ValueError):
        S.safe_join(tmp_path, "")
    with pytest.raises(ValueError):
        S.safe_join(tmp_path, "C:/windows/system32")

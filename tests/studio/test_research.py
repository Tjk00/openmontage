"""Research stage tests: feed parsing, caching, throttling, honesty rules."""
from __future__ import annotations

import time
from unittest import mock

from studio.pipeline import research as R

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Test Feed</title>
<item><title>Finding A published today</title><link>https://example.com/a</link>
<pubDate>Mon, 06 Oct 2025 10:00:00 GMT</pubDate>
<description>Researchers report that honeybee dance language encodes distance.</description></item>
<item><title>Some headline</title><link>https://example.com/b</link>
<pubDate>Tue, 07 Oct 2025 10:00:00 GMT</pubDate>
<description>Analysts predict the trend may continue, possibly for months.</description></item>
</channel></rss>"""


class _Resp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def test_parse_feed_rss():
    items = R._parse_feed(RSS, "https://example.com/rss")
    assert len(items) == 2
    assert items[0]["title"].startswith("Finding A")
    assert items[0]["url"] == "https://example.com/a"
    assert "dance language" in items[0]["snippet"]


def test_parse_feed_atom():
    atom = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
    <entry><title>Atom story</title><link href="https://example.com/atom1"/>
    <updated>2025-10-06T10:00:00Z</updated><summary>Summary text here</summary></entry></feed>"""
    items = R._parse_feed(atom, "https://example.com/atom")
    assert len(items) == 1 and items[0]["url"] == "https://example.com/atom1"


def test_run_research_success_and_claim_classification(db):
    with mock.patch("studio.pipeline.research.requests.get", return_value=_Resp(RSS)):
        result = R.run_research("honeybee dance", timeout=2, cache=db, cache_hours=1)
    assert result.status == "ok"
    assert result.verified is True
    assert len(result.sources) == 2
    assert result.findings
    types = {f["claim_type"] for f in result.findings}
    assert "sourced_statement" in types or "opinion_or_prediction" in types
    # hedged language must be classified as opinion/prediction
    hedge = [f for f in result.findings if "predict" in f["statement"].lower()]
    if hedge:
        assert hedge[0]["claim_type"] == "opinion_or_prediction"
    # every finding carries a source
    assert all(f["source_url"] for f in result.findings)
    # three angles with evidence
    assert len(result.angles) == 3
    assert all(a["evidence_strength"] == "sourced" for a in result.angles)


def test_run_research_offline_is_honest(db):
    def boom(*a, **kw):
        raise OSError("network unreachable")

    with mock.patch("studio.pipeline.research.requests.get", side_effect=boom):
        result = R.run_research("quantum computing", timeout=2, cache=db, cache_hours=1)
    assert result.status == "unavailable"
    assert result.verified is False
    assert result.angles  # fallback angles exist
    assert all(a["evidence_strength"] == "unverified" for a in result.angles)
    # must NOT claim trending/viral
    blob = str(result.to_dict()).lower()
    assert "currently viral" not in blob
    assert any("unverified" in u.lower() for u in result.uncertainties)


def test_run_research_caching(db):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return _Resp(RSS)

    with mock.patch("studio.pipeline.research.requests.get", side_effect=fake_get):
        r1 = R.run_research("caching topic", timeout=2, cache=db, cache_hours=1)
        r2 = R.run_research("caching topic", timeout=2, cache=db, cache_hours=1)
    assert r2.cached is True
    assert len(calls) == 1


def test_run_research_empty_query_raises():
    import pytest

    with pytest.raises(ValueError):
        R.run_research("   ")


def test_research_throttle_spaces_requests():
    last = R._last_host_hit
    last.clear()
    last["example.com"] = time.time() - 1.8  # last hit 1.8s ago → ~0.2s wait left
    start = time.time()
    R._throttle("https://example.com/feed")
    assert time.time() - start > 0.1  # had to wait some of the interval

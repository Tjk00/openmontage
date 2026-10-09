"""Script generation tests: duration matching, anti-fabrication, styles."""
from __future__ import annotations

import pytest

from studio.pipeline import scriptgen as S


def test_script_matches_duration():
    req = {"topic": "the history of coffee", "duration_seconds": 30, "style": "history",
           "audience": "general", "platform": "tiktok"}
    doc = S.generate_script(req, None)
    words = len(doc.voiceover_text.split())
    est = words / S.WPS
    assert 30 * 0.5 <= est <= 30 * 1.6  # reasonable pacing window
    assert doc.hook and doc.closing_line
    assert len(doc.scenes) >= 3
    total_scene_dur = sum(s.duration for s in doc.scenes)
    assert abs(total_scene_dur - 30) < 0.5


def test_script_no_placeholders_or_fabricated_numbers():
    req = {"topic": "electric cars in 2026", "duration_seconds": 15, "style": "technology"}
    doc = S.generate_script(req, None)
    assert "{topic}" not in doc.voiceover_text
    assert "TODO" not in doc.voiceover_text
    # No research → no numeric claims allowed at all
    import re

    assert not re.search(r"\b\d{1,3}(?:\.\d+)?\s?%|\$\s?\d+", doc.voiceover_text)


def test_numeric_claim_requires_source():
    req = {"topic": "crypto markets", "duration_seconds": 30, "style": "finance"}
    research = {"findings": [], "sources": []}
    doc = S.generate_script(req, research)
    # engine itself must never add numbers without sources — validation enforces it
    assert doc.source_refs == []
    import re

    assert not re.search(r"\b\d{1,3}(?:\.\d+)?\s?%|\$\s?\d+", doc.voiceover_text)


def test_sensitive_topics_get_disclaimers():
    req = {"topic": "bitcoin investment strategies", "duration_seconds": 15, "style": "finance"}
    doc = S.generate_script(req, None)
    assert any("not financial advice" in d.lower() for d in doc.disclaimers)

    req2 = {"topic": "managing back pain", "duration_seconds": 15, "style": "health"}
    doc2 = S.generate_script(req2, None)
    assert any("medical advice" in d.lower() for d in doc2.disclaimers)


def test_custom_topics_accepted():
    req = {"topic": "why my cat ignores me but loves my roommate", "duration_seconds": 15,
           "style": "custom"}
    doc = S.generate_script(req, None)
    assert "cat" in doc.voiceover_text.lower()


def test_research_findings_become_supporting_facts():
    research = {
        "findings": [
            {"statement": "A study from 2025 described a new approach to reef restoration.",
             "source_title": "Reef study", "source_url": "https://example.com/study",
             "claim_type": "sourced_statement"},
        ],
        "sources": [{"title": "Reef study", "url": "https://example.com/study"}],
    }
    req = {"topic": "coral reef restoration", "duration_seconds": 30, "style": "nature"}
    doc = S.generate_script(req, research)
    assert doc.supporting_facts and doc.supporting_facts[0]["source_url"] == "https://example.com/study"
    assert doc.source_refs
    assert "reef restoration" in doc.voiceover_text.lower()


def test_all_styles_produce_valid_scripts():
    for style in S.STYLE_PACKS:
        req = {"topic": "sample topic about space", "duration_seconds": 15, "style": style}
        doc = S.generate_script(req, None)
        assert doc.voiceover_text.strip()
        assert len(doc.scenes) >= 3


def test_validator_rejects_placeholders():
    doc = S.ScriptDoc(topic="t", style="custom", language="en", platform="x", duration_seconds=15,
                      voiceover_text="{topic} is great")
    with pytest.raises(ValueError):
        S.validate_script(doc, requested_seconds=15)

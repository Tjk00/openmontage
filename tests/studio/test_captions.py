"""Caption generation tests: timing, SRT export, PNG cards."""
from __future__ import annotations

from studio.pipeline import captions as C


def test_estimate_word_timings_proportional():
    words = C.estimate_word_timings("Hello wonderful world", 3.0)
    assert len(words) == 3
    assert words[0]["start"] == 0.0
    assert abs(words[-1]["end"] - 3.0) < 0.05
    # longer words get more time
    assert words[1]["end"] - words[1]["start"] > words[0]["end"] - words[0]["start"]


def test_build_cues_grouping():
    words = C.estimate_word_timings("one two three four five six seven eight nine", 4.5)
    cues = C.build_cues(words, max_words=3)
    assert len(cues) == 3
    assert cues[0].index == 1
    assert cues[0].text == "one two three"
    assert cues[0].start < cues[0].end <= cues[1].start + 1e-6


def test_build_captions_writes_srt_and_json(studio_env, tmp_path):
    text = "Welcome to the studio. This is a caption timing test with several short sentences."
    res = C.build_captions(text, 6.0, tmp_path)
    assert res.cues
    assert res.timing_source == "estimated-proportional"
    srt = (tmp_path / "captions.srt").read_text(encoding="utf-8")
    assert "Welcome" in srt
    assert "-->" in srt
    assert (tmp_path / "captions.json").exists()
    # timing honesty warning present
    assert any("estimated" in w.lower() for w in res.warnings)


def test_render_caption_png(studio_env, tmp_path):
    out = C.render_caption_png("Big readable caption text", tmp_path / "c.png",
                               width=540, height=960, position="bottom")
    assert out.exists() and out.stat().st_size > 500
    from PIL import Image

    img = Image.open(out)
    assert img.size == (540, 960)
    assert img.mode == "RGBA"


def test_render_caption_cards_positions(studio_env, tmp_path):
    words = C.estimate_word_timings("alpha beta gamma delta epsilon", 3.0)
    cues = C.build_cues(words, max_words=2)
    cards = C.render_caption_cards(cues, tmp_path, width=216, height=216, position="top")
    assert len(cards) == len(cues)
    for card in cards:
        assert card["start"] < card["end"]
        assert card["path"].endswith(".png")


def test_empty_input_no_crash(studio_env, tmp_path):
    res = C.build_captions("", 0, tmp_path)
    assert res.cues == []
    assert res.warnings

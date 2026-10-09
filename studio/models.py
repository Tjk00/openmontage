"""Request models + input validation for the studio API."""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

DURATIONS = [15, 30, 45, 60, 90]
ASPECTS = ["9:16", "16:9", "1:1"]
PLATFORMS = ["tiktok", "youtube", "instagram", "x", "linkedin", "facebook", "other"]
STYLES = ["documentary", "educational", "motivation", "news", "technology", "finance",
          "business", "nature", "health", "history", "storytelling", "product", "custom"]
FOOTAGE = ["auto", "stock", "open", "local"]
CAPTIONS = ["burned", "srt-only", "none"]
MUSIC_PREF = ["none", "ambient", "upload"]
RESEARCH_DEPTH = ["quick", "standard", "deep"]
LANGUAGES = ["en", "en-GB", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "zh", "ja", "hi", "ar"]
VOICES = ["auto", "en-us", "en-gb", "de", "fr", "es", "it", "pt", "ru", "zh"]


class VideoRequest(BaseModel):
    """Universal topic input for a video production job."""

    topic: str = Field(min_length=3, max_length=500)
    audience: str = Field(default="general", max_length=200)
    platform: str = Field(default="tiktok")
    duration_seconds: int = Field(default=30)
    language: str = Field(default="en")
    voice: str = Field(default="en-us")
    style: str = Field(default="custom")
    aspect: str = Field(default="9:16")
    research_depth: str = Field(default="standard")
    footage_preference: str = Field(default="auto")
    caption_preference: str = Field(default="burned")
    music_preference: str = Field(default="ambient")
    reference_urls: list[str] = Field(default_factory=list, max_length=5)
    restrictions: str = Field(default="", max_length=1000)
    call_to_action: str = Field(default="auto", max_length=120)
    selected_angle: Optional[str] = Field(default=None, max_length=300)
    narration_upload_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("topic")
    @classmethod
    def _topic_ok(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("topic must not be empty")
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", v):
            raise ValueError("topic contains control characters")
        return v

    @field_validator("duration_seconds")
    @classmethod
    def _duration_ok(cls, v: int) -> int:
        if v not in DURATIONS:
            raise ValueError(f"duration_seconds must be one of {DURATIONS}")
        return v

    @field_validator("platform")
    @classmethod
    def _platform_ok(cls, v: str) -> str:
        if v not in PLATFORMS:
            raise ValueError(f"platform must be one of {PLATFORMS}")
        return v

    @field_validator("style")
    @classmethod
    def _style_ok(cls, v: str) -> str:
        if v not in STYLES:
            raise ValueError(f"style must be one of {STYLES} (custom topics use style='custom')")
        return v

    @field_validator("aspect")
    @classmethod
    def _aspect_ok(cls, v: str) -> str:
        if v not in ASPECTS:
            raise ValueError(f"aspect must be one of {ASPECTS}")
        return v

    @field_validator("research_depth")
    @classmethod
    def _depth_ok(cls, v: str) -> str:
        if v not in RESEARCH_DEPTH:
            raise ValueError(f"research_depth must be one of {RESEARCH_DEPTH}")
        return v

    @field_validator("footage_preference")
    @classmethod
    def _footage_ok(cls, v: str) -> str:
        if v not in FOOTAGE:
            raise ValueError(f"footage_preference must be one of {FOOTAGE}")
        return v

    @field_validator("caption_preference")
    @classmethod
    def _captions_ok(cls, v: str) -> str:
        if v not in CAPTIONS:
            raise ValueError(f"caption_preference must be one of {CAPTIONS}")
        return v

    @field_validator("music_preference")
    @classmethod
    def _music_ok(cls, v: str) -> str:
        if v not in MUSIC_PREF:
            raise ValueError(f"music_preference must be one of {MUSIC_PREF}")
        return v

    @field_validator("language", "voice")
    @classmethod
    def _lang_ok(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z\-]{2,10}$", v or ""):
            raise ValueError("must be a simple language/voice code like 'en' or 'en-GB'")
        return v

    @field_validator("reference_urls")
    @classmethod
    def _urls_ok(cls, urls: list[str]) -> list[str]:
        from studio.security import validate_and_normalize_url

        out = []
        for u in urls:
            u = (u or "").strip()
            if not u:
                continue
            out.append(validate_and_normalize_url(u))
        return out

    @field_validator("restrictions", "audience", "call_to_action", "selected_angle")
    @classmethod
    def _no_control(cls, v: Optional[str]) -> Optional[str]:
        if v and re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", v):
            raise ValueError("contains control characters")
        return v


class ResearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    depth: str = Field(default="standard")

    @field_validator("depth")
    @classmethod
    def _depth_ok(cls, v: str) -> str:
        if v not in RESEARCH_DEPTH:
            raise ValueError(f"depth must be one of {RESEARCH_DEPTH}")
        return v


class ProviderToggle(BaseModel):
    enabled: bool


class DeleteProjectRequest(BaseModel):
    confirm: bool = False

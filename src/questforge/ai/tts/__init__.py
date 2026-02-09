# src/questforge/ai/tts/__init__.py
from __future__ import annotations

from questforge.ai.tts.narration_split import NarrationLine, split_narration
from questforge.ai.tts.tts_cache import TtsCache
from questforge.ai.tts.tts_client_openai import OpenAiTtsClient
from questforge.ai.tts.voice_map import VoiceProfile, voice_for_role

__all__ = [
    "NarrationLine",
    "split_narration",
    "TtsCache",
    "OpenAiTtsClient",
    "VoiceProfile",
    "voice_for_role",
]

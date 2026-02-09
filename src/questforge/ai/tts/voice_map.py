from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceProfile:
    role: str
    voice: str
    instructions: str = ""


_DEFAULT_VOICE_BY_ROLE = {
    "旁白": "shimmer",
    "narrator": "shimmer",
    # kids：先用 brighter 的 nova / ash 當預設
    "霏霏": "nova",
    "child_female": "nova",
    "樂樂": "ash",
    "child_male": "ash",
    "老師": "sage",
    "teacher": "sage",
    "配角": "alloy",
    "extra": "alloy",
    "default": "alloy",
}

_DEFAULT_INSTRUCTIONS_BY_ROLE = {
    "旁白": (
        "Warm, gentle female narrator. Natural storytelling, not robotic. "
        "Slightly slower pace, soft smiles in tone."
    ),
    "霏霏": (
        "Sound like a cute, natural Taiwanese elementary school girl (about 7-9). "
        "Bright, lively, playful. Short natural pauses. "
        "Avoid sounding like an adult pretending to be a child."
    ),
    "樂樂": (
        "Sound like an energetic Taiwanese elementary school boy (about 7-9). "
        "More active and expressive, curious and excited. "
        "Avoid deep adult tone."
    ),
    "老師": (
        "Speak clearly, gently, like a teacher talking to kids. "
        "Reassuring, calm, warm."
    ),
    "default": "Speak clearly and friendly.",
}

_EXTRA_VOICE_POOL = [
    "alloy",
    "ash",
    "nova",
    "echo",
    "fable",
    "verse",
    "cedar",
    "marin",
    "shimmer",
    "sage",
    "coral",
    "onyx",
]


def _env_voice(key: str) -> str:
    return (os.getenv(key) or "").strip()


def _stable_pick_voice(name: str, pool: list[str]) -> str:
    n = (name or "").strip()
    if not n:
        return pool[0]
    h = hashlib.sha1(n.encode("utf-8")).hexdigest()
    idx = int(h[:8], 16) % len(pool)
    return pool[idx]


def voice_for_role(role: str) -> VoiceProfile:
    r = (role or "").strip() or "default"

    if r in ("旁白", "narrator"):
        voice = _env_voice("QF_TTS_VOICE_NARRATOR") or _DEFAULT_VOICE_BY_ROLE["旁白"]
        return VoiceProfile(r, voice, _DEFAULT_INSTRUCTIONS_BY_ROLE["旁白"])

    if r in ("霏霏", "child_female"):
        voice = (
            _env_voice("QF_TTS_VOICE_CHILD_FEMALE") or _DEFAULT_VOICE_BY_ROLE["霏霏"]
        )
        return VoiceProfile(r, voice, _DEFAULT_INSTRUCTIONS_BY_ROLE["霏霏"])

    if r in ("樂樂", "child_male"):
        voice = _env_voice("QF_TTS_VOICE_CHILD_MALE") or _DEFAULT_VOICE_BY_ROLE["樂樂"]
        return VoiceProfile(r, voice, _DEFAULT_INSTRUCTIONS_BY_ROLE["樂樂"])

    if r in ("老師", "teacher"):
        voice = _env_voice("QF_TTS_VOICE_TEACHER") or _DEFAULT_VOICE_BY_ROLE["老師"]
        return VoiceProfile(r, voice, _DEFAULT_INSTRUCTIONS_BY_ROLE["老師"])

    env_default = _env_voice("QF_TTS_VOICE_DEFAULT")
    voice = env_default or _stable_pick_voice(r, _EXTRA_VOICE_POOL)
    return VoiceProfile(r, voice, _DEFAULT_INSTRUCTIONS_BY_ROLE["default"])

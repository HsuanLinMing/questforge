# src/questforge_server/tts_cache.py
from __future__ import annotations

import hashlib
import os
import wave
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SR = 22050

@dataclass(frozen=True)
class TtsFile:
    file_id: str
    path: Path

class TtsCache:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_id(self, *, text: str, voice: str, fmt: str) -> str:
        h = hashlib.sha1()
        h.update((voice + "|" + fmt + "|" + text).encode("utf-8"))
        return h.hexdigest()

    def ensure_wav(self, *, text: str, voice: str = "narrator") -> TtsFile:
        file_id = self._make_id(text=text, voice=voice, fmt="wav")
        out = self.cache_dir / f"{file_id}.wav"
        if out.exists():
            return TtsFile(file_id=file_id, path=out)

        # ✅ 先產一段「靜音 wav」(0.25s) 讓你驗證 Flutter 播放鏈 OK
        duration_sec = 0.25
        nframes = int(DEFAULT_SR * duration_sec)
        silence = (b"\x00\x00") * nframes  # 16-bit mono

        with wave.open(str(out), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(DEFAULT_SR)
            wf.writeframes(silence)

        return TtsFile(file_id=file_id, path=out)

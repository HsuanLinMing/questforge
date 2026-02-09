# src/questforge/ai/tts/tts_cache.py
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from questforge.ai.tts.tts_client_openai import OpenAiTtsClient


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CachedTtsItem:
    role: str
    voice: str
    text: str
    path: str          # file://...
    response_format: str


class TtsCache:
    """File-based TTS cache.

    key = sha1(model + voice + instructions + response_format + text)
    value = audio file stored on disk

    Default dir:
    - env QF_TTS_CACHE_DIR
    - else ./.qf_tts_cache
    """

    def __init__(self, *, base_dir: str | Path | None = None) -> None:
        root = (
            str(base_dir)
            if base_dir is not None
            else (os.getenv("QF_TTS_CACHE_DIR") or "./.qf_tts_cache")
        )
        self.base_dir = Path(root).expanduser().resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def cache_path(
        self,
        *,
        model: str,
        voice: str,
        instructions: str,
        response_format: str,
        text: str,
    ) -> Path:
        key_src = "|".join(
            [
                model.strip(),
                voice.strip(),
                (instructions or "").strip(),
                response_format.strip(),
                text.strip(),
            ]
        )
        key = _sha1(key_src)
        ext = response_format.strip().lower() or "mp3"
        return self.base_dir / f"{key}.{ext}"

    def get_or_create(
        self,
        *,
        role: str,
        voice: str,
        instructions: str,
        text: str,
        client: OpenAiTtsClient,
        response_format: str = "mp3",
        speed: float | None = None,
    ) -> CachedTtsItem:
        path = self.cache_path(
            model=client.model,
            voice=voice,
            instructions=instructions,
            response_format=response_format,
            text=text,
        )

        if not path.exists() or path.stat().st_size <= 0:
            res = client.synthesize(
                text=text,
                voice=voice,
                instructions=instructions,
                response_format=response_format,
                speed=speed,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(res.audio_bytes)

        return CachedTtsItem(
            role=role,
            voice=voice,
            text=text,
            path=path.resolve().as_uri(),
            response_format=response_format,
        )

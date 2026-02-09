# src/questforge/ai/tts/tts_client_openai.py
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TtsResult:
    """Audio bytes from TTS."""

    audio_bytes: bytes
    response_format: str


class OpenAiTtsClient:
    """OpenAI TTS client wrapper.

    This module intentionally isolates the OpenAI SDK dependency.

    Docs: https://platform.openai.com/docs/guides/text-to-speech
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = (model or os.getenv("QF_TTS_MODEL") or "gpt-4o-mini-tts").strip()
        self.api_key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "").strip()

    def synthesize(
        self,
        *,
        text: str,
        voice: str,
        instructions: str = "",
        response_format: str = "mp3",
        speed: float | None = None,
    ) -> TtsResult:
        """Synthesize text into speech and return audio bytes."""

        if not (text or "").strip():
            return TtsResult(audio_bytes=b"", response_format=response_format)

        if not self.api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is missing. Set OPENAI_API_KEY or pass api_key=..."
            )

        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "OpenAI SDK is not installed. Run `pip install openai` in your venv."
            ) from e

        client_kwargs: dict[str, str] = {}
        if self.api_key:
            client_kwargs["api_key"] = self.api_key
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        client = OpenAI(**client_kwargs)

        create_kwargs: dict[str, object] = {
            "model": self.model,
            "voice": voice,
            "input": text,
            "response_format": response_format,
        }
        if instructions:
            create_kwargs["instructions"] = instructions
        if speed is not None:
            create_kwargs["speed"] = float(speed)

        buf = bytearray()
        with client.audio.speech.with_streaming_response.create(**create_kwargs) as resp:
            for chunk in resp.iter_bytes():
                if chunk:
                    buf.extend(chunk)

        return TtsResult(audio_bytes=bytes(buf), response_format=response_format)

# src/questforge_server/tts_service.py
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

from openai import OpenAI
import hashlib
import os
from pathlib import Path
from typing import Iterable


def _key_fingerprint(k: str) -> str:
    k = (k or "")
    return f"len={len(k)} head={k[:8]!r} tail={k[-6:]!r} sha1={hashlib.sha1(k.encode('utf-8')).hexdigest()[:12]}"

print("[TTS_KEY]", _key_fingerprint(os.getenv("OPENAI_API_KEY","")), flush=True)

@dataclass(frozen=True)
class TtsResult:
    filename: str
    file_path: Path
    cache_hit: bool = False


def _norm_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def _clamp_speed(x: float) -> float:
    try:
        v = float(x)
    except Exception:
        v = 1.0
    if v < 0.6:
        v = 0.6
    if v > 1.4:
        v = 1.4
    return v


def _hash_key(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()




def synthesize_to_wav(
    *,
    text: str,
    out_dir: Path,
    voice: str = "alloy",
    model: Optional[str] = None,
    instructions: str = "",
    speed: float = 1.0,
) -> Optional[TtsResult]:
    """
    ✅ 保持你「舊版可成功」的做法：
    - client = OpenAI(api_key=OPENAI_API_KEY)（不帶 org/project/base_url）
    - 用 response_format="wav"
    - 只在遇到 TypeError（SDK 版本差異）時降級參數
    - cache key 要包含 voice/speed/instructions/model，避免回舊音
    """
    text = _norm_text(text)
    if not text:
        return None

    out_dir.mkdir(parents=True, exist_ok=True)

    api_key = (os.getenv("OPENAI_API_KEY", "") or "").strip()
    if not api_key:
        print("[tts_service] missing OPENAI_API_KEY", flush=True)
        return None

    model = (model or os.getenv("QF_TTS_MODEL", "").strip() or "gpt-4o-mini-tts").strip()
    voice = (voice or "").strip() or "alloy"
    instructions = (instructions or "").strip()
    speed = _clamp_speed(speed)

    # ✅ cache key 必須包含 voice/speed/instructions/model
    fp = _hash_key("v5", model, voice, f"{speed:.3f}", instructions, text)
    filename = f"{fp}.wav"
    file_path = out_dir / filename

    if file_path.exists() and file_path.stat().st_size > 512:
        return TtsResult(filename=filename, file_path=file_path, cache_hit=True)

    try:
        client = OpenAI(api_key=api_key)

        kwargs: Dict[str, Any] = {
            "model": model,
            "voice": voice,
            "input": text,
            "speed": speed,
            "response_format": "wav",
        }
        if instructions:
            kwargs["instructions"] = instructions

        try:
            audio = client.audio.speech.create(**kwargs)
        except TypeError:
            # ✅ SDK 不支援 response_format / instructions 時降級
            kwargs.pop("response_format", None)
            kwargs.pop("instructions", None)
            audio = client.audio.speech.create(**kwargs)

        # ✅ 能 stream_to_file 就用（新版 SDK）
        if hasattr(audio, "stream_to_file"):
            audio.stream_to_file(str(file_path))
        else:
            # ✅ 舊版相容：bytes/read/content
            if isinstance(audio, (bytes, bytearray)):
                data = bytes(audio)
            elif hasattr(audio, "read"):
                data = audio.read()
            elif hasattr(audio, "content"):
                data = audio.content
            else:
                raise TypeError(f"unexpected audio payload type: {type(audio)}")
            file_path.write_bytes(data)

        if not file_path.exists() or file_path.stat().st_size <= 512:
            print(
                "[tts_service] wrote empty/small wav:",
                {"path": str(file_path), "size": file_path.stat().st_size if file_path.exists() else 0,
                 "model": model, "voice": voice},
                flush=True,
            )
            return None


        return TtsResult(filename=filename, file_path=file_path, cache_hit=False)

    except Exception as e:
        print(
            "[tts_service] synth failed:",
            {
                "err": repr(e),
                "model": model,
                "voice": voice,
                "speed": speed,
                "text_len": len(text),
                "out_dir": str(out_dir),
            },
            flush=True,
        )
        return None

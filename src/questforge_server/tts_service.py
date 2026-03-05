# src/questforge_server/tts_service.py
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from questforge_server.storage.blob_store import BlobStore
    from questforge_server.pool.queue_client_upstash import UpstashRedisRest

from openai import OpenAI


# ----------------------------
# debug api key fingerprint
# ----------------------------
def _key_fingerprint(k: str) -> str:
    k = (k or "")
    return f"len={len(k)} head={k[:8]!r} tail={k[-6:]!r} sha1={hashlib.sha1(k.encode('utf-8')).hexdigest()[:12]}"


print("[TTS_KEY]", _key_fingerprint(os.getenv("OPENAI_API_KEY", "")), flush=True)


# ----------------------------
# models
# ----------------------------
@dataclass
class TtsResult:
    filename: str
    file_path: Path
    cache_hit: bool = False
    public_url: str = ""  # ✅ R2 public URL if uploaded; empty if local-only


@dataclass(frozen=True)
class TtsManifestItem:
    index: int
    file: str
    text: str
    role: str
    voice: str
    speed: float


# ----------------------------
# helpers
# ----------------------------
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


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _copy_file(src: Path, dst: Path) -> None:
    _ensure_dir(dst.parent)
    shutil.copyfile(str(src), str(dst))


def _default_cache_dir() -> Path:
    # 你 boot log 有顯示 tts_dir=/private/tmp/qf_cache/tts
    # 這裡跟你目前系統一致：優先用 env，沒有就走 /private/tmp/qf_cache/tts
    env = (os.getenv("QF_TTS_CACHE_DIR", "") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path("/private/tmp/qf_cache/tts").resolve()


def write_tts_manifest(
    *,
    out_dir: Path,
    ui_view_fp: str,
    items: List[TtsManifestItem],
) -> Path:
    """
    在 out_dir 寫入 manifest.json（順序 + text/role/voice）
    """
    _ensure_dir(out_dir)
    data = {
        "type": "tts_manifest_v1",
        "ui_view_fp": ui_view_fp,
        "items": [
            {
                "index": it.index,
                "file": it.file,
                "text": it.text,
                "role": it.role,
                "voice": it.voice,
                "speed": it.speed,
            }
            for it in items
        ],
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_tts_manifest(out_dir: Path) -> Optional[Dict[str, Any]]:
    path = out_dir / "manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ----------------------------
# main api
# ----------------------------
def synthesize_to_wav(
    *,
    text: str,
    out_dir: Path,
    voice: str = "alloy",
    model: Optional[str] = None,
    instructions: str = "",
    speed: float = 1.0,
    # ✅ 新增：想要固定檔名（例如 000.wav / 001.wav）就傳進來
    out_name: Optional[str] = None,
    # ✅ 新增：共享 cache 目錄（用 fp.wav 當 key）
    cache_dir: Optional[Path] = None,
    # ✅ Day B: 上傳到 R2 + 記錄 ready hash
    blob_store: Optional["BlobStore"] = None,
    blob_key: Optional[str] = None,             # R2 object key, e.g. tts_runs/view_fp/000.wav
    tts_redis: Optional["UpstashRedisRest"] = None,
    tts_ready_hash_key: Optional[str] = None,  # Redis hash key, e.g. qf:tts_ready:<view_fp>
    tts_ready_field: Optional[str] = None,     # field = str(index), e.g. "0"
    tts_ready_hash_ttl: int = 7200,            # seconds
) -> Optional[TtsResult]:
    """
    ✅ 你原本的「成功率高」方式保留，但新增兩個能力：
    1) out_name：可以把輸出固定成 000.wav 這種順序檔名
    2) cache_dir：先寫到共享 cache（fp.wav），再 copy 到 out_dir/out_name
       -> 這樣你同一段文字不同 view 仍可命中 cache
    """
    text = _norm_text(text)
    if not text:
        return None

    _ensure_dir(out_dir)

    api_key = (os.getenv("OPENAI_API_KEY", "") or "").strip()
    if not api_key:
        print("[tts_service] missing OPENAI_API_KEY", flush=True)
        return None

    model = (model or os.getenv("QF_TTS_MODEL", "").strip() or "gpt-4o-mini-tts").strip()
    voice = (voice or "").strip() or "alloy"
    instructions = (instructions or "").strip()
    speed = _clamp_speed(speed)

    # ✅ cache key：包含 voice/speed/instructions/model/text
    fp = _hash_key("v5", model, voice, f"{speed:.3f}", instructions, text)

    # 共享 cache 檔（fp.wav）
    cache_dir = (cache_dir or _default_cache_dir()).resolve()
    _ensure_dir(cache_dir)
    cache_path = cache_dir / f"{fp}.wav"

    # 最終輸出檔名（順序 or hash）
    final_name = (out_name or f"{fp}.wav").strip()
    file_path = out_dir / final_name

    # 1) 若 final 已存在 → 直接用
    if file_path.exists() and file_path.stat().st_size > 512:
        return TtsResult(filename=final_name, file_path=file_path, cache_hit=True)

    # 2) 若 cache 存在 → copy 到 final
    if cache_path.exists() and cache_path.stat().st_size > 512:
        _copy_file(cache_path, file_path)
        return TtsResult(filename=final_name, file_path=file_path, cache_hit=True)

    # 3) cache 不存在 → 生成到 cache，再 copy 到 final
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

        # 寫入 cache_path
        if hasattr(audio, "stream_to_file"):
            audio.stream_to_file(str(cache_path))
        else:
            if isinstance(audio, (bytes, bytearray)):
                data = bytes(audio)
            elif hasattr(audio, "read"):
                data = audio.read()
            elif hasattr(audio, "content"):
                data = audio.content
            else:
                raise TypeError(f"unexpected audio payload type: {type(audio)}")
            cache_path.write_bytes(data)

        if not cache_path.exists() or cache_path.stat().st_size <= 512:
            print(
                "[tts_service] wrote empty/small wav:",
                {"path": str(cache_path), "size": cache_path.stat().st_size if cache_path.exists() else 0,
                 "model": model, "voice": voice},
                flush=True,
            )
            return None

        # copy 到 final
        _copy_file(cache_path, file_path)

        if not file_path.exists() or file_path.stat().st_size <= 512:
            print(
                "[tts_service] copy to final failed/small:",
                {"path": str(file_path), "size": file_path.stat().st_size if file_path.exists() else 0},
                flush=True,
            )
            return None

        result = TtsResult(filename=final_name, file_path=file_path, cache_hit=False)

        # ✅ Day B: upload to R2 & record in Redis ready hash
        _maybe_upload_to_blob(
            result=result,
            blob_store=blob_store,
            blob_key=blob_key,
            tts_redis=tts_redis,
            tts_ready_hash_key=tts_ready_hash_key,
            tts_ready_field=tts_ready_field,
            tts_ready_hash_ttl=tts_ready_hash_ttl,
        )

        return result

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
                "out_name": final_name,
            },
            flush=True,
        )
        return None


# ----------------------------
# Day B helper: R2 upload + Redis ready hash
# ----------------------------

def _maybe_upload_to_blob(
    *,
    result: TtsResult,
    blob_store: Optional[Any],
    blob_key: Optional[str],
    tts_redis: Optional[Any],
    tts_ready_hash_key: Optional[str],
    tts_ready_field: Optional[str],
    tts_ready_hash_ttl: int = 7200,
) -> Optional[str]:
    """
    If blob_store is configured, upload WAV and record the public URL in Redis.
    Returns the public URL, or None if not configured / failed.
    """
    if blob_store is None or not blob_key:
        return None

    try:
        wav_bytes = result.file_path.read_bytes()
        public_url = blob_store.put_bytes(blob_key, wav_bytes, "audio/wav")

        if public_url and tts_redis and tts_ready_hash_key and tts_ready_field is not None:
            tts_redis.hset(tts_ready_hash_key, tts_ready_field, public_url)
            tts_redis.expire(tts_ready_hash_key, tts_ready_hash_ttl)

        # ✅ Store the R2 URL on the result for callers
        if public_url:
            result.public_url = public_url

        print(
            "[tts_service] blob upload ok",
            {"key": blob_key, "url": public_url[:60] if public_url else ""},
            flush=True,
        )
        return public_url

    except Exception as e:
        print(f"[tts_service] blob upload failed key={blob_key!r} err={e!r}", flush=True)
        return None
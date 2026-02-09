# src/questforge_server/routes_tts.py
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from questforge_server.tts_cache import TtsCache

router = APIRouter(prefix="/v1/tts", tags=["tts"])

_cache = TtsCache(Path(".qf_cache/tts"))

@router.get("/{file_id}.wav")
def get_tts_wav(file_id: str):
    p = _cache.cache_dir / f"{file_id}.wav"
    if not p.exists():
        raise HTTPException(status_code=404, detail="tts_not_found")
    return FileResponse(str(p), media_type="audio/wav")

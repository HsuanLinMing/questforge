# src/questforge_server/routes_voice_lab.py
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from questforge.ai.tts.voice_map import voice_for_role
from questforge_server.tts_service import synthesize_to_wav

router = APIRouter(prefix="/v1/tts", tags=["tts"])


class VoicesResponse(BaseModel):
    voices: List[str]
    recommended: dict


class PreviewRequest(BaseModel):
    text: str = Field(min_length=1)
    role: str = "旁白"
    voice: Optional[str] = None
    speed: float = 1.0
    instructions: str = ""
    model: Optional[str] = None


class PreviewResponse(BaseModel):
    status: str = "ok"
    url: str
    filename: str
    role: str
    voice: str
    speed: float
    model: str
    instructions: str = ""
    cache_hit: bool = False


# 你可以自由增減；Voice Lab 會顯示這些
VOICE_LIST = [
    "alloy",
    "ash",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
    "cedar",
    "marin",
]


@router.get("/voices", response_model=VoicesResponse)
def api_voices() -> VoicesResponse:
    return VoicesResponse(
        voices=VOICE_LIST,
        recommended={
            "旁白": "shimmer",
            "霏霏": "nova",
            "樂樂": "ash",
            "老師": "sage",
        },
    )


@router.post("/preview", response_model=PreviewResponse)
def api_preview(req: PreviewRequest, request: Request) -> PreviewResponse:
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text_required")

    role = (req.role or "旁白").strip()
    profile = voice_for_role(role)

    voice = (req.voice or "").strip() or profile.voice
    model = (req.model or "").strip() or "gpt-4o-mini-tts"
    instructions = (req.instructions or "").strip() or profile.instructions
    speed = float(req.speed or 1.0)

    out_dir = Path(".qf_cache/tts").resolve()
    r = synthesize_to_wav(
        text=text,
        out_dir=out_dir,
        voice=voice,
        model=model,
        instructions=instructions,
        speed=speed,
    )
    if r is None:
        raise HTTPException(status_code=500, detail="tts_failed")

    base = str(request.base_url).rstrip("/")
    url = f"{base}/static/tts/{r.filename}"

    return PreviewResponse(
        url=url,
        filename=r.filename,
        role=role,
        voice=voice,
        speed=speed,
        model=model,
        instructions=instructions,
        cache_hit=r.cache_hit,
    )

# src/questforge_server/main.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os
from dotenv import load_dotenv

from questforge_server.routes_game import router as game_router
from questforge_server.routes_voice_lab import router as tts_router

load_dotenv()

from dotenv import load_dotenv

load_dotenv()

# ✅ sanitize OPENAI_API_KEY (remove invisible separators)
_BAD = {"\u2028", "\u2029", "\n", "\r", "\t", "\x00"}


def _sanitize_env(key: str) -> None:
    v = os.getenv(key)
    if not v:
        return
    cleaned = "".join(ch for ch in v if ch not in _BAD).strip()
    if cleaned != v:
        os.environ[key] = cleaned


_sanitize_env("OPENAI_API_KEY")
_sanitize_env("OPENAI_ORG")
_sanitize_env("OPENAI_ORGANIZATION")
_sanitize_env("OPENAI_PROJECT")
_sanitize_env("OPENAI_BASE_URL")


def create_app() -> FastAPI:
    app = FastAPI(title="QuestForge Server", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ✅ TTS cache dir (server local)
    tts_dir = Path(".qf_cache/tts").resolve()
    tts_dir.mkdir(parents=True, exist_ok=True)

    # ✅ mount: GET /static/tts/<file>
    app.mount("/static/tts", StaticFiles(directory=str(tts_dir)), name="tts")

    app.include_router(game_router)

    app.include_router(tts_router)
    # ✅ TTS cache dir (server local)
    tts_dir = Path(".qf_cache/tts").resolve()
    tts_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/tts", StaticFiles(directory=str(tts_dir)), name="tts")

    # ✅ TTS runs dir (story-bundle)
    tts_runs_dir = Path(".qf_cache/tts_runs").resolve()
    tts_runs_dir.mkdir(parents=True, exist_ok=True)  # <- 這行是關鍵
    app.mount(
        "/static/tts_runs", StaticFiles(directory=str(tts_runs_dir)), name="tts_runs"
    )

    return app


app = create_app()

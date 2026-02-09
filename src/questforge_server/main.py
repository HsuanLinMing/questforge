# src/questforge_server/main.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from questforge_server.routes_game import router as game_router
from questforge_server.routes_voice_lab import router as tts_router

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
    
    return app

app = create_app()

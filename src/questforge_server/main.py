# src/questforge_server/main.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from questforge_server.routes_game import router as game_router


def create_app() -> FastAPI:
    app = FastAPI(title="QuestForge Server", version="0.1.0")

    # MVP: allow all. Later restrict to your app domain.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(game_router)
    return app


app = create_app()

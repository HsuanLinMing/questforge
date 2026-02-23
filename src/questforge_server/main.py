# src/questforge_server/main.py
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ✅ 本機開發才讀 .env（Render 會用 Dashboard 的 env vars）
try:
    from dotenv import load_dotenv  # type: ignore

    if (os.getenv("RENDER") or "").strip() == "":
        load_dotenv()
except Exception:
    pass

from questforge_server.routes_game import router as game_router
from questforge_server.routes_voice_lab import router as tts_router


def _commit_sha() -> str:
    return (os.getenv("COMMIT_SHA") or "").strip()


def _env_snapshot() -> dict:
    """Expose minimal env info for debugging deployment (no secrets)."""
    keys = [
        "AI_MODE",
        "QF_STORY_MODEL",
        "QF_STORY_MAX_ATTEMPTS",
        "QF_PREFETCH_ENABLED",
        "QF_TTS_ENABLED",
        "QF_TTS_PREWARM_ENABLED",
        "QF_TTS_ONLY_AI",
        "QF_POOL_DIR",
        "QF_AI_FALLBACK_TO_STATIC",
    ]
    return {k: (os.getenv(k) or "") for k in keys}


def create_app() -> FastAPI:
    app = FastAPI(title="QuestForge Server", version="0.1.0")

    def _cors_origins() -> list[str]:
        raw = (os.getenv("QF_CORS_ORIGINS") or "").strip()
        if not raw:
            return ["*"]  # 開發/測試
        return [x.strip() for x in raw.split(",") if x.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ✅ cache root (Render 建議用 /tmp)
    cache_root = Path(os.getenv("QF_CACHE_DIR") or "/tmp/qf_cache").resolve()
    cache_root.mkdir(parents=True, exist_ok=True)

    # ✅ TTS cache dir
    tts_dir = (cache_root / "tts")
    tts_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/tts", StaticFiles(directory=str(tts_dir)), name="tts")

    # ✅ story runs dir
    runs_dir = (cache_root / "tts_runs")
    runs_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/tts_runs", StaticFiles(directory=str(runs_dir)), name="tts_runs")

    @app.get("/")
    def root() -> dict:
        return {
            "ok": True,
            "service": "questforge_server",
            "endpoints": ["/health", "/v1/game/start", "/v1/game/choose", "/static/tts"],
        }

    @app.get("/health")
    def health() -> dict:
        return {
            "ok": True,
            "service": "questforge_server",
            "version": app.version,
            "commit_sha": _commit_sha(),
            "env": _env_snapshot(),
        }

    @app.on_event("startup")
    def _startup_log() -> None:
        # ✅ 讓你在 Render logs 一眼看出 env 有沒有吃到
        print("[BOOT] QuestForge Server starting...", flush=True)
        print(f"[BOOT] commit_sha={_commit_sha()}", flush=True)
        for k, v in _env_snapshot().items():
            print(f"[BOOT] {k}={v}", flush=True)
        print(f"[BOOT] tts_dir={tts_dir}", flush=True)
        print(f"[BOOT] runs_dir={runs_dir}", flush=True)

    app.include_router(game_router)
    app.include_router(tts_router)
    return app


app = create_app()

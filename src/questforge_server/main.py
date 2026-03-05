# src/questforge_server/main.py
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from questforge_server.routes_pool import router as pool_router

# ✅ 本機開發才讀 .env
try:
    from dotenv import load_dotenv  # type: ignore
    if (os.getenv("RENDER") or "").strip() == "":
        load_dotenv()
except Exception:
    pass

from questforge_server.routes_game import router as game_router
from questforge_server.routes_voice_lab import router as tts_router
from questforge_server.pool.pool_config import PoolConfig
from questforge_server.pool.pool_manager import StoryPoolManager
from questforge_server.worker.main import start_worker_in_thread  # ✅ NEW

_pool = StoryPoolManager(PoolConfig())


def _commit_sha() -> str:
    return (os.getenv("COMMIT_SHA") or "").strip()


def _env_snapshot() -> dict:
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
        "QF_UPSTASH_REDIS_REST_URL",
        "QF_WORKER_ENABLED",  # ✅ NEW
    ]
    snap = {k: (os.getenv(k) or "") for k in keys}

    if os.getenv("QF_UPSTASH_REDIS_REST_TOKEN"):
        snap["QF_UPSTASH_REDIS_REST_TOKEN"] = "***set***"
    else:
        snap["QF_UPSTASH_REDIS_REST_TOKEN"] = ""

    return snap


def create_app() -> FastAPI:
    app = FastAPI(title="QuestForge Server", version="0.1.0")

    def _cors_origins() -> list[str]:
        raw = (os.getenv("QF_CORS_ORIGINS") or "").strip()
        if not raw:
            return ["*"]
        return [x.strip() for x in raw.split(",") if x.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ✅ 統一 cache root
    cache_root = Path(os.getenv("QF_CACHE_DIR") or "/tmp/qf_cache").resolve()
    cache_root.mkdir(parents=True, exist_ok=True)

    # ---------------------------
    # static mounts
    # ---------------------------

    tts_dir = cache_root / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/tts", StaticFiles(directory=str(tts_dir)), name="tts")

    runs_dir = cache_root / "tts_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/tts_runs", StaticFiles(directory=str(runs_dir)), name="tts_runs")

    runtime_sample_dir = cache_root / "runtime_sample"
    runtime_sample_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/static/runtime_sample",
        StaticFiles(directory=str(runtime_sample_dir)),
        name="runtime_sample",
    )

    # pool tts (keep your existing on-disk location)
    pool_tts_dir = Path(".qf_cache/pool_ai/tts").resolve()
    pool_tts_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/static/pool_tts",
        StaticFiles(directory=str(pool_tts_dir)),
        name="pool_tts",
    )

    # ---------------------------
    # health / root
    # ---------------------------

    @app.get("/")
    def root() -> dict:
        return {
            "ok": True,
            "service": "questforge_server",
            "endpoints": [
                "/health",
                "/v1/game/start",
                "/v1/game/choose",
                "/static/tts",
                "/static/tts_runs",
                "/static/runtime_sample",
                "/static/pool_tts",
            ],
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

    # ---------------------------
    # startup
    # ---------------------------

    @app.on_event("startup")
    def _startup_log() -> None:
        print("[BOOT] QuestForge Server starting...", flush=True)
        print(f"[BOOT] commit_sha={_commit_sha()}", flush=True)
        for k, v in _env_snapshot().items():
            print(f"[BOOT] {k}={v}", flush=True)

        print(f"[BOOT] cache_root={cache_root}", flush=True)
        print(f"[BOOT] tts_dir={tts_dir}", flush=True)
        print(f"[BOOT] runs_dir={runs_dir}", flush=True)
        print(f"[BOOT] runtime_sample_dir={runtime_sample_dir}", flush=True)
        print(f"[BOOT] pool_tts_dir={pool_tts_dir}", flush=True)

        # ✅ warmup ensure_pool
        try:
            _pool.ensure_pool()
            print("[POOL] warmup ensure_pool ok", flush=True)
        except Exception as e:
            print(f"[POOL] warmup ensure_pool fail err={e!r}", flush=True)

        try:
            start_worker_in_thread()
            print("[BOOT] Background AI worker thread started", flush=True)
        except Exception as e:
            print(f"[BOOT] Worker thread failed: {e!r}", flush=True)

        # ✅ Start periodic local-disk cleanup thread (R2 is long-term; local is ephemeral cache)
        try:
            import time as _time
            import threading as _threading
            import shutil as _sh

            _tts_ttl_h = float(os.getenv("QF_LOCAL_TTS_TTL_HOURS", "6") or "6")
            _pool_tts_ttl_h = float(os.getenv("QF_LOCAL_POOL_TTS_TTL_HOURS", "168") or "168")
            _cleanup_interval_s = float(os.getenv("QF_CLEANUP_INTERVAL_SECONDS", "1800") or "1800")

            _cleanup_dirs = [
                (runtime_sample_dir, _tts_ttl_h),
                (runs_dir, _tts_ttl_h),
                (Path(".qf_cache/pool_ai/tts").resolve(), _pool_tts_ttl_h),
            ]

            def _prune_once(base: Path, max_age_hours: float) -> int:
                if not base.exists():
                    return 0
                cutoff = _time.time() - max_age_hours * 3600
                removed = 0
                for child in base.iterdir():
                    try:
                        if child.stat().st_mtime < cutoff:
                            if child.is_dir():
                                _sh.rmtree(str(child), ignore_errors=True)
                            else:
                                child.unlink(missing_ok=True)
                            removed += 1
                    except Exception:
                        pass
                return removed

            def _cleanup_loop() -> None:
                # Run once at startup, then every interval
                while True:
                    for base, ttl_h in _cleanup_dirs:
                        try:
                            n = _prune_once(base, ttl_h)
                            if n:
                                print(f"[CLEANUP] removed {n} old entries from {base}", flush=True)
                        except Exception as ex:
                            print(f"[CLEANUP] error {base}: {ex!r}", flush=True)
                    _time.sleep(_cleanup_interval_s)

            t = _threading.Thread(target=_cleanup_loop, name="qf-cache-cleanup", daemon=True)
            t.start()
            print(f"[BOOT] cache cleanup thread started interval={_cleanup_interval_s}s", flush=True)
        except Exception as e:
            print(f"[BOOT] cache cleanup start error: {e!r}", flush=True)


    # routers
    app.include_router(game_router)
    app.include_router(tts_router)
    app.include_router(pool_router)

    return app


app = create_app()
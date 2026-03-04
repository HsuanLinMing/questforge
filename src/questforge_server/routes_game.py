# src/questforge_server/routes_game.py
from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
import traceback
import time
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel, Field

from questforge_server.progress import ProgressLogger
from questforge.engine.actions import PlayerAction
from questforge.engine.session import GameSession, StepResult
from questforge_server.session_store import SessionStore
from questforge_server.tts_service import synthesize_to_wav
from questforge.ai.tts.voice_map import voice_for_role
from questforge_server.pool.pool_config import PoolConfig
from questforge_server.pool.pool_manager import StoryPoolManager

_pool = StoryPoolManager(PoolConfig())
router = APIRouter(prefix="/v1/game", tags=["game"])

# ✅ dev-only in-memory store
store = SessionStore()


# ----------------------------
# Pydantic Schemas
# ----------------------------


class StartRequest(BaseModel):
    seed: Optional[int] = None


class ChooseRequest(BaseModel):
    session_id: str
    choice_index: int


class ReplayRequest(BaseModel):
    session_id: str


class EndFlowRequest(BaseModel):
    session_id: str
    end_action: str  # go_epilogue / restart_case / switch_case / quit


class SetReasonsRequest(BaseModel):
    session_id: str
    reason_ids: List[str] = Field(default_factory=list)
    reason_text: str = ""


class ConfirmQuizRequest(BaseModel):
    session_id: str
    answers: List[Any] = Field(default_factory=list)
    skipped: bool = False


class QuitRequest(BaseModel):
    session_id: str


class AccuseEvaluateRequest(BaseModel):
    session_id: str
    recognized_text: str
    node_id: Optional[str] = None


class AccuseEvaluateResponse(BaseModel):
    decision: str  # "accuse" | "defer_to_teacher"
    score: float = 0.0
    threshold: float = 0.6
    fifi_reply: str
    matched_choice_index: Optional[int] = None
    matched_choice_text: Optional[str] = None
    defer_choice_index: Optional[int] = None
    ending_kind: Optional[str] = None  # "clear" | "nudge" | "defer"
    auto_submit: Optional[bool] = None
    debug: Optional[Dict[str, Any]] = None


class BundleResponse(BaseModel):
    # Flutter 端用的是 bundle.view/ask/quiz/end，所以固定保持這四個 key
    view: Optional[Dict[str, Any]] = None
    ask: Optional[Dict[str, Any]] = None
    quiz: Optional[Dict[str, Any]] = None
    end: Optional[Dict[str, Any]] = None
    commands: Optional[List[Dict[str, Any]]] = None  # ✅ playlist 放這


class StepResponse(BaseModel):
    session_id: str
    bundle: BundleResponse
    events: List[str] = Field(default_factory=list)
    is_over: bool = False


# ----------------------------
# Env helpers
# ----------------------------


def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "y", "on")


# ----------------------------
# Helpers
# ----------------------------


def _get_session_or_404(session_id: str) -> GameSession:
    sid = (session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="missing_session_id")

    sess = store.get(sid)
    if sess is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    return sess


def _to_json_dict(obj: Any) -> Optional[Dict[str, Any]]:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj

    if hasattr(obj, "to_json"):
        try:
            return obj.to_json()
        except Exception:
            pass
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            pass
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass

    try:
        return dict(obj.__dict__)
    except Exception:
        return None


def _safe_rmtree(p: Path) -> None:
    try:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


def _runs_root() -> Path:
    return Path(".qf_cache/tts_runs").resolve()


def _bundle_to_raw_dict(bundle: BundleResponse) -> Dict[str, Any]:
    try:
        return bundle.model_dump()  # pydantic v2
    except Exception:
        try:
            return bundle.dict()  # pydantic v1
        except Exception:
            return {
                "view": bundle.view,
                "ask": bundle.ask,
                "quiz": bundle.quiz,
                "end": bundle.end,
                "commands": bundle.commands,
            }


# ----------------------------
# TTS helpers
# ----------------------------

_ALLOWED_ROLES = {
    "旁白",
    "霏霏",
    "樂樂",
    "老師",
    "narrator",
    "teacher",
    "child_female",
    "child_male",
}


def _split_paragraphs(narration: str) -> List[str]:
    return [x.strip() for x in (narration or "").split("\n\n") if x.strip()]


def _parse_paragraph(p: str) -> tuple[str, str]:
    s = (p or "").strip()
    if not s:
        return ("旁白", "")

    first_line, *rest_lines = s.splitlines()
    first_line = first_line.strip()
    rest_text = "\n".join([x.strip() for x in rest_lines]).strip()
    full_text = s

    if "：" in first_line:
        role, rest = first_line.split("：", 1)
        role = role.strip()
        text0 = (rest or "").strip()
        if role in _ALLOWED_ROLES and text0:
            text = text0
            if rest_text:
                text = text0 + "\n" + rest_text
            return (role, text)

    return ("旁白", full_text)


def _voice_speed_for_role(role: str) -> float:
    if role in ("旁白", "narrator"):
        return 0.95
    if role in ("霏霏", "child_female"):
        return 1.05
    if role in ("樂樂", "child_male"):
        return 1.12
    if role in ("老師", "teacher"):
        return 0.98
    return 1.0


def _view_fp_for_narration(narration: str) -> str:
    # ✅ 必須固定算法才能共用 cache
    return hashlib.sha1(("v2|" + (narration or "")).encode("utf-8")).hexdigest()


def _prewarm_story_tts_all_nodes(
    *, session_id: str, run_id: str, session: GameSession
) -> None:
    """
    ✅ 補齊「整個故事」所有 node 的 narration 語音
    """
    try:
        nodes = getattr(session, "nodes", {}) or {}
        base_dir = _runs_root() / session_id / run_id
        base_dir.mkdir(parents=True, exist_ok=True)

        clips = 0
        for node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            narration = (node.get("narration") or "").strip()
            if not narration:
                continue

            view_fp = _view_fp_for_narration(narration)
            out_dir = base_dir / view_fp
            out_dir.mkdir(parents=True, exist_ok=True)

            for p in _split_paragraphs(narration):
                role, text = _parse_paragraph(p)
                spoken_text = (text or "").strip()
                if not spoken_text:
                    continue

                profile = voice_for_role(role)
                speed = _voice_speed_for_role(role)

                r = synthesize_to_wav(
                    text=spoken_text,
                    out_dir=out_dir,
                    voice=profile.voice,
                    instructions=profile.instructions,
                    speed=speed,
                )
                if r is not None:
                    clips += 1

        print(
            f"[PREWARM_ALL] ok sid={session_id[:6]} run={run_id[:6]} clips={clips}",
            flush=True,
        )
    except Exception as e:
        print(f"[PREWARM_ALL] fail sid={session_id[:6]} err={e!r}", flush=True)


def _build_ai_playlist(
    request: Request,
    view_json: Dict[str, Any],
) -> Optional[Dict[str, Any]]:

    runtime = view_json.get("runtime") or {}
    story = runtime.get("story") or {}

    story_id = str(story.get("story_id") or "").strip()
    if not story_id:
        return None

    narration = (view_json.get("narration") or "").strip()
    if not narration:
        return None

    view_fp = _view_fp_for_narration(narration)

    pool_root = Path(".qf_cache/pool_ai").resolve()
    dirp = pool_root / "tts" / story_id / view_fp

    if not dirp.exists():
        return None

    manifest_path = dirp / "manifest.json"
    if not manifest_path.exists():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    items_raw = manifest.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        return None

    base = str(request.base_url).rstrip("/")
    items: List[Dict[str, Any]] = []

    for it in items_raw:
        if not isinstance(it, dict):
            continue

        idx = it.get("index")
        file = str(it.get("file") or "").strip()
        if not file:
            continue

        url = f"{base}/static/pool_tts/{story_id}/{view_fp}/{file}"

        items.append(
            {
                "index": int(idx) if isinstance(idx, int) else 0,
                "format": "wav",
                "path": url,
                "text": str(it.get("text") or ""),
                "role": str(it.get("role") or ""),
                "voice": str(it.get("voice") or ""),
                "speed": float(it.get("speed") or 1.0),
                "story_id": story_id,
                "ui_view_fp": str(manifest.get("ui_view_fp") or ""),
            }
        )

    if not items:
        return None

    items.sort(key=lambda x: int(x.get("index") or 0))

    return {
        "type": "tts_playlist_v1",
        "scope": "view",
        "status": "ok",
        "source": "pool",
        "story_id": story_id,
        "view_fp": view_fp,
        "ui_view_fp": str(manifest.get("ui_view_fp") or ""),
        "items": items,
    }

def _try_make_pooled_tts_cmd(
    *, request: Request, view_json: Dict[str, Any], background_tasks: Optional[BackgroundTasks] = None
) -> Optional[Dict[str, Any]]:

    runtime = view_json.get("runtime") or {}
    story = runtime.get("story") or {}

    source = str(story.get("source") or "").strip().lower()

    # ✅ AI → 讀 pooled manifest
    if source == "ai":
        return _build_ai_playlist(request, view_json)

    # ✅ SAMPLE → 即時第一段語音
    if source == "sample":
        return _build_sample_runtime_tts(request, view_json, background_tasks)

    return None
# ----------------------------
# Bundle builder
# ----------------------------
def _build_sample_runtime_tts(
    request: Request, view_json: Dict[str, Any], background_tasks: Optional[BackgroundTasks] = None
):
    narration = (view_json.get("narration") or "").strip()
    if not narration:
        return None

    paras = _split_paragraphs(narration)
    if not paras:
        return None

    # ✅ 生成所有段落：
    # - 同步只做前 N 段（讓 API 秒回）
    # - 其餘段落用 BackgroundTasks 補齊
    # - 檔名固定為 000.wav / 001.wav ...（避免預測 hash 出錯）
    sync_limit = int(os.getenv("QF_TTS_SYNC_LIMIT", "1") or "1")
    if sync_limit < 1:
        sync_limit = 1

    items: List[Dict[str, Any]] = []

    # ✅ 跟 main.py mount 同一個 cache_root/runtime_sample
    cache_root = Path(os.getenv("QF_CACHE_DIR") or "/tmp/qf_cache").resolve()
    base_root = (cache_root / "runtime_sample").resolve()
    base_root.mkdir(parents=True, exist_ok=True)

    # ✅ 每個 view 用自己的資料夾（避免互相覆蓋）
    ui_view_fp = _view_fp_for_narration(narration)
    out_dir = (base_root / ui_view_fp).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    base = str(request.base_url).rstrip("/")

    def _out_name(i: int) -> str:
        return f"{i:03d}.wav"

    def _synth_para(i: int, p: str) -> None:
        role, text = _parse_paragraph(p)
        spoken_text = (text or "").strip()
        if not spoken_text:
            return

        profile = voice_for_role(role)
        speed = _voice_speed_for_role(role)

        r = synthesize_to_wav(
            text=spoken_text,
            out_dir=out_dir,
            out_name=_out_name(i),
            voice=profile.voice,
            instructions=profile.instructions,
            speed=speed,
        )
        if not r:
            return

        try:
            print(
                "[RUNTIME_SAMPLE_TTS] wrote",
                {"file": str(r.file_path), "size": r.file_path.stat().st_size},
                flush=True,
            )
        except Exception:
            pass

    for i, para in enumerate(paras):
        role, text = _parse_paragraph(para)
        spoken_text = (text or "").strip()
        if not spoken_text:
            continue

        profile = voice_for_role(role)
        speed = _voice_speed_for_role(role)

        # 🚀 同步只做前 sync_limit 段；其餘段落放背景
        if i < sync_limit or background_tasks is None:
            _synth_para(i, para)
        else:
            background_tasks.add_task(_synth_para, i, para)

        filename = _out_name(i)
        url = f"{base}/static/runtime_sample/{ui_view_fp}/{filename}"

        # ✅ ready: 讓前端知道目前檔案是否已存在（可用來等待，不要直接 skip）
        ready = (out_dir / filename).exists()
        items.append(
            {
                "index": i,
                "format": "wav",
                "path": url,
                "text": spoken_text,
                "role": role,
                "voice": profile.voice,
                "speed": speed,
                "ready": bool(ready),
            }
        )
        
    if not items:
        return None

    return {
        "type": "tts_playlist_v1",
        "scope": "view",
        "status": "ok",
        "source": "runtime_sample",
        "view_fp": ui_view_fp,
        "ui_view_fp": ui_view_fp,
        "items": items,
    }


def _mark_ready_for_existing_files(cmd: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure each item has a boolean 'ready' field based on file existence."""
    try:
        items = cmd.get("items")
        if not isinstance(items, list):
            return cmd

        for it in items:
            if not isinstance(it, dict):
                continue
            path = str(it.get("path") or "")
            if "ready" in it:
                continue

            # We can only reliably check for our known static dirs.
            # - /static/runtime_sample/<fp>/<nnn>.wav
            # - /static/pool_tts/<story>/<view_fp>/<file>
            ready = None
            if "/static/runtime_sample/" in path:
                try:
                    rel = path.split("/static/runtime_sample/", 1)[1]
                    cache_root = Path(os.getenv("QF_CACHE_DIR") or "/tmp/qf_cache").resolve()
                    p = (cache_root / "runtime_sample" / rel).resolve()
                    ready = p.exists() and p.stat().st_size > 512
                except Exception:
                    ready = False
            elif "/static/pool_tts/" in path:
                try:
                    rel = path.split("/static/pool_tts/", 1)[1]
                    p = (Path(".qf_cache/pool_ai/tts").resolve() / rel).resolve()
                    ready = p.exists() and p.stat().st_size > 512
                except Exception:
                    ready = False

            if ready is not None:
                it["ready"] = bool(ready)

        return cmd
    except Exception:
        return cmd


class TtsStatusResp(BaseModel):
    ready: bool
    ready_count: int
    paths: List[str]
    missing: List[int]
    command: Optional[Dict[str, Any]] = None

@router.get("/tts_status", response_model=TtsStatusResp)
def get_tts_status(view_fp: str, count: int, request: Request, session_id: Optional[str] = None):
    # This checks in both potential locations (AI pools and runs) and returns status
    base = str(request.base_url).rstrip("/")
    cache_root = Path(os.getenv("QF_CACHE_DIR") or "/tmp/qf_cache").resolve()

    # Check runtime_sample location first
    out_dir_sample = (cache_root / "runtime_sample" / view_fp).resolve()

    # If session_id is provided, check tts_runs too
    out_dir_runs: Optional[Path] = None
    run_id = ""
    if session_id:
        run_id = store.get_current_run_id(session_id) or ""
        out_dir_runs = _runs_root() / session_id / run_id / view_fp

    ready_paths = []
    missing = []
    items: List[Dict[str, Any]] = []

    for i in range(count):
        filename = f"{i:03d}.wav"
        found = False
        url = f"{base}/static/runtime_sample/{view_fp}/{filename}"  # default

        # Check sample dir
        if out_dir_sample.exists() and (out_dir_sample / filename).exists():
            url = f"{base}/static/runtime_sample/{view_fp}/{filename}"
            ready_paths.append(url)
            found = True
        # Check runs dir
        elif out_dir_runs and out_dir_runs.exists() and (out_dir_runs / filename).exists():
            url = f"{base}/static/tts_runs/{session_id}/{run_id}/{view_fp}/{filename}"
            ready_paths.append(url)
            found = True

        if not found:
            missing.append(i)

        items.append({
            "index": i,
            "format": "wav",
            "path": url,
            "role": "",
            "voice": "",
            "text": "",
            "speed": 1.0,
            "ready": found,
        })

    cmd: Dict[str, Any] = {
        "type": "tts_playlist_v1",
        "scope": "view",
        "status": "ok",
        "source": "tts_status",
        "view_fp": view_fp,
        "ui_view_fp": view_fp,
        "total_count": count,
        "items": items,
    }

    return TtsStatusResp(
        ready=(len(missing) == 0),
        ready_count=len(ready_paths),
        paths=ready_paths,
        missing=missing,
        command=cmd,
    )
def _bundle_from_session_and_step(
    *,
    request: Request,
    session_id: str,
    run_id: str,
    session: GameSession,
    step: Optional[StepResult],
    background_tasks: Optional[BackgroundTasks] = None,
) -> Tuple[BundleResponse, List[str], bool]:
    """
    產出 Flutter 端吃的 bundle：
    - bundle.view (NodeView json)
    - bundle.ask / quiz / end (overlay command)
    - bundle.commands (tts_playlist_v1 等)
    並把 commands 同步塞到 view.commands（方便 debug）
    """

    def _inject_story_meta(
        view_json: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if view_json is None:
            return None
        try:
            story_meta = getattr(session.state, "vars", {}).get("qf_story")
        except Exception:
            story_meta = None
        if not story_meta:
            return view_json
        v = dict(view_json)
        runtime = dict(v.get("runtime") or {})
        runtime["story"] = story_meta
        v["runtime"] = runtime
        return v

    def _make_tts_cmd_from_view_json(
        view_json: Optional[Dict[str, Any]],
        bg_tasks: Optional[BackgroundTasks] = None,
    ) -> Optional[Dict[str, Any]]:
        # ✅ TTS 總開關
        if not _env_bool("QF_TTS_ENABLED", True):
            return None
        pooled = _try_make_pooled_tts_cmd(
            request=request,
            view_json=view_json,
            background_tasks=bg_tasks,
        )
        if pooled is not None:
            return pooled

        # ✅ 只讓 AI case 做 TTS（你如果要 pool 也播：把 env 設為 0）
        if _env_bool("QF_TTS_ONLY_AI", False):
            case_id = str(getattr(session, "case_id", "") or "")
            if not case_id.startswith("ai_"):
                return None

        if not view_json:
            return None

        narration = (view_json.get("narration") or "").strip()
        if not narration:
            return None

        raw_paras = _split_paragraphs(narration)
        if not raw_paras:
            return None

        # ✅ Sample/Static：只先產第一段，讓玩家立刻能聽
        # AI：允許完整段落（或之後改成由 worker 預產）
        try:
            # 優先用 runtime.story.source（如果有）
            runtime = (
                (view_json.get("runtime") or {}) if isinstance(view_json, dict) else {}
            )
            story = (runtime.get("story") or {}) if isinstance(runtime, dict) else {}
            source = str(story.get("source") or "").strip().lower()
        except Exception:
            source = ""

        is_ai = source == "ai"
        # ✅ 移除: if not is_ai: raw_paras = raw_paras[:1]
        # 讓這段與 AI 一樣，都產出完整的 TTS playlist 給使用者聽

        view_fp = _view_fp_for_narration(narration)

        out_dir = _runs_root() / session_id / run_id / view_fp
        out_dir.mkdir(parents=True, exist_ok=True)

        base = str(request.base_url).rstrip("/")
        items: List[Dict[str, Any]] = []

        sync_limit = int(os.getenv("QF_TTS_SYNC_LIMIT", "1") or "1")
        if sync_limit < 1:
            sync_limit = 1

        def _out_name(i: int) -> str:
            return f"{i:03d}.wav"

        def _synth_para(i: int, p: str) -> None:
            role, text = _parse_paragraph(p)
            spoken_text = (text or "").strip()
            if not spoken_text:
                return

            profile = voice_for_role(role)
            speed = _voice_speed_for_role(role)

            r = synthesize_to_wav(
                text=spoken_text,
                out_dir=out_dir,
                out_name=_out_name(i),
                voice=profile.voice,
                instructions=profile.instructions,
                speed=speed,
            )
            if not r:
                return

        for i, p in enumerate(raw_paras):
            role, text = _parse_paragraph(p)
            spoken_text = (text or "").strip()
            if not spoken_text:
                continue

            profile = voice_for_role(role)
            speed = _voice_speed_for_role(role)

            # 🚀 同步只做前 sync_limit 段；其餘段落放背景
            if i < sync_limit or bg_tasks is None:
                _synth_para(i, p)
            else:
                bg_tasks.add_task(_synth_para, i, p)

            filename = _out_name(i)
            url = f"{base}/static/tts_runs/{session_id}/{run_id}/{view_fp}/{filename}"
            ready = (out_dir / filename).exists()

            items.append(
                {
                    "index": i,
                    "text": spoken_text,  # debug
                    "role": role,  # debug
                    "voice": profile.voice,  # debug
                    "speed": speed,  # debug
                    "format": "wav",
                    "path": url,
                    "ready": bool(ready),
                }
            )

        if not items:
            return None

        return {
            "type": "tts_playlist_v1",
            "scope": "view",
            "status": "ok",
            "view_fp": view_fp,
            "total_count": len(raw_paras),
            "items": items,
        }

    # ----------------------------
    # start: step is None
    # ----------------------------
    if step is None:
        view_obj = session.get_view()
        view_json = _to_json_dict(view_obj)
        view_json = _inject_story_meta(view_json)

        tts_cmd = _make_tts_cmd_from_view_json(view_json, background_tasks)
        commands_out = [tts_cmd] if tts_cmd else []

        if view_json is not None:
            v = dict(view_json)
            v["commands"] = commands_out if commands_out else None
            view_json = v

        return (
            BundleResponse(
                view=view_json, ask=None, quiz=None, end=None, commands=commands_out
            ),
            [],
            False,
        )

    # ----------------------------
    # step: view + overlays + playlist
    # ----------------------------
    events = list(step.events or [])
    is_over = bool(step.is_over)

    view_json: Optional[Dict[str, Any]] = _to_json_dict(step.view)
    view_json = _inject_story_meta(view_json)

    ask = None
    quiz = None
    end = None

    for cmd in step.commands or []:
        if not isinstance(cmd, dict):
            continue
        t = (cmd.get("type") or "").strip()
        if t == "ask_reason":
            ask = cmd
        elif t == "confirm_quiz":
            quiz = cmd
        elif t in ("show_end_screen", "show_reasoning_feedback"):
            end = cmd

    tts_cmd = _make_tts_cmd_from_view_json(view_json, background_tasks)
    commands_out = [tts_cmd] if tts_cmd else []

    if view_json is not None:
        v = dict(view_json)
        v["commands"] = commands_out if commands_out else None
        view_json = v

    return (
        BundleResponse(
            view=view_json, ask=ask, quiz=quiz, end=end, commands=commands_out
        ),
        events,
        is_over,
    )


def _step_and_build_response(
    *,
    request: Request,
    session_id: str,
    session: GameSession,
    action: PlayerAction,
    background_tasks: Optional[BackgroundTasks] = None,
) -> StepResponse:
    step = session.step(action)
    run_id = store.get_current_run_id(session_id) or ""
    bundle, events, is_over = _bundle_from_session_and_step(
        request=request,
        session_id=session_id,
        run_id=run_id,
        session=session,
        step=step,
        background_tasks=background_tasks,
    )
    return StepResponse(
        session_id=session_id, bundle=bundle, events=events, is_over=is_over
    )


# ----------------------------
# ✅ 方案 B-1：Bootstrap pipeline（順序：current_tts -> ai1+tts -> ai2+tts）
# ----------------------------


def _bootstrap_background_pipeline(
    request: Request, session_id: str, seed: Optional[int]
) -> None:
    """
    - /start 先回第一頁（低延遲）
    - 背景依序做：
      1) current 全故事 TTS
      2) next1 -> AI + 全故事 TTS + prefetch first bundle
      3) next2 -> AI + 全故事 TTS + prefetch first bundle
    - 同 sid 只允許一條 pipeline（store.bg_running lock）
    """
    # 你想全程都跑就設 True；想關閉就設 QF_PREFETCH_ENABLED=0
    if not _env_bool("QF_PREFETCH_ENABLED", True):
        return
    if not store.try_mark_bg_running(session_id):
        return

    def _job() -> None:
        sid6 = session_id[:6]
        try:
            tts_enabled = _env_bool("QF_TTS_ENABLED", True)
            prewarm_enabled = _env_bool("QF_TTS_PREWARM_ENABLED", True)

            # 1) current：補齊整故事 TTS（第一頁已在 start 的 bundle 產掉）
            if tts_enabled and prewarm_enabled:
                cur = store.get(session_id)
                cur_run = store.get_current_run_id(session_id) or ""
                if cur is not None and cur_run:
                    print(f"[BOOT] sid={sid6} stage=current_tts", flush=True)
                    _prewarm_story_tts_all_nodes(
                        session_id=session_id, run_id=cur_run, session=cur
                    )

            # 2) next1：build AI -> prewarm all -> prefetch first bundle
            print(f"[BOOT] sid={sid6} stage=build_ai1", flush=True)
            ok1 = store.build_ai_into_next1(
                session_id=session_id, seed=seed, stage="bootstrap_ai1"
            )
            if ok1:
                next1 = store.get_next1(session_id)
                run1 = store.get_next1_run_id(session_id) or ""
                if tts_enabled and prewarm_enabled and next1 is not None and run1:
                    print(f"[BOOT] sid={sid6} stage=ai1_tts", flush=True)
                    _prewarm_story_tts_all_nodes(
                        session_id=session_id, run_id=run1, session=next1
                    )

                if next1 is not None and run1:
                    bundle, _, _ = _bundle_from_session_and_step(
                        request=request,
                        session_id=session_id,
                        run_id=run1,
                        session=next1,
                        step=None,
                    )
                    store.set_next1_prefetched_bundle(
                        session_id, _bundle_to_raw_dict(bundle)
                    )
                    print(f"[BOOT] sid={sid6} ai1_prefetched ok", flush=True)

            # 3) next2：build AI -> prewarm all -> prefetch first bundle
            print(f"[BOOT] sid={sid6} stage=build_ai2", flush=True)
            ok2 = store.build_ai_into_next2(
                session_id=session_id, seed=seed, stage="bootstrap_ai2"
            )
            if ok2:
                next2 = store.get_next2(session_id)
                run2 = store.get_next2_run_id(session_id) or ""
                if tts_enabled and prewarm_enabled and next2 is not None and run2:
                    print(f"[BOOT] sid={sid6} stage=ai2_tts", flush=True)
                    _prewarm_story_tts_all_nodes(
                        session_id=session_id, run_id=run2, session=next2
                    )

                if next2 is not None and run2:
                    bundle, _, _ = _bundle_from_session_and_step(
                        request=request,
                        session_id=session_id,
                        run_id=run2,
                        session=next2,
                        step=None,
                    )
                    store.set_next2_prefetched_bundle(
                        session_id, _bundle_to_raw_dict(bundle)
                    )
                    print(f"[BOOT] sid={sid6} ai2_prefetched ok", flush=True)

        except Exception as e:
            print(f"[BOOT] sid={session_id[:6]} fail err={e!r}", flush=True)
            print(traceback.format_exc(), flush=True)
        finally:
            store.mark_bg_done(session_id)

    threading.Thread(target=_job, daemon=True).start()


# ----------------------------
# Accuse evaluator helpers（你原本那套保留）
# ----------------------------


def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^\u4e00-\u9fff0-9a-z]+", "", s)
    return s


ADULT_FALLBACK_KEYWORDS = [
    "交給大人",
    "交給會長",
    "會長",
    "警衛",
    "我不確定",
    "不確定",
    "不知道",
    "我不知道",
    "先去確認",
    "先問一下",
    "等一下問",
    "我想再想一下",
]


def _looks_like_teacher_intent(text: str) -> bool:
    r = _norm_text(text)
    if not r:
        return False
    for k in ADULT_FALLBACK_KEYWORDS:
        if _norm_text(k) in r:
            return True
    return False


def _iter_choices(view_obj_or_json: Any) -> List[Tuple[Optional[int], str]]:
    if view_obj_or_json is None:
        return []
    out: List[Tuple[Optional[int], str]] = []

    if isinstance(view_obj_or_json, dict):
        raw_choices = view_obj_or_json.get("choices") or []
        for c in raw_choices:
            if c is None:
                continue
            if isinstance(c, dict):
                idx = c.get("index")
                txt = c.get("text")
            else:
                idx = getattr(c, "index", None)
                txt = getattr(c, "text", None)
            try:
                idx_int = int(idx) if idx is not None else None
            except Exception:
                idx_int = None
            out.append((idx_int, str(txt or "").strip()))
        return out

    raw_choices = getattr(view_obj_or_json, "choices", None) or []
    for c in raw_choices:
        if c is None:
            continue
        idx = getattr(c, "index", None)
        txt = getattr(c, "text", None)
        try:
            idx_int = int(idx) if idx is not None else None
        except Exception:
            idx_int = None
        out.append((idx_int, str(txt or "").strip()))
    return out


def _find_teacher_choice_index(view_obj_or_json: Any) -> Optional[int]:
    for idx, t in _iter_choices(view_obj_or_json):
        if idx is None:
            continue
        for k in ADULT_FALLBACK_KEYWORDS:
            if k in t:
                return idx
    return None


def _tokenize_choice_text(text: str) -> List[str]:
    raw = (text or "").strip()
    if not raw:
        return []

    main = re.split(r"[（(]", raw)[0].strip()
    candidates = [raw, main]

    cleaned = re.sub(r"[^\u4e00-\u9fff0-9a-zA-Z]+", " ", raw)
    parts = [p.strip() for p in cleaned.split() if p.strip()]

    out: List[str] = []
    for s in candidates + parts:
        ns = _norm_text(s)
        if len(ns) >= 2:
            out.append(ns)

    chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", raw)
    for run in chinese_runs:
        run = run.strip()
        for L in (2, 3, 4):
            if len(run) >= L:
                for i in range(0, len(run) - L + 1):
                    ng = _norm_text(run[i : i + L])
                    if len(ng) >= 2:
                        out.append(ng)

    seen = set()
    uniq: List[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _best_effort_match_choice(
    view_obj_or_json: Any, recognized_text: str
) -> Tuple[Optional[int], Optional[str], float, Optional[Dict[str, Any]]]:
    r = _norm_text(recognized_text)
    if not r:
        return None, None, 0.0, {"reason": "empty_recognized"}

    best_idx: Optional[int] = None
    best_text: Optional[str] = None
    best_score = 0.0
    best_dbg: Optional[Dict[str, Any]] = None

    for idx, t in _iter_choices(view_obj_or_json):
        if idx is None:
            continue
        if any(k in t for k in ADULT_FALLBACK_KEYWORDS):
            continue

        nt = _norm_text(t)
        if not nt:
            continue

        score = 0.0
        why = "none"

        if nt in r and len(nt) >= 2:
            score = 1.0
            why = "choice_in_recognized"
        elif r in nt and len(r) >= 2:
            score = 0.92
            why = "recognized_in_choice"
        else:
            tokens = _tokenize_choice_text(t)
            for tok in tokens:
                if len(tok) >= 2 and (tok in r or r in tok):
                    score = max(score, 0.86 if len(tok) >= 3 else 0.78)
                    why = f"token_hit:{tok}"
                    break

        if score > best_score:
            best_score = float(score)
            best_idx = idx
            best_text = t
            best_dbg = {"why": why, "choice": t, "recognized": recognized_text}

    return best_idx, best_text, float(best_score), best_dbg


# ----------------------------
# Preload helpers
# ----------------------------


def _count_scene01_start_narration(pkg: Any) -> int:
    """Return number of TTS-speakable narration paragraphs in scene_01_start node."""
    try:
        nodes = getattr(pkg, "nodes", None)
        if not isinstance(nodes, dict):
            return 0
        node = nodes.get("scene_01_start")
        if node is None:
            return 0

        # StoryNode.narration is List[NarrationItem]
        narration = getattr(node, "narration", None)
        if isinstance(narration, list):
            return sum(1 for item in narration if (getattr(item, "text", "") or "").strip())

        # Fallback: narration might be a raw string in edge cases
        if isinstance(narration, str):
            return len(_split_paragraphs(narration))

    except Exception as e:
        print(f"[PRELOAD] _count_scene01_start_narration err: {e!r}", flush=True)
    return 0


def _trigger_scene01_tts(
    *,
    request: Request,
    session_id: str,
    run_id: str,
    view_json: Dict[str, Any],
    count: int,
    background_tasks: Optional[BackgroundTasks] = None,
) -> None:
    """
    Kick off TTS generation for scene_01_start paragraphs 0..count-1.
    First paragraph is synchronous (so Flutter can start playing fast),
    the rest are queued as background tasks.
    """
    narration = (view_json.get("narration") or "").strip()
    if not narration or count == 0:
        return

    paras = _split_paragraphs(narration)
    if not paras:
        return

    # Use the per-session tts_runs location so /tts_status can find them
    cache_root = Path(os.getenv("QF_CACHE_DIR") or "/tmp/qf_cache").resolve()
    view_fp = _view_fp_for_narration(narration)

    # Try sample path first (runtime_sample) since this is where _build_sample_runtime_tts writes
    base_root = (cache_root / "runtime_sample").resolve()
    out_dir = (base_root / view_fp).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    def _synth(i: int, p: str) -> None:
        role, text = _parse_paragraph(p)
        spoken_text = (text or "").strip()
        if not spoken_text:
            return
        profile = voice_for_role(role)
        speed = _voice_speed_for_role(role)
        try:
            synthesize_to_wav(
                text=spoken_text,
                out_dir=out_dir,
                out_name=f"{i:03d}.wav",
                voice=profile.voice,
                instructions=profile.instructions,
                speed=speed,
            )
        except Exception as e:
            print(f"[PRELOAD_TTS] synth err i={i} err={e!r}", flush=True)

    # Sync: first paragraph (so Flutter can start immediately)
    if paras:
        _synth(0, paras[0])

    # Async: remaining paragraphs up to count
    if background_tasks is not None:
        for i, p in enumerate(paras[1:count], start=1):
            background_tasks.add_task(_synth, i, p)
    else:
        # No background tasks: do them inline (e.g., called without FastAPI context)
        for i, p in enumerate(paras[1:count], start=1):
            _synth(i, p)


class PreloadResponse(BaseModel):
    session_id: str
    bundle: BundleResponse
    events: List[str] = Field(default_factory=list)
    is_over: bool = False
    view_fp: str = ""
    preload_count: int = 0
    story_source: str = ""
    story_id: Optional[str] = None


# ----------------------------
# Routes
# ----------------------------


@router.post("/preload", response_model=PreloadResponse)
def preload_session(
    req: StartRequest, request: Request, background_tasks: BackgroundTasks
) -> PreloadResponse:
    """
    Splash-screen endpoint:
    1. Picks a story (AI-first, falls back to sample)
    2. Creates a session
    3. Starts generating scene_01_start TTS (first para sync, rest async)
    4. Returns view_fp + preload_count so Flutter can poll /tts_status until ready
    """
    sid = "pending"
    try:
        # ① Ensure pool & acquire story
        _pool.ensure_pool()
        acq = _pool.acquire_story()

        # ② Create session
        sid, session = store.create_from_story_pkg(
            pkg=acq.pkg,
            seed=req.seed,
            source=acq.source,
        )
        session.state.vars.setdefault("qf_story", {})
        session.state.vars["qf_story"].update({
            "source": acq.source,
            "story_id": acq.story_id,
        })

        run_id = store.get_current_run_id(sid) or ""

        # ③ Build first-view bundle (TTS also triggered inside here for first para)
        bundle, events, is_over = _bundle_from_session_and_step(
            request=request,
            session_id=sid,
            run_id=run_id,
            session=session,
            step=None,
            background_tasks=background_tasks,
        )

        # ④ Figure out view_fp and preload_count from scene_01_start
        view_json = bundle.view or {}
        narration = (view_json.get("narration") or "").strip()
        view_fp = _view_fp_for_narration(narration) if narration else ""
        preload_count = _count_scene01_start_narration(acq.pkg)

        # ⑤ Trigger remaining paragraphs beyond what _bundle_from_session_and_step already started
        # (It already does para 0 sync + rest async via _build_sample_runtime_tts,
        #  so we just ensure the count cap is applied correctly)
        print(
            f"[PRELOAD] sid={sid[:6]} source={acq.source} "
            f"view_fp={view_fp[:8]} preload_count={preload_count}",
            flush=True,
        )

        # ⑥ Background ensure pool for next players
        background_tasks.add_task(_pool.ensure_pool)

        return PreloadResponse(
            session_id=sid,
            bundle=bundle,
            events=events,
            is_over=is_over,
            view_fp=view_fp,
            preload_count=preload_count,
            story_source=acq.source,
            story_id=acq.story_id,
        )

    except Exception as e:
        tb = traceback.format_exc()
        print("[preload] error:", repr(e), flush=True)
        print(tb, flush=True)
        raise HTTPException(
            status_code=500, detail=f"preload_error: {type(e).__name__} {repr(e)}"
        )



@router.post("/start", response_model=StepResponse)
def start_session(
    req: StartRequest, request: Request, background_tasks: BackgroundTasks
) -> StepResponse:
    sid = "pending"
    p = ProgressLogger(sid="pending", label="START")

    try:
        p.log("create_session:begin", seed=req.seed)

        # ✅ Story Pool (Phase-1):
        # - If AI ready pool is empty, StoryPoolManager will fallback to sample_pool_json
        # - Flutter doesn't need to know which source it gets
        with p.timed("pool.acquire"):
            _pool.ensure_pool()
            acq = _pool.acquire_story()
            pkg = acq.pkg

        with p.timed("store.create_from_pkg"):
            sid, session = store.create_from_story_pkg(
                pkg=pkg,
                seed=req.seed,
                source=acq.source,
            )
            # ✅ 注入 story meta（超重要）
            session.state.vars.setdefault("qf_story", {})
            session.state.vars["qf_story"].update(
                {
                    "source": acq.source,
                    "story_id": acq.story_id,
                }
            )

        p = ProgressLogger(sid=sid, label="START")
        p.log("create_session:ok")

        run_id = store.get_current_run_id(sid) or ""
        p.log("run_id", run_id=run_id[:6] if run_id else "")

        # ✅ 2) 保底背景補故事（非阻塞），確保一直玩也有一直補
        ready = _pool._ready_count()
        pending = _pool._jobs_count()
        if (ready + pending) < 2:
            try:
                # 這裡可以用 background_tasks 來非同步執行確保池子
                background_tasks.add_task(_pool.ensure_pool)
            except Exception as e:
                print(f"[start] bg ensure_pool error: {e}", flush=True)

        # ✅ 3) 先回第一頁 bundle（第一頁語音也會在這裡產）
        with p.timed("build_bundle_first_view"):
            bundle, events, is_over = _bundle_from_session_and_step(
                request=request,
                session_id=sid,
                run_id=run_id,
                session=session,
                step=None,
                background_tasks=background_tasks,
            )

        # ✅ 2) B-1 pipeline：背景順序做 current_tts -> ai1+tts -> ai2+tts
        # 先保留（你之後正式接 Queue/Worker 後再把它換掉）
        # _bootstrap_background_pipeline(request, sid, seed=req.seed)

        p.log("api_start:return", events_count=len(events), is_over=is_over)
        return StepResponse(
            session_id=sid, bundle=bundle, events=events, is_over=is_over
        )

    except Exception as e:
        tb = traceback.format_exc()
        print("[api_start] error:", repr(e), flush=True)
        print(tb, flush=True)
        raise HTTPException(
            status_code=500, detail=f"start_error: {type(e).__name__} {repr(e)}"
        )


@router.post("/choose", response_model=StepResponse)
def choose_action(
    req: ChooseRequest, request: Request, background_tasks: BackgroundTasks
) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(type="choose", choice_index=req.choice_index)
    return _step_and_build_response(
        request=request,
        session_id=req.session_id,
        session=session,
        action=action,
        background_tasks=background_tasks,
    )


@router.post("/replay", response_model=StepResponse)
def replay_action(
    req: ReplayRequest, request: Request, background_tasks: BackgroundTasks
) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(type="replay")
    return _step_and_build_response(
        request=request,
        session_id=req.session_id,
        session=session,
        action=action,
        background_tasks=background_tasks,
    )


@router.post("/end_flow", response_model=StepResponse)
def end_flow_action(
    req: EndFlowRequest, request: Request, background_tasks: BackgroundTasks
) -> StepResponse:
    session_id = (req.session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    action = (req.end_action or "").strip()
    if not action:
        raise HTTPException(status_code=400, detail="end_action required")

    session = _get_session_or_404(session_id)
    step = session.step(PlayerAction(type="end_flow", end_action=action))

    # ✅ 你現在的 SessionStore 版本沒有 reset(case_id) 的 API
    # 如果你真的需要 restart_case，我建議做成：rotate_to_next1 的「重新開始」UX
    if action == "restart_case":
        run_id = store.get_current_run_id(session_id) or ""
        bundle, events, is_over = _bundle_from_session_and_step(
            request=request,
            session_id=session_id,
            run_id=run_id,
            session=session,
            step=None,
            background_tasks=background_tasks,
        )
        return StepResponse(
            session_id=session_id,
            bundle=bundle,
            events=["restart_case_no_reset_api"],
            is_over=False,
        )

    if action == "switch_case":
        # ✅ 1) 先拿 next1 的 prefetched bundle（有就秒回）
        pref1 = store.get_next1_prefetched_bundle(session_id)

        # ✅ 2) rotate：current <- next1, next1 <- next2, next2 <- new placeholder
        new_current, old_run = store.rotate_to_next1(session_id=session_id, seed=None)
        if new_current is None:
            raise HTTPException(status_code=500, detail="rotate_to_next1 failed")

        # ✅ 3) 刪掉舊 current 的音檔包（整個 run 資料夾）
        if old_run:
            _safe_rmtree(_runs_root() / session_id / old_run)

        # ✅ 4) 回 next1 預生成（最快）
        if pref1:
            bundle_obj = BundleResponse(**pref1)
            # 背景：補下一個（此時 next2 是 placeholder，pipeline 會把它換成新 AI 並產 TTS）
            _bootstrap_background_pipeline(request, session_id, seed=None)
            return StepResponse(
                session_id=session_id,
                bundle=bundle_obj,
                events=["switch_case", "rotate_next1_prefetched"],
                is_over=False,
            )

        # ✅ 5) fallback：如果還沒 prefetched，就現算一次 current 第一頁（通常也不慢）
        run_id = store.get_current_run_id(session_id) or ""
        bundle, events, is_over = _bundle_from_session_and_step(
            request=request,
            session_id=session_id,
            run_id=run_id,
            session=new_current,
            step=None,
            background_tasks=background_tasks,
        )
        _bootstrap_background_pipeline(request, session_id, seed=None)
        return StepResponse(
            session_id=session_id,
            bundle=bundle,
            events=["switch_case", "rotate_next1_fallback"],
            is_over=False,
        )

    if action == "quit":
        store.delete(session_id)
        _safe_rmtree(_runs_root() / session_id)
        return StepResponse(
            session_id=session_id,
            bundle=BundleResponse(
                view=None, ask=None, quiz=None, end=None, commands=None
            ),
            events=["quit"],
            is_over=True,
        )

    # default: use the step result we already computed
    run_id = store.get_current_run_id(session_id) or ""
    bundle, events, is_over = _bundle_from_session_and_step(
        request=request,
        session_id=session_id,
        run_id=run_id,
        session=session,
        step=step,
        background_tasks=background_tasks,
    )
    return StepResponse(
        session_id=session_id, bundle=bundle, events=events, is_over=is_over
    )


@router.post("/set_reasons", response_model=StepResponse)
def set_reasons_action(
    req: SetReasonsRequest, request: Request, background_tasks: BackgroundTasks
) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(
        type="set_reasons",
        reason_ids=list(req.reason_ids or []),
        reason_text=(req.reason_text or ""),
    )
    return _step_and_build_response(
        request=request,
        session_id=req.session_id,
        session=session,
        action=action,
        background_tasks=background_tasks,
    )


@router.post("/confirm_quiz", response_model=StepResponse)
def confirm_quiz_action(
    req: ConfirmQuizRequest, request: Request, background_tasks: BackgroundTasks
) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(
        type="confirm_quiz_answer",
        answers=list(req.answers or []),
        skipped=bool(req.skipped),
    )
    return _step_and_build_response(
        request=request,
        session_id=req.session_id,
        session=session,
        action=action,
        background_tasks=background_tasks,
    )


@router.post("/quit", response_model=StepResponse)
def api_quit(req: QuitRequest, request: Request, background_tasks: BackgroundTasks) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(type="quit")
    resp = _step_and_build_response(
        request=request,
        session_id=req.session_id,
        session=session,
        action=action,
        background_tasks=background_tasks,
    )
    store.delete(req.session_id)
    _safe_rmtree(_runs_root() / req.session_id)
    return resp


@router.post("/accuse_evaluate", response_model=AccuseEvaluateResponse)
def accuse_evaluate_action(
    req: AccuseEvaluateRequest, request: Request, background_tasks: BackgroundTasks
) -> AccuseEvaluateResponse:
    threshold = 0.6
    nudge_margin = 0.12
    auto_submit_delta = 0.15

    try:
        session = _get_session_or_404(req.session_id)

        if hasattr(session, "get_view"):
            view = session.get_view()
        elif hasattr(session, "view"):
            view = session.view()
        else:
            view = None

        recognized_text = (req.recognized_text or "").strip()
        teacher_idx = _find_teacher_choice_index(view)

        session.state.vars.pop("accuse_bucket", None)
        session.state.vars.pop("accuse_score", None)
        session.state.vars.pop("accuse_text", None)

        if not recognized_text:
            session.state.vars["accuse_bucket"] = "defer"
            session.state.vars["accuse_score"] = 0.0
            session.state.vars["accuse_text"] = ""
            return AccuseEvaluateResponse(
                decision="defer_to_teacher",
                score=0.0,
                threshold=threshold,
                fifi_reply="霏霏：欸…我剛剛沒聽清楚耶。你可以再說一次，或直接點下面也可以～",
                defer_choice_index=teacher_idx,
                auto_submit=False,
                ending_kind="defer",
                debug={"case": "empty_text", "teacher_idx": teacher_idx},
            )

        if _looks_like_teacher_intent(recognized_text):
            session.state.vars["accuse_bucket"] = "defer"
            session.state.vars["accuse_score"] = 0.0
            session.state.vars["accuse_text"] = recognized_text

            defer_auto_submit = (teacher_idx is not None) and (
                len(_norm_text(recognized_text)) >= 4
            )
            return AccuseEvaluateResponse(
                decision="defer_to_teacher",
                score=0.0,
                threshold=threshold,
                fifi_reply=f"霏霏：我聽到你說「{recognized_text}」。好～那我們先去問清楚，免得越講越亂。",
                defer_choice_index=teacher_idx,
                auto_submit=defer_auto_submit,
                ending_kind="defer",
                debug={
                    "case": "adult_intent",
                    "teacher_idx": teacher_idx,
                    "defer_auto_submit": defer_auto_submit,
                },
            )

        idx, text, score, mdbg = _best_effort_match_choice(view, recognized_text)

        if idx is not None and score >= threshold:
            bucket = "clear"
        elif idx is not None and score >= (threshold - nudge_margin):
            bucket = "nudge"
        else:
            bucket = "defer"

        session.state.vars["accuse_bucket"] = bucket
        session.state.vars["accuse_score"] = float(score or 0.0)
        session.state.vars["accuse_text"] = recognized_text
        if idx is not None:
            session.state.vars["accuse_choice_index"] = int(idx)

        accuse_auto_submit = bool(
            bucket == "clear" and float(score) >= (threshold + auto_submit_delta)
        )
        defer_auto_submit = bool(
            bucket == "defer"
            and teacher_idx is not None
            and len(_norm_text(recognized_text)) >= 4
        )

        if bucket == "clear":
            fifi = (
                f"霏霏：我聽到你說「{recognized_text}」。好～我們就照你說的方向講清楚。"
            )
        elif bucket == "nudge":
            fifi = f"霏霏：我聽到你說「{recognized_text}」。我懂～我再幫你補一句：有些話前後不太一樣，我們等等一起對一對。"
        else:
            fifi = f"霏霏：我聽到你說「{recognized_text}」。我們先不要急著喊名字，先去確認一下比較安心。"

        if bucket in ("clear", "nudge") and idx is not None:
            return AccuseEvaluateResponse(
                decision="accuse",
                score=float(score),
                threshold=threshold,
                fifi_reply=fifi,
                matched_choice_index=idx,
                matched_choice_text=text,
                defer_choice_index=teacher_idx,
                auto_submit=accuse_auto_submit,
                ending_kind=bucket,
                debug={
                    "case": "accuse_bucket",
                    "bucket": bucket,
                    "match": mdbg,
                    "teacher_idx": teacher_idx,
                },
            )

        return AccuseEvaluateResponse(
            decision="defer_to_teacher",
            score=float(score or 0.0),
            threshold=threshold,
            fifi_reply=fifi,
            matched_choice_index=None,
            matched_choice_text=None,
            defer_choice_index=teacher_idx,
            auto_submit=defer_auto_submit,
            ending_kind="defer",
            debug={
                "case": "defer_bucket",
                "bucket": bucket,
                "match": mdbg,
                "teacher_idx": teacher_idx,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        return AccuseEvaluateResponse(
            decision="defer_to_teacher",
            score=0.0,
            threshold=threshold,
            fifi_reply="霏霏：欸…剛剛好像卡一下。我們先慢慢講也沒關係～",
            matched_choice_index=None,
            matched_choice_text=None,
            defer_choice_index=None,
            auto_submit=False,
            ending_kind="defer",
            debug={"case": "exception", "error": repr(e)},
        )


class InitializeStoriesResponse(BaseModel):
    has_ai_stories: bool
    sample_stories: List[Dict[str, Any]] = Field(default_factory=list)
    skipped: Optional[bool] = None
    reason: Optional[str] = None
    queued: Optional[int] = None

class PoolStatusResponse(BaseModel):
    ready_count: int
    generating_count: int
    tts_ready_count: int
    target: int = 2

@router.get("/pool_status", response_model=PoolStatusResponse)
def pool_status() -> PoolStatusResponse:
    ready = _pool._ready_count()
    pending = _pool._jobs_count()
    
    tts_ready = 0
    tts_dir = Path(".qf_cache/pool_ai/tts")
    if tts_dir.exists():
        tts_ready = sum(1 for x in tts_dir.iterdir() if x.is_dir() and not x.name.startswith("."))
        
    return PoolStatusResponse(
        ready_count=ready,
        generating_count=pending,
        tts_ready_count=tts_ready,
        target=2,
    )

from questforge_server.redis_lock import get_redis_lock
LOCK_KEY = "qf:pool:lock"

@router.post("/initialize_stories", response_model=InitializeStoriesResponse)
def initialize_stories(request: Request, background_tasks: BackgroundTasks) -> InitializeStoriesResponse:
    lock = get_redis_lock()
    lock_token = None
    if lock:
        lock_token = lock.acquire(LOCK_KEY, ttl_seconds=15)
        if not lock_token:
            return InitializeStoriesResponse(has_ai_stories=False, skipped=True, reason="pool_lock_redis")

    try:
        pool_mgr = _pool
        ready_count = pool_mgr._ready_count()
        generating_count = pool_mgr._jobs_count()
        target = 2
        
        # ✅ 防呆: 數量夠就不排新的
        if (ready_count + generating_count) >= target:
            # 沒有 AI 故事時回傳 sample, 如果已經有了就回傳 true
            if ready_count > 0:
                return InitializeStoriesResponse(has_ai_stories=True, skipped=True, reason="pool_full")

        missing = target - (ready_count + generating_count)
        missing = max(0, missing)
        
        # 觸發 pool 確保排隊
        _pool.ensure_pool()
        
        if ready_count > 0:
            return InitializeStoriesResponse(has_ai_stories=True, queued=missing)

        # 沒有 AI 故事，回傳 sample 故事
        samples = []
        for p in pool_mgr._sample_repo._paths:
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                meta = raw.get("meta") or {}
                samples.append({
                    "source": "sample",
                    "title": meta.get("title") or "Unknown Title",
                    "brief": meta.get("brief") or "",
                    "file_name": p.name,
                })
            except Exception:
                pass

        return InitializeStoriesResponse(has_ai_stories=False, sample_stories=samples, queued=missing)
    finally:
        if lock and lock_token:
            lock.release(LOCK_KEY, lock_token)


class GenerateAiStoryRequest(BaseModel):
    # just an empty request for now, can accept params if needed
    pass


class GenerateAiStoryResponse(BaseModel):
    status: str
    message: str


@router.post("/generate_ai_story", response_model=GenerateAiStoryResponse)
def generate_ai_story(req: GenerateAiStoryRequest, background_tasks: BackgroundTasks) -> GenerateAiStoryResponse:
    # 強制觸發一次 AI 故事背景產生
    _pool.ensure_pool()
    return GenerateAiStoryResponse(status="ok", message="AI story generation started in background.")


class CleanupAiStoryRequest(BaseModel):
    story_id: str


class CleanupAiStoryResponse(BaseModel):
    status: str
    message: str


@router.post("/cleanup_ai_story", response_model=CleanupAiStoryResponse)
def cleanup_ai_story(req: CleanupAiStoryRequest) -> CleanupAiStoryResponse:
    story_id = req.story_id
    if not story_id:
        raise HTTPException(status_code=400, detail="Missing story_id")
    
    # 移除 local storage 的 story
    try:
        store_path = _pool._storage._cfg.root_dir / f"{story_id}.json"
        if store_path.exists():
            store_path.unlink()
            
        # 移除 tts pool 裡面的檔案
        tts_dir = Path(".qf_cache/pool_tts") / story_id
        _safe_rmtree(tts_dir)
        
        return CleanupAiStoryResponse(status="ok", message="Story cleaned up.")
    except Exception as e:
        return CleanupAiStoryResponse(status="error", message=str(e))

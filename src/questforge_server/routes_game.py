# src/questforge_server/routes_game.py
from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
import traceback
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from questforge_server.progress import ProgressLogger
from questforge.engine.actions import PlayerAction
from questforge.engine.session import GameSession, StepResult
from questforge_server.session_store import SessionStore
from questforge_server.tts_service import synthesize_to_wav
from questforge.ai.tts.voice_map import voice_for_role

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


def _prewarm_story_tts_all_nodes(*, session_id: str, run_id: str, session: GameSession) -> None:
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


# ----------------------------
# Bundle builder
# ----------------------------

def _bundle_from_session_and_step(
    *,
    request: Request,
    session_id: str,
    run_id: str,
    session: GameSession,
    step: Optional[StepResult],
) -> Tuple[BundleResponse, List[str], bool]:
    """
    產出 Flutter 端吃的 bundle：
    - bundle.view (NodeView json)
    - bundle.ask / quiz / end (overlay command)
    - bundle.commands (tts_playlist_v1 等)
    並把 commands 同步塞到 view.commands（方便 debug）
    """

    def _inject_story_meta(view_json: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
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

    def _make_tts_cmd_from_view_json(view_json: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        # ✅ TTS 總開關
        if not _env_bool("QF_TTS_ENABLED", True):
            return None

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

        view_fp = _view_fp_for_narration(narration)

        out_dir = _runs_root() / session_id / run_id / view_fp
        out_dir.mkdir(parents=True, exist_ok=True)

        base = str(request.base_url).rstrip("/")
        items: List[Dict[str, Any]] = []

        for i, p in enumerate(raw_paras):
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
            if r is None:
                continue

            url = f"{base}/static/tts_runs/{session_id}/{run_id}/{view_fp}/{r.filename}"

            items.append(
                {
                    "index": i,
                    "text": spoken_text,  # debug
                    "role": role,         # debug
                    "voice": profile.voice,  # debug
                    "speed": speed,       # debug
                    "format": "wav",
                    "path": url,
                }
            )

        if not items:
            return None

        return {
            "type": "tts_playlist_v1",
            "scope": "view",
            "status": "ok",
            "view_fp": view_fp,
            "items": items,
        }

    # ----------------------------
    # start: step is None
    # ----------------------------
    if step is None:
        view_obj = session.get_view()
        view_json = _to_json_dict(view_obj)
        view_json = _inject_story_meta(view_json)

        tts_cmd = _make_tts_cmd_from_view_json(view_json)
        commands_out = [tts_cmd] if tts_cmd else []

        if view_json is not None:
            v = dict(view_json)
            v["commands"] = commands_out if commands_out else None
            view_json = v

        return (
            BundleResponse(view=view_json, ask=None, quiz=None, end=None, commands=commands_out),
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

    tts_cmd = _make_tts_cmd_from_view_json(view_json)
    commands_out = [tts_cmd] if tts_cmd else []

    if view_json is not None:
        v = dict(view_json)
        v["commands"] = commands_out if commands_out else None
        view_json = v

    return (
        BundleResponse(view=view_json, ask=ask, quiz=quiz, end=end, commands=commands_out),
        events,
        is_over,
    )


def _step_and_build_response(
    *,
    request: Request,
    session_id: str,
    session: GameSession,
    action: PlayerAction,
) -> StepResponse:
    step = session.step(action)
    run_id = store.get_current_run_id(session_id) or ""
    bundle, events, is_over = _bundle_from_session_and_step(
        request=request,
        session_id=session_id,
        run_id=run_id,
        session=session,
        step=step,
    )
    return StepResponse(session_id=session_id, bundle=bundle, events=events, is_over=is_over)


# ----------------------------
# ✅ 方案 B-1：Bootstrap pipeline（順序：current_tts -> ai1+tts -> ai2+tts）
# ----------------------------

def _bootstrap_background_pipeline(request: Request, session_id: str, seed: Optional[int]) -> None:
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
                    _prewarm_story_tts_all_nodes(session_id=session_id, run_id=cur_run, session=cur)

            # 2) next1：build AI -> prewarm all -> prefetch first bundle
            print(f"[BOOT] sid={sid6} stage=build_ai1", flush=True)
            ok1 = store.build_ai_into_next1(session_id=session_id, seed=seed, stage="bootstrap_ai1")
            if ok1:
                next1 = store.get_next1(session_id)
                run1 = store.get_next1_run_id(session_id) or ""
                if tts_enabled and prewarm_enabled and next1 is not None and run1:
                    print(f"[BOOT] sid={sid6} stage=ai1_tts", flush=True)
                    _prewarm_story_tts_all_nodes(session_id=session_id, run_id=run1, session=next1)

                if next1 is not None and run1:
                    bundle, _, _ = _bundle_from_session_and_step(
                        request=request,
                        session_id=session_id,
                        run_id=run1,
                        session=next1,
                        step=None,
                    )
                    store.set_next1_prefetched_bundle(session_id, _bundle_to_raw_dict(bundle))
                    print(f"[BOOT] sid={sid6} ai1_prefetched ok", flush=True)

            # 3) next2：build AI -> prewarm all -> prefetch first bundle
            print(f"[BOOT] sid={sid6} stage=build_ai2", flush=True)
            ok2 = store.build_ai_into_next2(session_id=session_id, seed=seed, stage="bootstrap_ai2")
            if ok2:
                next2 = store.get_next2(session_id)
                run2 = store.get_next2_run_id(session_id) or ""
                if tts_enabled and prewarm_enabled and next2 is not None and run2:
                    print(f"[BOOT] sid={sid6} stage=ai2_tts", flush=True)
                    _prewarm_story_tts_all_nodes(session_id=session_id, run_id=run2, session=next2)

                if next2 is not None and run2:
                    bundle, _, _ = _bundle_from_session_and_step(
                        request=request,
                        session_id=session_id,
                        run_id=run2,
                        session=next2,
                        step=None,
                    )
                    store.set_next2_prefetched_bundle(session_id, _bundle_to_raw_dict(bundle))
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
# Routes
# ----------------------------

@router.post("/start", response_model=StepResponse)
def api_start(req: StartRequest, request: Request) -> StepResponse:
    sid = "pending"
    p = ProgressLogger(sid="pending", label="START")

    try:
        p.log("create_session:begin", seed=req.seed)
        with p.timed("store.create"):
            sid, session = store.create(seed=req.seed)

        p = ProgressLogger(sid=sid, label="START")
        p.log("create_session:ok")

        run_id = store.get_current_run_id(sid) or ""
        p.log("run_id", run_id=run_id[:6] if run_id else "")

        # ✅ 1) 先回第一頁 bundle（第一頁語音也會在這裡產）
        with p.timed("build_bundle_first_view"):
            bundle, events, is_over = _bundle_from_session_and_step(
                request=request,
                session_id=sid,
                run_id=run_id,
                session=session,
                step=None,
            )

        # ✅ 2) B-1 pipeline：背景順序做 current_tts -> ai1+tts -> ai2+tts
        _bootstrap_background_pipeline(request, sid, seed=req.seed)

        p.log("api_start:return", events_count=len(events), is_over=is_over)
        return StepResponse(session_id=sid, bundle=bundle, events=events, is_over=is_over)

    except Exception as e:
        tb = traceback.format_exc()
        print("[api_start] error:", repr(e), flush=True)
        print(tb, flush=True)
        raise HTTPException(status_code=500, detail=f"start_error: {type(e).__name__} {repr(e)}")


@router.post("/choose", response_model=StepResponse)
def api_choose(req: ChooseRequest, request: Request) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(type="choose", choice_index=req.choice_index)
    return _step_and_build_response(
        request=request,
        session_id=req.session_id,
        session=session,
        action=action,
    )


@router.post("/replay", response_model=StepResponse)
def api_replay(req: ReplayRequest, request: Request) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(type="replay")
    return _step_and_build_response(
        request=request,
        session_id=req.session_id,
        session=session,
        action=action,
    )


@router.post("/end_flow", response_model=StepResponse)
def api_end_flow(req: EndFlowRequest, request: Request) -> StepResponse:
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
            bundle=BundleResponse(view=None, ask=None, quiz=None, end=None, commands=None),
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
    )
    return StepResponse(session_id=session_id, bundle=bundle, events=events, is_over=is_over)


@router.post("/set_reasons", response_model=StepResponse)
def api_set_reasons(req: SetReasonsRequest, request: Request) -> StepResponse:
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
    )


@router.post("/confirm_quiz", response_model=StepResponse)
def api_confirm_quiz(req: ConfirmQuizRequest, request: Request) -> StepResponse:
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
    )


@router.post("/quit", response_model=StepResponse)
def api_quit(req: QuitRequest, request: Request) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(type="quit")
    resp = _step_and_build_response(
        request=request,
        session_id=req.session_id,
        session=session,
        action=action,
    )
    store.delete(req.session_id)
    _safe_rmtree(_runs_root() / req.session_id)
    return resp


@router.post("/accuse_evaluate", response_model=AccuseEvaluateResponse)
def api_accuse_evaluate(req: AccuseEvaluateRequest) -> AccuseEvaluateResponse:
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

# src/questforge_server/routes_game.py
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import threading
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from questforge_server.progress import ProgressLogger
from questforge.content.cases import CASES
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


# ----------------------------
# TTS helpers (方案 B：全故事預產)
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
    # ✅ 必須跟 _make_tts_cmd_from_view_json 一樣的算法，才能共用 cache
    return hashlib.sha1(("v2|" + (narration or "")).encode("utf-8")).hexdigest()


def _runs_root() -> Path:
    # ✅ 你現有的路徑
    return Path(".qf_cache/tts_runs").resolve()


def _prewarm_story_tts_all_nodes(
    *,
    session_id: str,
    run_id: str,
    session: GameSession,
) -> None:
    """
    ✅ 方案 B：一次把整個故事所有 node narration 的語音都產好。
    只要 synthesize_to_wav 有 cache（檔案存在就快速返回），後面 choose 幾乎不會卡。
    """
    try:
        nodes = getattr(session, "nodes", {}) or {}
        base_dir = _runs_root() / session_id / run_id
        base_dir.mkdir(parents=True, exist_ok=True)

        clips = 0
        node_total = len([1 for _, n in (nodes or {}).items() if isinstance(n, dict)])
        node_done = 0
        p_every = 10  # 每 10 段印一次

        print(f"[PREWARM] begin sid={session_id[:6]} run={run_id[:6]}", flush=True)

        for node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            narration = (node.get("narration") or "").strip()
            if not narration:
                continue

            node_done += 1
            if node_done == 1 or node_done % 2 == 0:
                print(
                    f"[PREWARM] sid={session_id[:6]} node={node_done}/{node_total} node_id={node_id} clips={clips}",
                    flush=True,
                )
            paras = _split_paragraphs(narration)
            print(
                f"[PREWARM] node {node_done}/{node_total} id={node_id} paras={len(paras)}",
                flush=True,
            )

            view_fp = _view_fp_for_narration(narration)
            out_dir = base_dir / view_fp
            out_dir.mkdir(parents=True, exist_ok=True)

            for i, p in enumerate(paras, start=1):
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
                    if clips % 10 == 0:
                        print(
                            f"[PREWARM] sid={session_id[:6]} clips={clips}", flush=True
                        )
                if (i % p_every) == 0 or i == len(paras):
                    print(
                        f"[PREWARM] node={node_id} {i}/{len(paras)} clips={clips}",
                        flush=True,
                    )

        print(
            f"[PREWARM] done sid={session_id[:6]} run={run_id[:6]} clips={clips}",
            flush=True,
        )

        print(
            f"[PREWARM] done sid={session_id[:6]} run={run_id[:6]} clips={clips}",
            flush=True,
        )
    except Exception as e:
        print(f"[PREWARM] fail sid={session_id[:6]} err={e!r}", flush=True)


def _safe_rmtree(p: Path) -> None:
    try:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


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
    並額外把 commands 同步塞到 view.commands 方便 debug。
    """

    def _make_tts_cmd_from_view_json(
        view_json: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
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
            print(
                f"[TTS] view={view_fp[:8]} i={i}/{len(raw_paras)} role={role} ...",
                flush=True,
            )

            items.append(
                {
                    "index": i,
                    "text": spoken_text,  # debug
                    "role": role,  # debug
                    "voice": profile.voice,  # debug
                    "speed": speed,  # debug
                    "format": "wav",
                    "path": url,
                }
            )

        if not items:
            return None

        # ✅ 只保留最新兩個 run（current + next）=> 這裡是 per-session/run 資料夾
        def _cleanup_keep_latest_runs(root: Path, keep: int = 2) -> None:
            try:
                if not root.exists():
                    return
                sess_dir = root / session_id
                if not sess_dir.exists():
                    return

                dirs = [p for p in sess_dir.iterdir() if p.is_dir()]
                if len(dirs) <= keep:
                    return

                dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
                for d in dirs[keep:]:
                    _safe_rmtree(d)
            except Exception:
                return

        _cleanup_keep_latest_runs(_runs_root(), keep=2)

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

        tts_cmd = _make_tts_cmd_from_view_json(view_json)
        commands_out = [tts_cmd] if tts_cmd else []

        if view_json is not None:
            view_json = dict(view_json)
            view_json["commands"] = commands_out if commands_out else None

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
        view_json = dict(view_json)
        view_json["commands"] = commands_out if commands_out else None

    print("[BUNDLE] out.commands_count =", len(commands_out), flush=True)

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
    return StepResponse(
        session_id=session_id, bundle=bundle, events=events, is_over=is_over
    )


# ----------------------------
# Next prefetch (含全故事 prewarm)
# ----------------------------


def _prefetch_next_bundle_in_background(request: Request, session_id: str) -> None:
    """
    背景做：
    1) materialize next AI（保留你原本的保險，避免 next 還是舊 case）
    2) prewarm next 全故事語音（方案 B）
    3) 產 next 第一頁 bundle + playlist，快取到 store
    """

    def _job() -> None:
        try:
            # ✅ 1) 先把 next 變成 AI 案件（nodes）
            store.materialize_next_ai_case(session_id)

            # ✅ 2) prewarm next 全故事
            next_sess = store.get_next(session_id)
            next_run_id = store.get_next_run_id(session_id) or ""
            if next_sess is None or not next_run_id:
                return

            _prewarm_story_tts_all_nodes(
                session_id=session_id,
                run_id=next_run_id,
                session=next_sess,
            )

            # ✅ 3) 再用 next session 產第一頁 bundle（此時幾乎都是 cache hit）
            bundle, _, _ = _bundle_from_session_and_step(
                request=request,
                session_id=session_id,
                run_id=next_run_id,
                session=next_sess,
                step=None,
            )
            store.set_next_prefetched_bundle(session_id, _bundle_to_raw_dict(bundle))
            print(
                f"[PREFETCH] ok sid={session_id[:6]} run={next_run_id[:6]}", flush=True
            )
        except Exception as e:
            print(f"[PREFETCH] fail sid={session_id[:6]} err={e!r}", flush=True)

    threading.Thread(target=_job, daemon=True).start()


# ----------------------------
# Accuse evaluator helpers (你原本那套保留)
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

        # ✅ 1) 先回第一頁 bundle（不要被全故事 TTS 卡住）
        with p.timed("build_bundle_first_view"):
            bundle, events, is_over = _bundle_from_session_and_step(
                request=request,
                session_id=sid,
                run_id=run_id,
                session=session,
                step=None,
            )

        # ✅ 2) current 全故事 prewarm 改背景 + 進度 log
        if run_id:
            p.log("prewarm_current_all_nodes:spawn")

            def _prewarm_job() -> None:
                t0 = time.time()
                print(f"[PREWARM] begin sid={sid[:6]} run={run_id[:6]}", flush=True)
                _prewarm_story_tts_all_nodes(
                    session_id=sid, run_id=run_id, session=session
                )
                dt = time.time() - t0
                print(
                    f"[PREWARM] end   sid={sid[:6]} run={run_id[:6]} dt={dt:.2f}s",
                    flush=True,
                )

            threading.Thread(target=_prewarm_job, daemon=True).start()

        # ✅ 3) next 照舊背景 prefetch
        p.log("prefetch_next:spawn")
        _prefetch_next_bundle_in_background(request, sid)

        p.log("api_start:return", events_count=len(events), is_over=is_over)
        return StepResponse(
            session_id=sid, bundle=bundle, events=events, is_over=is_over
        )

    except Exception as e:
        tb = traceback.format_exc()
        print("[api_start] error:", repr(e), flush=True)
        print(tb, flush=True)
        raise HTTPException(
            status_code=500,
            detail=f"start_error: {type(e).__name__} {repr(e)}",
        )


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

    if action == "restart_case":
        case_id = store.get_case_id(session_id) or "2"
        new_sess, old_run = store.reset(
            session_id=session_id, case_id=case_id, seed=None
        )
        if new_sess is None:
            raise HTTPException(status_code=500, detail="reset failed")

        # ✅ 刪舊 run
        if old_run:
            _safe_rmtree(_runs_root() / session_id / old_run)

        run_id = store.get_current_run_id(session_id) or ""
        if run_id:
            _prewarm_story_tts_all_nodes(
                session_id=session_id, run_id=run_id, session=new_sess
            )

        bundle, events, is_over = _bundle_from_session_and_step(
            request=request,
            session_id=session_id,
            run_id=run_id,
            session=new_sess,
            step=None,
        )
        return StepResponse(
            session_id=session_id,
            bundle=bundle,
            events=["restart_case"],
            is_over=False,
        )

    if action == "switch_case":
        # ✅ 1) 先拿 B 的預生成 bundle（如果有，就能秒回）
        prefetched = store.get_next_prefetched_bundle(session_id)

        # ✅ 2) swap: B -> current, 同時生成新的 next=C
        new_current, old_run = store.swap_to_next_and_prefetch(
            session_id=session_id, seed=None
        )
        if new_current is None:
            raise HTTPException(status_code=500, detail="swap_to_next failed")

        # ✅ 3) 刪掉 A 的音檔包（整個 run 資料夾）
        if old_run:
            _safe_rmtree(_runs_root() / session_id / old_run)

        # ✅ 4) 回 B 的預生成（最快路徑）
        if prefetched:
            bundle_obj = BundleResponse(**prefetched)

            # 背景生 C（materialize + 全故事 prewarm + 第一頁快取）
            _prefetch_next_bundle_in_background(request, session_id)

            return StepResponse(
                session_id=session_id,
                bundle=bundle_obj,
                events=["switch_case", "swap_to_next_prefetched"],
                is_over=False,
            )

        # ✅ 5) fallback：如果 B 還沒預生成完，就現算一次（此時通常 prewarm 已做過，會快很多）
        run_id = store.get_current_run_id(session_id) or ""
        bundle, events, is_over = _bundle_from_session_and_step(
            request=request,
            session_id=session_id,
            run_id=run_id,
            session=new_current,
            step=None,
        )

        _prefetch_next_bundle_in_background(request, session_id)
        return StepResponse(
            session_id=session_id,
            bundle=bundle,
            events=["switch_case", "swap_to_next_fallback"],
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
    )
    return StepResponse(
        session_id=session_id, bundle=bundle, events=events, is_over=is_over
    )


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

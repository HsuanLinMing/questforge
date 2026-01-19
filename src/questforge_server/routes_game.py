# src/questforge_server/routes_game.py
from __future__ import annotations
import traceback
import random
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from questforge.engine.actions import PlayerAction
from questforge.engine.session import GameSession, StepResult
from questforge_server.session_store import SessionStore
from questforge.content.cases import CASES

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
    auto_submit: Optional[bool] = None
    debug: Optional[Dict[str, Any]] = None


class BundleResponse(BaseModel):
    # 你現在 Flutter 端用的是 bundle.view/ask/quiz/end，所以固定保持這四個 key
    view: Optional[Dict[str, Any]] = None
    ask: Optional[Dict[str, Any]] = None
    quiz: Optional[Dict[str, Any]] = None
    end: Optional[Dict[str, Any]] = None


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


def _bundle_from_session_and_step(
    *,
    session: GameSession,
    step: Optional[StepResult],
) -> Tuple[BundleResponse, List[str], bool]:
    """
    將 engine 的 StepResult(commands/events/view/is_over) 轉成
    Flutter 端需要的 bundle(view/ask/quiz/end)
    """
    events: List[str] = []
    is_over = False

    if step is None:
        # start: 只拿 view
        view_obj = session.get_view()
        return (
            BundleResponse(view=_to_json_dict(view_obj), ask=None, quiz=None, end=None),
            [],
            False,
        )

    events = list(step.events or [])
    is_over = bool(step.is_over)

    # view：StepResult.view 可能是 NodeView 或 None
    view_json: Optional[Dict[str, Any]] = _to_json_dict(step.view)

    ask = None
    quiz = None
    end = None

    # commands：把 ask_reason/confirm_quiz/show_end_screen/show_reasoning_feedback 映射到 bundle
    for cmd in step.commands or []:
        if not isinstance(cmd, dict):
            continue
        t = (cmd.get("type") or "").strip()

        if t == "ask_reason":
            ask = cmd
        elif t == "confirm_quiz":
            quiz = cmd
        elif t == "show_end_screen":
            end = cmd
        elif t == "show_reasoning_feedback":
            # 目前 OverlayManagerV2 沒有這個 overlay 類型時，你可以先把它當 end 用（或之後擴充 overlay）
            # 先放 end，至少 Flutter 可以顯示出來（你之後可改成獨立 overlay）
            end = cmd

    return (
        BundleResponse(view=view_json, ask=ask, quiz=quiz, end=end),
        events,
        is_over,
    )


def _step_and_build_response(
    session_id: str, session: GameSession, action: PlayerAction
) -> StepResponse:
    step = session.step(action)
    bundle, events, is_over = _bundle_from_session_and_step(session=session, step=step)
    return StepResponse(
        session_id=session_id, bundle=bundle, events=events, is_over=is_over
    )


def _to_json_dict(obj: Any) -> Optional[Dict[str, Any]]:
    if obj is None:
        return None

    if isinstance(obj, dict):
        return obj

    # questforge views 通常會有 to_json()（你 curl 出來就是 nodeId camelCase）
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

    # pydantic v2
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass

    # 最後 fallback：盡量用 __dict__ 但不保證欄位命名正確
    try:
        return dict(obj.__dict__)
    except Exception:
        return None


def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    import re

    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^\u4e00-\u9fff0-9a-z]+", "", s)
    return s


TEACHER_KEYWORDS = [
    "交給老師",
    "老師",
    "我不確定",
    "不確定",
    "不知道",
    "我不知道",
    "隨便",
    "你決定",
    "想不到",
    "沒想法",
    "先交給",
]


def _looks_like_teacher_intent(text: str) -> bool:
    r = _norm_text(text)
    if not r:
        return False
    for k in TEACHER_KEYWORDS:
        if _norm_text(k) in r:
            return True
    return False


def _find_teacher_choice_index(view_json: Dict[str, Any]) -> Optional[int]:
    choices = (view_json or {}).get("choices") or []
    for c in choices:
        t = str((c or {}).get("text") or "").strip()
        for k in TEACHER_KEYWORDS:
            if k in t:
                try:
                    return int((c or {}).get("index"))
                except Exception:
                    pass
    return None


def _best_effort_match_choice(
    view_json: Dict[str, Any], recognized_text: str
) -> Tuple[Optional[int], Optional[str], float]:
    """Simple fuzzy match without AI. Return (idx, text, score)."""
    r = _norm_text(recognized_text)
    if not r:
        return None, None, 0.0

    best_idx: Optional[int] = None
    best_text: Optional[str] = None
    best_score = 0.0

    for c in (view_json or {}).get("choices") or []:
        t = str((c or {}).get("text") or "").strip()
        idx = (c or {}).get("index")

        # skip teacher option for matching suspects
        if any(k in t for k in TEACHER_KEYWORDS):
            continue

        nt = _norm_text(t)
        if not nt:
            continue

        score = 0.0
        if nt in r and len(nt) >= 2:
            score = 1.0
        elif r in nt and len(r) >= 2:
            score = 0.9
        else:
            # longest common substring length
            n = len(r)
            m = len(nt)
            dp = [0] * (m + 1)
            best = 0
            for i in range(1, n + 1):
                prev = 0
                for j in range(1, m + 1):
                    temp = dp[j]
                    if r[i - 1] == nt[j - 1]:
                        dp[j] = prev + 1
                        best = max(best, dp[j])
                    else:
                        dp[j] = 0
                    prev = temp
            if best >= 2:
                base = best / max(1, len(nt))
                score = base + (0.25 if best >= 3 else 0.12)

        if score > best_score:
            best_score = score
            try:
                best_idx = int(idx)
            except Exception:
                best_idx = None
            best_text = t

    return best_idx, best_text, float(best_score)


# ----------------------------
# Routes
# ----------------------------


@router.post("/accuse_evaluate", response_model=AccuseEvaluateResponse)
def api_accuse_evaluate(req: AccuseEvaluateRequest) -> AccuseEvaluateResponse:
    threshold = 0.6
    try:
        session = _get_session_or_404(req.session_id)

        # 兼容不同 session API
        if hasattr(session, "get_view"):
            view = session.get_view()
        elif hasattr(session, "view"):
            view = session.view()
        else:
            view = None

        view_json = _to_json_dict(view) if view is not None else {}
        recognized_text = (req.recognized_text or "").strip()
        teacher_idx = _find_teacher_choice_index(view_json)

        if not recognized_text:
            return AccuseEvaluateResponse(
                decision="defer_to_teacher",
                score=0.0,
                threshold=threshold,
                fifi_reply="霏霏：我剛剛沒有聽清楚耶～我們先把看到的交給老師，一起整理。",
                matched_choice_index=None,
                matched_choice_text=None,
                defer_choice_index=teacher_idx,
                auto_submit=False,
                debug={"empty": True},
            )

        if _looks_like_teacher_intent(recognized_text):
            return AccuseEvaluateResponse(
                decision="defer_to_teacher",
                score=0.0,
                threshold=threshold,
                fifi_reply=f"霏霏：我聽到你說「{recognized_text}」。沒關係～我們先把看到的交給老師，一起安心整理。",
                matched_choice_index=None,
                matched_choice_text=None,
                defer_choice_index=teacher_idx,
                auto_submit=False,
                debug={"teacher_intent": True},
            )

        idx, text, score = _best_effort_match_choice(view_json, recognized_text)
        if idx is not None and score >= threshold:
            return AccuseEvaluateResponse(
                decision="accuse",
                score=float(score),
                threshold=threshold,
                fifi_reply=f"霏霏：我聽到你說「{recognized_text}」。我先幫你整理：你覺得可能跟「{text}」有關。就算不完全確定也沒關係，我們可以請老師一起看。",
                matched_choice_index=idx,
                matched_choice_text=text,
                defer_choice_index=teacher_idx,
                auto_submit=False,
                debug={"matched": True},
            )

        return AccuseEvaluateResponse(
            decision="defer_to_teacher",
            score=float(score),
            threshold=threshold,
            fifi_reply=f"霏霏：我聽到你說「{recognized_text}」。你的想法很重要～但我們先不要急著指名，先交給老師一起整理會更安全。",
            matched_choice_index=None,
            matched_choice_text=None,
            defer_choice_index=teacher_idx,
            auto_submit=False,
            debug={"matched": False},
        )

    except Exception as e:
        # ✅ 保底：永遠回正常 JSON，不讓 Flutter 看到 500
        return AccuseEvaluateResponse(
            decision="defer_to_teacher",
            score=0.0,
            threshold=threshold,
            fifi_reply="霏霏：我先接住你的想法～我們把看到的交給老師，一起慢慢整理就好。",
            matched_choice_index=None,
            matched_choice_text=None,
            defer_choice_index=None,
            auto_submit=False,
            debug={"error": repr(e)},
        )


@router.post("/start", response_model=StepResponse)
def api_start(req: StartRequest) -> StepResponse:
    sid, session = store.create(seed=req.seed)
    bundle, events, is_over = _bundle_from_session_and_step(session=session, step=None)
    return StepResponse(session_id=sid, bundle=bundle, events=events, is_over=is_over)


@router.post("/choose", response_model=StepResponse)
def api_choose(req: ChooseRequest) -> StepResponse:
    session = _get_session_or_404(req.session_id)

    try:
        action = PlayerAction(type="choose", choice_index=req.choice_index)
        return _step_and_build_response(req.session_id, session, action)

    except AssertionError as e:
        # ✅ 這個最可能：assert 沒帶訊息時 str(e)==''，所以你才會看到 engine_error: ''
        raise HTTPException(
            status_code=400,
            detail=f"assertion_failed: {repr(e)}",
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        tb = traceback.format_exc()
        # ✅ 直接在 server console 印出完整 traceback（最重要）
        print("[routes_game] engine error:", type(e).__name__, repr(e))
        print(tb)

        # ✅ 回傳帶型別與 repr，避免空字串
        raise HTTPException(
            status_code=500,
            detail=f"engine_error: {type(e).__name__} {repr(e)}",
        )


@router.post("/replay", response_model=StepResponse)
def api_replay(req: ReplayRequest) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(type="replay")
    return _step_and_build_response(req.session_id, session, action)


# src/questforge_server/routes_game.py
@router.post("/end_flow", response_model=StepResponse)
def api_end_flow(req: EndFlowRequest) -> StepResponse:
    session_id = (req.session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    action = (req.end_action or "").strip()
    if not action:
        raise HTTPException(status_code=400, detail="end_action required")

    session = _get_session_or_404(session_id)

    # ✅ 先讓 engine 收到 end_flow（保留事件/紀錄）
    # 你目前 PlayerAction 用 type=... 的風格，所以沿用
    step = session.step(
        PlayerAction(
            type="end_flow",
            end_action=action,
        )
    )

    # ✅ FastAPI 模式：補上 CLI 那段「外層處理 restart/switch/quit」
    if action == "restart_case":
        case_id = store.get_case_id(session_id) or "2"
        new_sess = store.reset(session_id=session_id, case_id=case_id, seed=None)
        if new_sess is None:
            raise HTTPException(status_code=500, detail="reset failed")

        bundle, events, is_over = _bundle_from_session_and_step(
            session=new_sess, step=None
        )
        return StepResponse(
            session_id=session_id,
            bundle=bundle,
            events=["restart_case"],
            is_over=False,
        )

    if action == "switch_case":
        current = store.get_case_id(session_id)
        all_ids = list(CASES.keys())
        candidates = [cid for cid in all_ids if cid != current] or all_ids
        next_case_id = random.choice(candidates)

        new_sess = store.reset(session_id=session_id, case_id=next_case_id, seed=None)
        if new_sess is None:
            raise HTTPException(status_code=500, detail="reset failed")

        bundle, events, is_over = _bundle_from_session_and_step(
            session=new_sess, step=None
        )
        return StepResponse(
            session_id=session_id,
            bundle=bundle,
            events=["switch_case", f"case:{next_case_id}"],
            is_over=False,
        )

    if action == "quit":
        store.delete(session_id)
        return StepResponse(
            session_id=session_id,
            bundle=BundleResponse(view=None, ask=None, quiz=None, end=None),
            events=["quit"],
            is_over=True,
        )

    # 其他 end_action：照 step 結果回去
    bundle, events, is_over = _bundle_from_session_and_step(session=session, step=step)
    return StepResponse(
        session_id=session_id,
        bundle=bundle,
        events=events,
        is_over=is_over,
    )


@router.post("/set_reasons", response_model=StepResponse)
def api_set_reasons(req: SetReasonsRequest) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(
        type="set_reasons",
        reason_ids=list(req.reason_ids or []),
        reason_text=(req.reason_text or ""),
    )
    return _step_and_build_response(req.session_id, session, action)


@router.post("/confirm_quiz", response_model=StepResponse)
def api_confirm_quiz(req: ConfirmQuizRequest) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(
        type="confirm_quiz_answer",
        answers=list(req.answers or []),
        skipped=bool(req.skipped),
    )
    return _step_and_build_response(req.session_id, session, action)


@router.post("/quit", response_model=StepResponse)
def api_quit(req: QuitRequest) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(type="quit")
    resp = _step_and_build_response(req.session_id, session, action)

    # quit 後把 session 刪掉（dev store）
    store.delete(req.session_id)
    return resp

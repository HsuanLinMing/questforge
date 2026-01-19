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


# ----------------------------
# Routes
# ----------------------------


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

        bundle, events, is_over = _bundle_from_session_and_step(session=new_sess, step=None)
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

        bundle, events, is_over = _bundle_from_session_and_step(session=new_sess, step=None)
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

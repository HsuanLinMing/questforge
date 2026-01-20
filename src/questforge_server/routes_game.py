# src/questforge_server/routes_game.py
from __future__ import annotations

import random
import traceback
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from questforge.content.cases import CASES
from questforge.engine.actions import PlayerAction
from questforge.engine.session import GameSession, StepResult
from questforge_server.session_store import SessionStore

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
            # 目前 OverlayManagerV2 沒有這個 overlay 類型時，先放 end
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


# --- 2) 把 TEACHER_KEYWORDS 改成「交給大人/去確認」語氣（你不想突然老師登場） ---

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
    """
    兼容：
    - view_json: {"choices":[{"index":0,"text":"..."}]}
    - view_obj: NodeView.choices = [ChoiceView(...)]
    回傳 list of (index:int|None, text:str)
    """
    if view_obj_or_json is None:
        return []

    out: List[Tuple[Optional[int], str]] = []

    # dict json
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

    # object view
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
    """
    從 choice 文案切出候選 token（>=2字），讓孩子只講「飯糰/波波」也能命中。
    例：'飯糰啵啵（白色吊飾）' -> ['飯糰', '啵啵', '白色', '吊飾', '飯糰啵啵', ...ngram]
    """
    import re

    raw = (text or "").strip()
    if not raw:
        return []

    # 先取括號前的主名 + 全名
    main = re.split(r"[（(]", raw)[0].strip()
    candidates = [raw, main]

    # 去符號後切詞：中文/英文/數字連段
    cleaned = re.sub(r"[^\u4e00-\u9fff0-9a-zA-Z]+", " ", raw)
    parts = [p.strip() for p in cleaned.split() if p.strip()]

    out: List[str] = []
    for s in candidates + parts:
        ns = _norm_text(s)
        if len(ns) >= 2:
            out.append(ns)

    # 再補：中文連續片段的 2~4 字 ngram（提升片段命中）
    chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", raw)
    for run in chinese_runs:
        run = run.strip()
        for L in (2, 3, 4):
            if len(run) >= L:
                for i in range(0, len(run) - L + 1):
                    ng = _norm_text(run[i : i + L])
                    if len(ng) >= 2:
                        out.append(ng)

    # 去重但保留順序
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

        # skip adult fallback option for matching suspects
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

            if score <= 0.0:
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
                    why = f"lcs:{best}"

        if score > best_score:
            best_score = float(score)
            best_idx = idx
            best_text = t
            best_dbg = {"why": why, "choice": t, "recognized": recognized_text}

    return best_idx, best_text, float(best_score), best_dbg


# ----------------------------
# Routes
# ----------------------------


# --- 3) api_accuse_evaluate：把 ending_kind + score 存進 session.state.vars，讓 engine 用它導結局 ---


@router.post("/accuse_evaluate", response_model=AccuseEvaluateResponse)
def api_accuse_evaluate(req: AccuseEvaluateRequest) -> AccuseEvaluateResponse:
    threshold = 0.6
    nudge_margin = 0.12  # ✅ 差一點點：0.48~0.59 -> nudge
    auto_submit_delta = 0.15  # ✅ clear：>= 0.75 才建議直接自動送（可自行調）

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

        # 先清掉舊值避免殘留
        session.state.vars.pop("accuse_bucket", None)
        session.state.vars.pop("accuse_score", None)
        session.state.vars.pop("accuse_text", None)

        if not recognized_text:
            # 空字串：不自動送
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

        # 明確「先去確認/交給大人」
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

        # 做 fuzzy match（用來找「你是指誰」）
        idx, text, score, mdbg = _best_effort_match_choice(view, recognized_text)

        # ✅ bucket 決策（3 段）
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

        # auto_submit 規則：
        # - clear：高於 threshold+delta 才直接送
        # - nudge：不直接送（避免誤送），由孩子按「送出」即可
        # - defer：若有 fallback 且字夠長，允許直接送
        if bucket == "clear":
            accuse_auto_submit = bool(float(score) >= (threshold + auto_submit_delta))
        else:
            accuse_auto_submit = False

        if bucket == "defer":
            defer_auto_submit = (teacher_idx is not None) and (
                len(_norm_text(recognized_text)) >= 4
            )
        else:
            defer_auto_submit = False

        # ✅ fifi_reply：不要「線索口吻」，只接住 + 不說教
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
        raise HTTPException(
            status_code=400,
            detail=f"assertion_failed: {repr(e)}",
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        tb = traceback.format_exc()
        print("[routes_game] engine error:", type(e).__name__, repr(e))
        print(tb)
        raise HTTPException(
            status_code=500,
            detail=f"engine_error: {type(e).__name__} {repr(e)}",
        )


@router.post("/replay", response_model=StepResponse)
def api_replay(req: ReplayRequest) -> StepResponse:
    session = _get_session_or_404(req.session_id)
    action = PlayerAction(type="replay")
    return _step_and_build_response(req.session_id, session, action)


@router.post("/end_flow", response_model=StepResponse)
def api_end_flow(req: EndFlowRequest) -> StepResponse:
    session_id = (req.session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    action = (req.end_action or "").strip()
    if not action:
        raise HTTPException(status_code=400, detail="end_action required")

    session = _get_session_or_404(session_id)

    step = session.step(
        PlayerAction(
            type="end_flow",
            end_action=action,
        )
    )

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

    store.delete(req.session_id)
    return resp

# src/questforge_server/engine_adapter.py
from __future__ import annotations

from typing import Any, Dict, Optional

from questforge.core.models import GameConfig
from questforge.engine.session import GameSession


JsonMap = Dict[str, Any]


def start_session(session: GameSession, *, case_id: Optional[str], seed: Optional[int]) -> JsonMap:
    """Return UI contract payload dict."""
    # 你可能有 config/selector 之類，這裡先走最小可用。
    # ✅ 如果你已有「CaseSelector / CASES」邏輯在 session.start(...) 內，就直接用。
    # ✅ 如果 session.start 需要參數，照你的版本改這裡即可。
    if hasattr(session, "start"):
        if case_id is None and seed is None:
            view = session.start()
        else:
            # 嘗試帶參數（若你的 start 不吃這些，改成你實際的參數）
            view = session.start(case_id=case_id, seed=seed)  # type: ignore[arg-type]
    else:
        raise RuntimeError("GameSession.start() not found. Please adapt engine_adapter.py")

    # view 很可能已經是 NodeView / dict
    return _to_payload(view)


def choose(session: GameSession, *, choice_index: int) -> JsonMap:
    if hasattr(session, "choose"):
        view = session.choose(choice_index)  # type: ignore[misc]
    else:
        raise RuntimeError("GameSession.choose() not found. Please adapt engine_adapter.py")

    return _to_payload(view)


def _to_payload(view: Any) -> JsonMap:
    """Unify to dict.
    - if view has model_dump() (pydantic v2) or dict() (pydantic v1), use it
    - if already dict, return as-is
    """
    if isinstance(view, dict):
        return view
    if hasattr(view, "model_dump"):
        return view.model_dump()  # type: ignore[no-any-return]
    if hasattr(view, "dict"):
        return view.dict()  # type: ignore[no-any-return]
    # fallback: try __dict__
    if hasattr(view, "__dict__"):
        return dict(view.__dict__)
    raise RuntimeError(f"Unsupported view type: {type(view)}")

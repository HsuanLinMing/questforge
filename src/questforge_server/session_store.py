# src/questforge_server/session_store.py
from __future__ import annotations

import time
import uuid
from dataclasses import fields
from typing import Dict, Optional, Tuple

from questforge.core.models import DetectiveState, GameConfig
from questforge.engine.case_selector import CaseSelector
from questforge.engine.session import GameSession
from questforge.content.cases import CASES


class SessionStore:
    def __init__(self, ttl_seconds: int = 60 * 60) -> None:
        self.ttl_seconds = int(ttl_seconds or 0) or (60 * 60)
        self._items: Dict[str, Tuple[float, GameSession]] = {}
        self._case_by_sid: Dict[str, str] = {}  # ✅ 新增：sid -> case_id

    def _cleanup(self) -> None:
        now = time.time()
        expired = []
        for sid, (ts, _) in self._items.items():
            if now - ts > self.ttl_seconds:
                expired.append(sid)
        for sid in expired:
            self._items.pop(sid, None)
            self._case_by_sid.pop(sid, None)

    def get(self, session_id: str) -> Optional[GameSession]:
        self._cleanup()
        sid = (session_id or "").strip()
        if not sid:
            return None
        item = self._items.get(sid)
        if not item:
            return None
        ts, sess = item
        self._items[sid] = (time.time(), sess)
        return sess

    def get_case_id(self, session_id: str) -> Optional[str]:
        sid = (session_id or "").strip()
        if not sid:
            return None
        return self._case_by_sid.get(sid)

    def delete(self, session_id: str) -> None:
        sid = (session_id or "").strip()
        if not sid:
            return
        self._items.pop(sid, None)
        self._case_by_sid.pop(sid, None)

    def _build_session(self, case_id: str, seed: int | None = None) -> GameSession:
        case = CASES.get(case_id)
        if not case:
            # fallback：亂挑
            selector = CaseSelector(CASES)
            case_id, case = selector.pick()

        nodes = case.get("nodes") or {}
        start_node = (
            (case.get("start_node") or "").strip()
            or (case.get("start") or "").strip()   # ✅ 支援你現在 CASES 的 start
            or next(iter(nodes.keys()))
        )
        solve_rule = case.get("solve_rule") or {}

        config_kwargs = {}
        try:
            cfg_fields = {f.name for f in fields(GameConfig)}
            if seed is not None and "seed" in cfg_fields:
                config_kwargs["seed"] = int(seed)
        except Exception:
            pass
        config = GameConfig(**config_kwargs)  # type: ignore[arg-type]

        state = DetectiveState()
        return GameSession(
            state=state,
            nodes=nodes,
            start_node=start_node,
            config=config,
            solve_rule=solve_rule,
        )

    def create(self, seed: int | None = None) -> Tuple[str, GameSession]:
        self._cleanup()

        selector = CaseSelector(CASES)
        case_id, _case = selector.pick()

        session = self._build_session(case_id=case_id, seed=seed)

        sid = uuid.uuid4().hex
        self._items[sid] = (time.time(), session)
        self._case_by_sid[sid] = case_id  # ✅ 記住 case_id
        return sid, session

    def reset(self, session_id: str, case_id: str, seed: int | None = None) -> Optional[GameSession]:
        """✅ 用同一個 session_id 重開案件，Flutter 端不用換 sid。"""
        sid = (session_id or "").strip()
        if not sid:
            return None
        self._cleanup()
        session = self._build_session(case_id=case_id, seed=seed)
        self._items[sid] = (time.time(), session)
        self._case_by_sid[sid] = case_id
        return session
